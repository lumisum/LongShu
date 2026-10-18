[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
$dashboardDir = Join-Path $root 'Projects\sec-filings-intel-glw\dashboard'
$dashboardStart = Join-Path $dashboardDir 'start-dashboard.ps1'
$node = Get-Command node -ErrorAction Stop
$nodeVersion = (& $node.Source --version).Trim().TrimStart('v')
$nodeMajor = [int]($nodeVersion.Split('.')[0])
if ($nodeMajor -lt 22) {
    throw "LongShu 工作台要求 Node.js 22 或更高版本，当前版本为 $nodeVersion。"
}

if (-not (Test-Path -LiteralPath (Join-Path $dashboardDir 'node_modules\pg'))) {
    $npm = Get-Command npm.cmd -ErrorAction Stop
    $env:npm_config_cache = Join-Path $root 'Cache\npm'
    New-Item -ItemType Directory -Force -Path $env:npm_config_cache | Out-Null
    Push-Location $dashboardDir
    try {
        & $npm.Source ci
        if ($LASTEXITCODE -ne 0) { throw 'Node.js 依赖安装失败。' }
    } finally {
        Pop-Location
    }
}

$child = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $dashboardStart
) -Wait -PassThru -WindowStyle Hidden
if ($child.ExitCode -ne 0) {
    throw 'Node.js 实时工作台启动失败。请查看 Logs/sec-dashboard/ 下的日志。'
}
Write-Output "Node.js 实时工作台已启动：http://127.0.0.1:8090（Node.js $nodeVersion）"
