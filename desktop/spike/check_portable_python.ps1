# Phase 0：验证 python-build-standalone 便携 Python 在 Windows 上运行数据科学栈。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out = if ($env:SPIKE_OUT) { $env:SPIKE_OUT } else { 'desktop/spike/out/portable-python.json' }
$out = [System.IO.Path]::GetFullPath($out)
$result = [ordered]@{
  check   = 'portable-python'
  status  = 'fail'
  steps   = @()
  details = [ordered]@{
    python_version = '3.12.16'
    release        = '20261026'
  }
}
$steps = [System.Collections.Generic.List[object]]::new()

function Invoke-Step {
  param([string]$Name, [scriptblock]$Body)
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $value = & $Body
    $steps.Add([ordered]@{
      name    = $Name
      status  = 'pass'
      seconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
      value   = "$value"
    })
    Write-Host "[pass] $Name -> $value"
    return $value
  } catch {
    $steps.Add([ordered]@{
      name    = $Name
      status  = 'fail'
      seconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
      error   = ($_ | Out-String)
    })
    Write-Host "[fail] $Name -> $_"
    throw
  }
}

$work = Join-Path $env:RUNNER_TEMP 'portable-python-spike'
$url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz'

try {
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $archive = Join-Path $work 'python.tar.gz'
  Invoke-Step 'download' {
    curl.exe -fsSL --retry 3 --retry-delay 2 -o $archive $url
    if ($LASTEXITCODE -ne 0) { throw "curl 退出码 $LASTEXITCODE" }
    "已下载 $( (Get-Item $archive).Length ) 字节"
  }
  Invoke-Step 'sha256' {
    $hash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash
    $result.details['sha256'] = $hash
    $hash
  }
  Invoke-Step 'extract' {
    tar.exe -xzf $archive -C $work
    if ($LASTEXITCODE -ne 0) { throw "tar 退出码 $LASTEXITCODE" }
    (Get-ChildItem -Path $work -Recurse -Filter 'python.exe' | Select-Object -First 1).FullName
  } | ForEach-Object { $result.details['python'] = $_ }

  $python = $result.details['python']
  if (-not $python) { throw '解压后未找到 python.exe' }

  Invoke-Step 'python_version' {
    (& $python --version 2>&1 | Out-String).Trim()
  } | ForEach-Object { $result.details['runtime_version'] = $_ }

  Invoke-Step 'pip_install' {
    & $python -m pip install --disable-pip-version-check --no-warn-script-location `
      numpy pandas matplotlib openpyxl pillow
    if ($LASTEXITCODE -ne 0) { throw "pip 退出码 $LASTEXITCODE" }
    'installed'
  }

  $env:SPIKE_OUT = $out
  & $python (Join-Path $PSScriptRoot 'check_portable_python_runtime.py')
  $probeExit = $LASTEXITCODE
  $runtime = $null
  if (Test-Path $out) {
    # 探针会先写 JSON 再打印；即使打印失败也能保留诊断信息。
    $runtime = Get-Content $out -Raw | ConvertFrom-Json
    $result.details['runtime'] = $runtime
  }
  if ($probeExit -ne 0) { throw "运行时探针退出码 $probeExit" }
  if (-not $runtime) { throw '运行时探针没有写出结果' }
  if ($runtime.status -ne 'pass') { throw "运行时探针失败：$($runtime.error)" }
  $result.status = 'pass'
  $result.summary = '便携 Python 可运行 numpy / pandas / matplotlib / openpyxl / pillow'
} catch {
  $result.error = ($_ | Out-String)
  Write-Host $result.error
} finally {
  $result.steps = $steps
  $outDir = Split-Path -Parent $out
  if ($outDir) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
  $result | ConvertTo-Json -Depth 10 | Set-Content -Path $out -Encoding utf8
  Write-Host "结果已写入 $out"
}

if ($result.status -ne 'pass') { exit 1 }
