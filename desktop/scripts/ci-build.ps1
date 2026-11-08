# CI 分阶段构建入口：把 build.ps1 的一键流程拆成四个可独立观察的步骤。
# 这样 Windows runner 上任何一步失败，GitHub Actions 都会直接指向具体阶段，
# 同时把完整 transcript 落盘到 desktop/dist/logs/ 供 artifact 上传。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('frontend', 'runtime', 'host', 'installer')]
    [string]$Stage,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repoRoot = Split-Path $PSScriptRoot -Parent | Split-Path -Parent
$buildScript = Join-Path $repoRoot 'desktop\build.ps1'
$logDir = Join-Path $repoRoot 'desktop\dist\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "build-$Stage.log"

$params = @{
    Version   = $Version
    SkipTests = $true
}

switch ($Stage) {
    'frontend' {
        $params.SkipRuntime = $true
        $params.SkipHost = $true
        $params.SkipInstaller = $true
    }
    'runtime' {
        $params.SkipFrontend = $true
        $params.SkipHost = $true
        $params.SkipInstaller = $true
        # 前端阶段已经下载并放入 prereqs，后续阶段不再重复复制 150MB 安装器。
        $params.NoWebView2Bundle = $true
    }
    'host' {
        $params.SkipFrontend = $true
        $params.SkipRuntime = $true
        $params.SkipInstaller = $true
        $params.NoWebView2Bundle = $true
    }
    'installer' {
        $params.SkipFrontend = $true
        $params.SkipRuntime = $true
        $params.SkipHost = $true
        $params.NoWebView2Bundle = $true
    }
}

# 签名开关与 windows-release.yml 的输入 / secret 保持同一套规则。
$wantSign = ("$env:INPUT_SIGN" -eq 'true') -or
    (-not [string]::IsNullOrWhiteSpace($env:SIGN_PFX_BASE64))
if ($wantSign) {
    if ([string]::IsNullOrWhiteSpace($env:SIGN_PFX_BASE64)) {
        throw '已要求签名，但未配置 SIGN_PFX_BASE64 secret。'
    }
    if ([string]::IsNullOrWhiteSpace($env:SIGN_PFX_PASSWORD)) {
        throw '已配置 SIGN_PFX_BASE64，但未配置 SIGN_PFX_PASSWORD secret。'
    }
    $params.Sign = $true
    $params.RequireSignature = $true
}

Write-Host "==> CI 构建阶段：$Stage（版本 $Version）"
$transcriptStarted = $false
try {
    Start-Transcript -Path $logPath -Force | Out-Null
    $transcriptStarted = $true
    & $buildScript @params
}
catch {
    Write-Host "::error::桌面构建阶段 $Stage 失败：$($_.Exception.Message)"
    throw
}
finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    Write-Host "阶段日志：$logPath"
}
