# Phase 0：验证 PyInstaller 能把后端核心依赖冻结成 Windows onedir 并启动。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out = if ($env:SPIKE_OUT) { $env:SPIKE_OUT } else { 'desktop/spike/out/pyinstaller.json' }
$out = [System.IO.Path]::GetFullPath($out)
$result = [ordered]@{
  check   = 'pyinstaller'
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

$work = Join-Path $env:RUNNER_TEMP ("pyinstaller-spike-" + [guid]::NewGuid().ToString('N'))
$dist = Join-Path $work 'dist'
$build = Join-Path $work 'build'
$spec = Join-Path $work 'spec'
New-Item -ItemType Directory -Force -Path $work, $dist, $build, $spec | Out-Null

try {
  Invoke-Step 'pyinstaller_version' { python -m PyInstaller --version }

  Invoke-Step 'build' {
    python -m PyInstaller --noconfirm --clean --onedir --name kiwi-spike `
      --distpath $dist --workpath $build --specpath $spec `
      desktop/spike/pyinstaller_entry.py
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller 退出码 $LASTEXITCODE" }
    'built'
  }

  $exe = Join-Path $dist 'kiwi-spike\kiwi-spike.exe'
  if (-not (Test-Path $exe)) { throw "未生成 $exe" }
  $result.details['exe'] = $exe
  $result.details['dist_bytes'] = (
    Get-ChildItem -Path (Join-Path $dist 'kiwi-spike') -Recurse -File |
      Measure-Object -Property Length -Sum
  ).Sum

  Invoke-Step 'run_frozen_exe' {
    $env:SPIKE_OUT = $out
    Push-Location $env:RUNNER_TEMP
    try {
      $output = & $exe 2>&1 | Out-String
      if ($LASTEXITCODE -ne 0) { throw "冻结程序退出码 $LASTEXITCODE`n$output" }
      $output.Trim()
    } finally {
      Pop-Location
    }
  }

  $runtime = Get-Content $out -Raw | ConvertFrom-Json
  $result.details['runtime'] = $runtime
  if ($runtime.status -ne 'pass') { throw "冻结程序自测失败：$($runtime.error)" }
  $result.status = 'pass'
  $result.summary = 'PyInstaller onedir 可冻结后端核心依赖并启动本地 HTTP 服务'
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
