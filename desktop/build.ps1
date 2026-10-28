<#
.SYNOPSIS
  Kiwi Windows 桌面版一键打包。

.DESCRIPTION
  依次构建桌面前端、PyInstaller runtime、.NET WebView2 宿主与 Inno Setup 安装包。
  必须在 Windows 10/11 x64 上运行；产物默认输出到 desktop\dist。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Version 1.0.0
  powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Clean -SkipTests
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [switch]$Clean,
    [switch]$SkipFrontend,
    [switch]$SkipRuntime,
    [switch]$SkipHost,
    [switch]$SkipInstaller,
    [switch]$SkipDownloads,
    [switch]$SkipTests,
    [switch]$NoWebView2Bundle,
    [switch]$FixedWebView2,
    [switch]$Sign,
    [switch]$RequireSignature,
    [string]$OutputDir = '',
    [switch]$Bootstrap
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path $PSScriptRoot -Parent
$FrontendDir = Join-Path $RepoRoot 'frontend'
$BackendDir = Join-Path $RepoRoot 'backend'
$DesktopDir = Join-Path $RepoRoot 'desktop'
$CacheDir = Join-Path $DesktopDir '.cache'
$BuildDir = Join-Path $DesktopDir 'build'
$StageDir = Join-Path $BuildDir 'app'
# 安装器前置组件单独存放，不进入应用目录，避免随安装包落盘约 150MB。
$PrereqsDir = Join-Path $BuildDir 'prereqs'
$RuntimeDist = Join-Path $BuildDir 'runtime-dist'
$RuntimeWork = Join-Path $BuildDir 'runtime-work'
$DistDir = if ($OutputDir) { [IO.Path]::GetFullPath($OutputDir) } else { Join-Path $DesktopDir 'dist' }

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Info([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Gray
}

function Fail([string]$Message) {
    throw "构建失败：$Message"
}

function Test-Hash([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash
    return $actual -ieq $Expected
}

function Get-CachedFile {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$Sha256 = ''
    )
    if (Test-Path $Destination) {
        if ([string]::IsNullOrWhiteSpace($Sha256) -or (Test-Hash $Destination $Sha256)) {
            Write-Info "使用缓存 $(Split-Path $Destination -Leaf)"
            return
        }
        Write-Info "缓存校验失败，重新下载 $(Split-Path $Destination -Leaf)"
        Remove-Item $Destination -Force
    }
    if ($SkipDownloads) {
        Fail "缺少缓存文件 $Destination；-SkipDownloads 不会发起下载。"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
    Write-Step "下载 $Url"
    & curl.exe -fsSL --retry 3 --retry-delay 2 -o $Destination $Url
    if ($LASTEXITCODE -ne 0) {
        Fail "下载失败（curl 退出码 $LASTEXITCODE）：$Url"
    }
    if (-not [string]::IsNullOrWhiteSpace($Sha256) -and -not (Test-Hash $Destination $Sha256)) {
        Remove-Item $Destination -Force
        Fail "SHA-256 校验失败：$Destination"
    }
}

function Copy-Directory {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path $Source)) {
        Fail "缺少目录：$Source"
    }
    if (Test-Path $Destination) {
        Remove-Item $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
    Copy-Item -Path $Source -Destination $Destination -Recurse -Force
}

function Resolve-Tool([string]$Name, [string]$Hint, [string[]]$Candidates = @()) {
    # Windows 上 python 等名称可能同时命中应用商店别名与真实安装，取第一个可执行项。
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in $Candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    if ($Bootstrap) {
        return $null
    }
    Fail "未找到 $Name。$Hint"
}

function Install-BootstrapTool([string]$Id, [string]$Label) {
    if (-not $Bootstrap) {
        return
    }
    Write-Step "通过 winget 安装 $Label"
    & winget install --id $Id --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget 安装 $Label 失败（退出码 $LASTEXITCODE），请手动安装后重试。"
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Sign-File([string]$Path, [string]$SignTool) {
    if (-not $Sign) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($env:SIGN_PFX_BASE64)) {
        if ($RequireSignature) {
            Fail "已要求 -RequireSignature，但未设置 SIGN_PFX_BASE64。"
        }
        Write-Warning "未配置签名证书，跳过签名：$Path"
        return
    }
    if ([string]::IsNullOrWhiteSpace($env:SIGN_PFX_PASSWORD)) {
        Fail "已设置 SIGN_PFX_BASE64，但缺少 SIGN_PFX_PASSWORD。"
    }
    if (-not $SignTool) {
        Fail "未找到 signtool.exe，无法签名。请安装 Windows SDK 或去掉 -Sign。"
    }
    $pfx = Join-Path $env:TEMP "kiwi-sign-$PID.pfx"
    try {
        [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:SIGN_PFX_BASE64))
        & $SignTool sign /fd SHA256 /f $pfx /p $env:SIGN_PFX_PASSWORD `
            /tr http://timestamp.digicert.com /td SHA256 $Path
        if ($LASTEXITCODE -ne 0) {
            Fail "签名失败：$Path"
        }
    }
    finally {
        Remove-Item $pfx -Force -ErrorAction SilentlyContinue
    }
}

# --------------------------------------------------------------------------- #
# 环境检查
# --------------------------------------------------------------------------- #
Write-Step '检查构建环境'
if ($env:OS -ne 'Windows_NT') {
    Fail 'Windows 桌面版必须在 Windows 10/11 x64 上构建（不支持 Wine 交叉打包）。'
}
if (-not [Environment]::Is64BitOperatingSystem) {
    Fail '需要 64 位 Windows。'
}
if ($RequireSignature -and -not $Sign) {
    Fail '-RequireSignature 需要同时指定 -Sign。'
}
if ($Sign -and $RequireSignature -and [string]::IsNullOrWhiteSpace($env:SIGN_PFX_BASE64)) {
    Fail '-RequireSignature 需要同时提供 -Sign 与 SIGN_PFX_BASE64。'
}

if (-not $Version) {
    $package = Get-Content (Join-Path $FrontendDir 'package.json') -Raw | ConvertFrom-Json
    $Version = [string]$package.version
}
if ($Version -notmatch '^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$') {
    Fail "版本号无效：$Version（示例：1.0.0）"
}
Write-Info "版本：$Version"

# 离线扫描脚本始终用 Node 执行，即使跳过前端构建也需要。
$node = Resolve-Tool 'node' '请安装 Node.js 22（winget install OpenJS.NodeJS.LTS）'
if (-not $node) { Install-BootstrapTool 'OpenJS.NodeJS.LTS' 'Node.js LTS'; $node = Resolve-Tool 'node' '请安装 Node.js 22' }
if (-not $node) { Fail '仍找不到 node；请重新打开终端或手动安装 Node.js 22。' }
if (-not $SkipRuntime) {
    $uv = Resolve-Tool 'uv' '请安装 uv（winget install astral-sh.uv）'
    if (-not $uv) { Install-BootstrapTool 'astral-sh.uv' 'uv'; $uv = Resolve-Tool 'uv' '请安装 uv' }
    if (-not $uv) { Fail '仍找不到 uv；请重新打开终端或手动安装。' }
    $python = Resolve-Tool 'python' '请安装 Python 3.12（winget install Python.Python.3.12）'
    if (-not $python) { Install-BootstrapTool 'Python.Python.3.12' 'Python 3.12'; $python = Resolve-Tool 'python' '请安装 Python 3.12' }
    if (-not $python) { Fail '仍找不到 python；请重新打开终端或手动安装 Python 3.12。' }
    $pyVersion = (& $python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))").Trim()
    if ($pyVersion -ne '3.12') {
        Fail "PyInstaller 需要 Python 3.12，当前为 $pyVersion。"
    }
}
if (-not $SkipHost) {
    $dotnet = Resolve-Tool 'dotnet' '请安装 .NET 10 SDK（winget install Microsoft.DotNet.SDK.10）'
    if (-not $dotnet) { Install-BootstrapTool 'Microsoft.DotNet.SDK.10' '.NET SDK 10'; $dotnet = Resolve-Tool 'dotnet' '请安装 .NET 10 SDK' }
    if (-not $dotnet) { Fail '仍找不到 dotnet；请重新打开终端或手动安装 .NET 10 SDK。' }
    $dotnetVersion = (& $dotnet --version).Trim()
    if ($dotnetVersion -notmatch '^10\.') {
        Fail ".NET SDK 需要 10.x，当前为 $dotnetVersion。"
    }
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe'
)
$iscc = $null
if (-not $SkipInstaller) {
    $iscc = Resolve-Tool 'ISCC.exe' '请安装 Inno Setup 6（winget install JRSoftware.InnoSetup）' $isccCandidates
    if (-not $iscc) {
        Install-BootstrapTool 'JRSoftware.InnoSetup' 'Inno Setup 6'
        $iscc = Resolve-Tool 'ISCC.exe' '请安装 Inno Setup 6' $isccCandidates
    }
    if (-not $iscc) {
        Fail '仍找不到 ISCC.exe；请安装 Inno Setup 6 或使用 -SkipInstaller。'
    }
}

$signTool = $null
if ($Sign) {
    $signToolCandidates = @()
    $sdkRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'),
        (Join-Path $env:ProgramFiles 'Windows Kits\10\bin')
    )
    foreach ($root in $sdkRoots) {
        if (Test-Path $root) {
            $signToolCandidates += Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\' } |
                Sort-Object FullName -Descending |
                Select-Object -ExpandProperty FullName
        }
    }
    $signTool = Resolve-Tool 'signtool.exe' '请安装 Windows SDK 或去掉 -Sign' $signToolCandidates
    if (-not $signTool) {
        Fail '未找到 signtool.exe；请安装 Windows SDK 或去掉 -Sign。'
    }
}

if ($Clean) {
    Write-Step '清理构建目录'
    foreach ($path in @($BuildDir, $DistDir)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
        }
    }
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

# --------------------------------------------------------------------------- #
# 前端
# --------------------------------------------------------------------------- #
if (-not $SkipFrontend) {
    Write-Step '构建桌面前端（离线模式）'
    Push-Location $FrontendDir
    try {
        if ($SkipDownloads) {
            & npm.cmd ci --offline
        }
        else {
            & npm.cmd ci
        }
        if ($LASTEXITCODE -ne 0) { Fail 'npm ci 失败。' }
        & npm.cmd run build:desktop
        if ($LASTEXITCODE -ne 0) { Fail '桌面前端构建失败。' }
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path (Join-Path $FrontendDir 'dist\index.html'))) {
        Fail '未生成 frontend\dist\index.html。'
    }
}
Copy-Directory (Join-Path $FrontendDir 'dist') (Join-Path $StageDir 'resources\frontend')
& node (Join-Path $DesktopDir 'scripts\check-offline-dist.mjs') (Join-Path $StageDir 'resources\frontend')
if ($LASTEXITCODE -ne 0) { Fail '桌面产物包含远程资源引用。' }

# --------------------------------------------------------------------------- #
# Python runtime
# --------------------------------------------------------------------------- #
if (-not $SkipRuntime) {
    Write-Step '构建 Python runtime（PyInstaller onedir）'
    Push-Location $BackendDir
    try {
        if ($SkipDownloads) {
            & uv sync --frozen --extra dev --offline
        }
        else {
            & uv sync --frozen --extra dev
        }
        if ($LASTEXITCODE -ne 0) { Fail 'uv sync 失败。' }

        if ($SkipDownloads) {
            & uv pip install --offline -r (Join-Path $DesktopDir 'requirements-build.txt')
        }
        else {
            & uv pip install -r (Join-Path $DesktopDir 'requirements-build.txt')
        }
        if ($LASTEXITCODE -ne 0) { Fail '安装 PyInstaller / pgserver 失败。' }

        $venvPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
        if (-not (Test-Path $venvPython)) {
            Fail "未找到后端虚拟环境解释器：$venvPython"
        }

        if (-not $SkipTests) {
            Write-Step '后端检查（ruff + pytest）'
            & $venvPython -m ruff check app tests
            if ($LASTEXITCODE -ne 0) { Fail 'ruff 检查未通过。' }
            & $venvPython -m pytest -q
            if ($LASTEXITCODE -ne 0) { Fail '后端测试未通过。' }
        }

        & $venvPython -m PyInstaller (Join-Path $DesktopDir 'kiwi-runtime.spec') `
            --noconfirm --clean `
            --distpath $RuntimeDist --workpath $RuntimeWork
        if ($LASTEXITCODE -ne 0) { Fail 'PyInstaller 构建失败。' }
    }
    finally {
        Pop-Location
    }
    $runtimeExe = Join-Path $RuntimeDist 'kiwi-runtime\kiwi-runtime.exe'
    if (-not (Test-Path $runtimeExe)) {
        Fail "PyInstaller 未生成 runtime：$runtimeExe"
    }
    Sign-File $runtimeExe $signTool
    Copy-Directory (Join-Path $RuntimeDist 'kiwi-runtime') (Join-Path $StageDir 'runtime')
}

# --------------------------------------------------------------------------- #
# 第三方组件（Qdrant / 便携 Python / WebView2）
# --------------------------------------------------------------------------- #
$versions = Get-Content (Join-Path $DesktopDir 'versions.json') -Raw | ConvertFrom-Json
if (-not $SkipRuntime) {
    Write-Step '准备 Qdrant 与便携 Python'
    $qdrantArchive = Join-Path $CacheDir ("qdrant-$($versions.qdrant.version).zip")
    Get-CachedFile -Url $versions.qdrant.url -Destination $qdrantArchive -Sha256 $versions.qdrant.sha256
    $qdrantExtract = Join-Path $CacheDir 'qdrant-extract'
    if (Test-Path $qdrantExtract) { Remove-Item $qdrantExtract -Recurse -Force }
    Expand-Archive -Path $qdrantArchive -DestinationPath $qdrantExtract -Force
    $qdrantExe = Get-ChildItem -Path $qdrantExtract -Recurse -Filter qdrant.exe | Select-Object -First 1
    if (-not $qdrantExe) { Fail 'Qdrant 压缩包中未找到 qdrant.exe。' }
    Copy-Directory $qdrantExe.Directory.FullName (Join-Path $StageDir 'resources\qdrant')

    $pythonArchive = Join-Path $CacheDir ("python-$($versions.python.version).tar.gz")
    Get-CachedFile -Url $versions.python.url -Destination $pythonArchive -Sha256 $versions.python.sha256
    $pythonExtract = Join-Path $CacheDir 'python-extract'
    if (Test-Path $pythonExtract) { Remove-Item $pythonExtract -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $pythonExtract | Out-Null
    & tar.exe -xzf $pythonArchive -C $pythonExtract
    if ($LASTEXITCODE -ne 0) { Fail '解压便携 Python 失败。' }
    $portablePython = Get-ChildItem -Path $pythonExtract -Recurse -Filter python.exe | Select-Object -First 1
    if (-not $portablePython) { Fail '便携 Python 压缩包中未找到 python.exe。' }
    Copy-Directory $portablePython.Directory.FullName (Join-Path $StageDir 'resources\python')
    $sitePackages = Join-Path $StageDir 'resources\python\Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    Copy-Item (Join-Path $DesktopDir 'runtime\sitecustomize.py') (Join-Path $sitePackages 'sitecustomize.py') -Force

    $portableExe = Join-Path $StageDir 'resources\python\python.exe'
    if (-not $SkipDownloads) {
        # 用 find_spec 探测，避免 pip 缺失时向 stderr 打印 traceback 影响日志。
        & $portableExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
        if ($LASTEXITCODE -ne 0) {
            Write-Info '便携 Python 未自带 pip，执行 ensurepip'
            & $portableExe -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) { Fail '便携 Python 缺少 pip，且 ensurepip 失败。' }
        }
    }
    if ($SkipDownloads) {
        Write-Step '校验便携 Python 运行包（离线）'
        & $portableExe -c "import numpy, pandas, matplotlib, openpyxl, PIL; print('runner packages ok')"
        if ($LASTEXITCODE -ne 0) { Fail '便携 Python 缺少运行包；联网构建或手动预装。' }
    }
    else {
        Write-Step '安装便携 Python 运行包'
        & $portableExe -m pip install --disable-pip-version-check --no-warn-script-location `
            -r (Join-Path $DesktopDir 'requirements-runner.txt')
        if ($LASTEXITCODE -ne 0) { Fail '便携 Python 运行包安装失败。' }
        & $portableExe -c "import numpy, pandas, matplotlib, openpyxl, PIL; print('runner packages ok')"
        if ($LASTEXITCODE -ne 0) { Fail '便携 Python 运行包冒烟失败。' }
    }
}

