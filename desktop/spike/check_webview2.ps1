# Phase 0：验证 .NET 10 WinForms 发布与 WebView2 Evergreen 运行时检测。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out = if ($env:SPIKE_OUT) { $env:SPIKE_OUT } else { 'desktop/spike/out/webview2.json' }
$out = [System.IO.Path]::GetFullPath($out)
$result = [ordered]@{
  check   = 'webview2'
  status  = 'fail'
  steps   = @()
  details = [ordered]@{}
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

$work = Join-Path $env:RUNNER_TEMP 'webview2-spike'
$publish = Join-Path $work 'publish'
New-Item -ItemType Directory -Force -Path $work, $publish | Out-Null

try {
  Invoke-Step 'dotnet_sdks' { (dotnet --list-sdks | Out-String).Trim() }

  Invoke-Step 'publish' {
    dotnet publish desktop/spike/WebView2Probe/WebView2Probe.csproj `
      -c Release -r win-x64 --self-contained true -o $publish
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish 退出码 $LASTEXITCODE" }
    'published'
  }

  $exe = Join-Path $publish 'WebView2Probe.exe'
  if (-not (Test-Path $exe)) { throw "未生成 $exe" }
  $result.details['exe'] = $exe
  $result.details['publish_bytes'] = (
    Get-ChildItem -Path $publish -Recurse -File | Measure-Object -Property Length -Sum
  ).Sum
  $result.details['webview2_dlls'] = @(
    Get-ChildItem -Path $publish -Filter 'Microsoft.Web.WebView2*.dll' -Recurse |
      Select-Object -ExpandProperty Name
  )

  Invoke-Step 'probe' {
    $env:SPIKE_OUT = $out
    $output = & $exe 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "探针退出码 $LASTEXITCODE`n$output" }
    $output.Trim()
  }

  $probe = Get-Content $out -Raw | ConvertFrom-Json
  $result.details['probe'] = $probe
  if ($probe.status -ne 'pass') { throw "WebView2 检测失败：$($probe.error)" }
  $result.status = 'pass'
  $result.summary = ".NET 10 自包含发布成功，WebView2 运行时 $($probe.details.runtime_version)"
} catch {
  $result.error = ($_ | Out-String)
  Write-Host $result.error
} finally {
  $result.steps = $steps
  $outDir = Split-Path -Parent $out
  if ($outDir) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
  $result | ConvertTo-Json -Depth 12 | Set-Content -Path $out -Encoding utf8
  Write-Host "结果已写入 $out"
}

if ($result.status -ne 'pass') { exit 1 }
