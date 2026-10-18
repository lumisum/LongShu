$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$longshuRoot = (Resolve-Path (Join-Path $root '..\..\..')).Path
$logDir = Join-Path $longshuRoot 'Logs\sec-dashboard'
$pidFile = Join-Path $logDir 'server.pid'
$healthUrl = 'http://127.0.0.1:8090/api/health'

try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    if ($health.ok -and $health.database -eq 'sec_financials') {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $ownerId = (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)
        if ($ownerId) {
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
            if ($owner -and $owner.Name -eq 'node.exe' -and $owner.CommandLine -like '*server.js*') {
                Set-Content -LiteralPath $pidFile -Value $ownerId -Encoding ascii
            }
        }
        Write-Output 'SEC 实时工作台已运行：http://127.0.0.1:8090'
        exit 0
    }
} catch {}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$node = (Get-Command node -ErrorAction Stop).Source
$process = Start-Process -FilePath $node -ArgumentList (Join-Path $root 'server.js') -WorkingDirectory $root `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'server.log') `
    -RedirectStandardError (Join-Path $logDir 'server-error.log') -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii
Start-Sleep -Seconds 2
$health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 10
Write-Output "SEC 实时工作台已启动：http://127.0.0.1:8090（PID $($process.Id)）"
