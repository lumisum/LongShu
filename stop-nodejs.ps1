[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
$dashboardStop = Join-Path $root 'Projects\sec-filings-intel-glw\dashboard\stop-dashboard.ps1'
if (-not (Test-Path -LiteralPath $dashboardStop)) {
    throw "找不到工作台停止脚本：$dashboardStop"
}

$child = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $dashboardStop
) -Wait -PassThru -WindowStyle Hidden
if ($child.ExitCode -ne 0) { throw 'Node.js 实时工作台停止失败。' }
Write-Output 'Node.js 实时工作台已停止。'
