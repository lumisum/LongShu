$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$longshuRoot = (Resolve-Path (Join-Path $dashboardRoot '..\..\..')).Path
$logDir = Join-Path $longshuRoot 'Logs\sec-dashboard'
$pidFile = Join-Path $logDir 'server.pid'

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output '没有找到工作台 PID 文件。'
    exit 0
}

$dashboardPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $dashboardPid" -ErrorAction SilentlyContinue
$listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $dashboardPid }
if ($process -and $process.Name -eq 'node.exe' -and $process.CommandLine -like '*server.js*' -and $listener) {
    Stop-Process -Id $dashboardPid -Force
    Write-Output "SEC 实时工作台已停止（PID $dashboardPid）。"
} else {
    Write-Output 'PID 文件中的进程已结束或不属于 SEC 实时工作台。'
}
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
