# Phase 0：验证 Qdrant Windows 二进制在 loopback 上启动、就绪探测与基本读写。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$out = if ($env:SPIKE_OUT) { $env:SPIKE_OUT } else { 'desktop/spike/out/qdrant.json' }
$out = [System.IO.Path]::GetFullPath($out)
$result = [ordered]@{
  check    = 'qdrant'
  status   = 'fail'
  steps    = @()
  details  = [ordered]@{}
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

$work = Join-Path $env:RUNNER_TEMP 'qdrant-spike'
$process = $null
$version = '1.20.0'
$url = "https://github.com/qdrant/qdrant/releases/download/v$version/qdrant-x86_64-pc-windows-msvc.zip"

try {
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $zip = Join-Path $work 'qdrant.zip'
  Invoke-Step 'download' {
    curl.exe -fsSL --retry 3 --retry-delay 2 -o $zip $url
    if ($LASTEXITCODE -ne 0) { throw "curl 退出码 $LASTEXITCODE" }
    "已下载 $( (Get-Item $zip).Length ) 字节"
  }
  Invoke-Step 'sha256' {
    $hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash
    $result.details['sha256'] = $hash
    $hash
  }
  Invoke-Step 'extract' {
    Expand-Archive -Path $zip -DestinationPath $work -Force
    (Get-ChildItem -Path $work -Recurse -Filter 'qdrant.exe' | Select-Object -First 1).FullName
  } | ForEach-Object { $result.details['exe'] = $_ }

  $exe = $result.details['exe']
  if (-not $exe) { throw '解压后未找到 qdrant.exe' }

  $env:QDRANT__SERVICE__HOST = '127.0.0.1'
  $env:QDRANT__SERVICE__HTTP_PORT = '6333'
  $env:QDRANT__SERVICE__GRPC_PORT = '6334'
  $env:QDRANT__STORAGE__STORAGE_PATH = (Join-Path $work 'storage')
  $env:QDRANT__TELEMETRY_DISABLED = 'true'
  $result.details['telemetry_disabled_env'] = $true

  $stdout = Join-Path $work 'qdrant.log'
  $stderr = Join-Path $work 'qdrant.err.log'

  Invoke-Step 'start' {
    $script:process = Start-Process -FilePath $exe -PassThru -NoNewWindow `
      -WorkingDirectory (Split-Path -Parent $exe) `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    "pid=$($script:process.Id)"
  }

  Invoke-Step 'readyz' {
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
      if ($process.HasExited) {
        throw "Qdrant 提前退出，exit=$($process.ExitCode)：$(Get-Content $stderr -Raw -ErrorAction SilentlyContinue)"
      }
      try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:6333/readyz' -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $ready = $true; break }
      } catch {
        Start-Sleep -Seconds 1
      }
    }
    if (-not $ready) { throw '60 秒内 /readyz 未就绪' }
    'ready'
  }

  Invoke-Step 'version' {
    $root = Invoke-RestMethod -Uri 'http://127.0.0.1:6333/' -TimeoutSec 5
    $result.details['version'] = $root.version
    $root.version
  }

  Invoke-Step 'create_collection' {
    Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:6333/collections/spike' `
      -ContentType 'application/json' `
      -Body '{"vectors":{"size":4,"distance":"Cosine"}}' | Out-Null
    'ok'
  }

  Invoke-Step 'upsert_and_query' {
    Invoke-RestMethod -Method Put -Uri 'http://127.0.0.1:6333/collections/spike/points?wait=true' `
      -ContentType 'application/json' `
      -Body '{"points":[{"id":1,"vector":[0.1,0.2,0.3,0.4],"payload":{"note":"中文测试"}}]}' | Out-Null
    $query = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:6333/collections/spike/points/query' `
      -ContentType 'application/json' `
      -Body '{"query":[0.1,0.2,0.3,0.4],"limit":1,"with_payload":true}'
    $note = $query.result.points[0].payload.note
    if ($note -ne '中文测试') { throw "查询结果不一致：$note" }
    $note
  }

  Invoke-Step 'loopback_only' {
    $addresses = Get-NetTCPConnection -LocalPort 6333 -State Listen |
      Select-Object -ExpandProperty LocalAddress -Unique
    $result.details['listeners'] = @($addresses)
    if ($addresses -contains '0.0.0.0' -or $addresses -contains '::') {
      throw "Qdrant 监听了非 loopback 地址：$addresses"
    }
    ($addresses -join ',')
  }

  $logTail = Get-Content $stdout -Tail 40 -ErrorAction SilentlyContinue
  $result.details['log_tail'] = @($logTail)
  $result.status = 'pass'
  $result.summary = "Qdrant $version Windows 二进制在 loopback 可用，读写与中文 payload 正常"
} catch {
  $result.error = ($_ | Out-String)
  Write-Host $result.error
} finally {
  if ($process -and -not $process.HasExited) {
    try {
      Stop-Process -Id $process.Id -Force
      Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
    } catch {
      Write-Host "[warn] 停止 Qdrant 失败：$_"
    }
  }
  $result.steps = $steps
  $outDir = Split-Path -Parent $out
  if ($outDir) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
  $result | ConvertTo-Json -Depth 8 | Set-Content -Path $out -Encoding utf8
  Write-Host "结果已写入 $out"
}

if ($result.status -ne 'pass') { exit 1 }