if (-not $NoWebView2Bundle -and -not $FixedWebView2) {
    Write-Step '准备 WebView2 Evergreen 安装程序'
    $cached = Join-Path $CacheDir $versions.webView2.filename
    Get-CachedFile -Url $versions.webView2.url -Destination $cached
    # 仅供安装器 dontcopy 展开，不复制到应用目录。
    New-Item -ItemType Directory -Force -Path $PrereqsDir | Out-Null
    Copy-Item $cached (Join-Path $PrereqsDir $versions.webView2.filename) -Force
}

$fixedFlag = '0'
if ($FixedWebView2) {
    Write-Step '准备随包 WebView2 Fixed Version 运行时'
    if ([string]::IsNullOrWhiteSpace($versions.fixedWebView2.url) -or
        [string]::IsNullOrWhiteSpace($versions.fixedWebView2.sha256)) {
        Fail 'versions.json 的 fixedWebView2 未配置 URL / SHA-256，无法使用 -FixedWebView2。'
    }
    $cab = Join-Path $CacheDir 'webview2-fixed.cab'
    Get-CachedFile -Url $versions.fixedWebView2.url -Destination $cab -Sha256 $versions.fixedWebView2.sha256
    $fixedDir = Join-Path $StageDir 'WebView2FixedRuntime'
    if (Test-Path $fixedDir) { Remove-Item $fixedDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $fixedDir | Out-Null
    & expand.exe $cab -F:* $fixedDir
    if ($LASTEXITCODE -ne 0) { Fail '解压 WebView2 Fixed Version 失败。' }
    $fixedFlag = '1'
}

# --------------------------------------------------------------------------- #
# .NET 宿主
# --------------------------------------------------------------------------- #
if (-not $SkipHost) {
    Write-Step '发布 .NET WebView2 宿主'
    $csproj = Join-Path $DesktopDir 'Kiwi.Desktop\Kiwi.Desktop.csproj'
    & dotnet publish $csproj -c Release -r win-x64 --self-contained true `
        -p:PublishSingleFile=false -p:PublishTrimmed=false -p:DebugType=None `
        -p:Version=$Version -o $StageDir
    if ($LASTEXITCODE -ne 0) { Fail 'dotnet publish 失败。' }
    $hostExe = Join-Path $StageDir 'Kiwi.Desktop.exe'
    if (-not (Test-Path $hostExe)) { Fail "未生成宿主：$hostExe" }
    Sign-File $hostExe $signTool
}

$notices = Join-Path $RepoRoot 'THIRD-PARTY-NOTICES.md'
if (Test-Path $notices) {
    Copy-Item $notices (Join-Path $StageDir 'THIRD-PARTY-NOTICES.md') -Force
}
else {
    Write-Warning '缺少 THIRD-PARTY-NOTICES.md，安装包将不包含第三方声明。'
}

# AGPL-3.0 要求随分发提供许可证文本；随程序目录安装，便于卸载前查阅。
$license = Join-Path $RepoRoot 'LICENSE'
if (Test-Path $license) {
    Copy-Item $license (Join-Path $StageDir 'LICENSE') -Force
}
else {
    Write-Warning '缺少 LICENSE，安装包将不包含 AGPL 许可证文本。'
}

# --------------------------------------------------------------------------- #
# 安装器
# --------------------------------------------------------------------------- #
$installerPath = $null
if (-not $SkipInstaller) {
    Write-Step '生成 Inno Setup 安装包'
    & $iscc "/DAppVersion=$Version" "/DStageDir=$StageDir" "/DPrereqsDir=$PrereqsDir" `
        "/DOutputDir=$DistDir" "/DFixedWebView2=$fixedFlag" `
        (Join-Path $DesktopDir 'installer\kiwi.iss')
    if ($LASTEXITCODE -ne 0) { Fail 'Inno Setup 编译失败。' }
    $installerPath = Join-Path $DistDir "Kiwi-Setup-$Version.exe"
    if (-not (Test-Path $installerPath)) {
        Fail "未生成安装包：$installerPath"
    }
    Sign-File $installerPath $signTool
    $hash = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashFile = "$installerPath.sha256"
    "$hash  $(Split-Path $installerPath -Leaf)" | Set-Content -Path $hashFile -Encoding ASCII
    Write-Host "`n安装包：$installerPath" -ForegroundColor Green
    Write-Host "SHA-256：$hash" -ForegroundColor Green
}
else {
    Write-Host "`n已跳过安装器；暂存目录：$StageDir" -ForegroundColor Green
}

if ($RequireSignature) {
    $targets = @()
    if ($installerPath) { $targets += $installerPath }
    if (Test-Path (Join-Path $StageDir 'Kiwi.Desktop.exe')) { $targets += (Join-Path $StageDir 'Kiwi.Desktop.exe') }
    if (Test-Path (Join-Path $StageDir 'runtime\kiwi-runtime.exe')) { $targets += (Join-Path $StageDir 'runtime\kiwi-runtime.exe') }
    foreach ($target in $targets) {
        $signature = Get-AuthenticodeSignature -FilePath $target
        if ($signature.Status -ne 'Valid') {
            Fail "签名校验失败：$target（$($signature.Status)）"
        }
        Write-Info "签名有效：$target"
    }
}

Write-Host "`nKiwi $Version 桌面构建完成。" -ForegroundColor Green
