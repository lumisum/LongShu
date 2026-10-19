[CmdletBinding()]
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
$docker = Get-Command docker -ErrorAction Stop
$stacks = @(
    [pscustomobject]@{
        Name = 'MinerU GPU, PostgreSQL, Redis'
        Directory = Join-Path $root 'Docker\mineru-stack'
        Compose = Join-Path $root 'Docker\mineru-stack\compose.yaml'
        EnvFile = Join-Path $root 'Docker\mineru-stack\.env'
    },
    [pscustomobject]@{
        Name = 'Nagarjuna PostgreSQL with pgvector'
        Directory = Join-Path $root 'Docker\nagarjuna-pgvector'
        Compose = Join-Path $root 'Docker\nagarjuna-pgvector\compose.yaml'
        EnvFile = Join-Path $root 'Docker\nagarjuna-pgvector\.env'
    }
)
foreach ($stack in $stacks) {
    if (-not (Test-Path -LiteralPath $stack.Compose)) {
        throw "找不到 Compose 文件：$($stack.Compose)"
    }
    if (-not (Test-Path -LiteralPath $stack.EnvFile)) {
        throw "缺少本机配置：$($stack.EnvFile)。请从同目录的 .env.example 复制并填写密码。"
    }
}

$engine = (& $docker.Source info --format '{{.ServerVersion}}' 2>$null | Out-String).Trim()
$engineReady = ($LASTEXITCODE -eq 0 -and $engine)
if (-not $engineReady) {
    $desktopRunning = [bool](Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)
    if (-not $desktopRunning) {
    $desktopExe = $env:DOCKER_DESKTOP_EXE
    if (-not $desktopExe -or -not (Test-Path -LiteralPath $desktopExe)) {
        $programFiles = [Environment]::GetFolderPath('ProgramFiles')
        $candidate = Join-Path $programFiles 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path -LiteralPath $candidate) { $desktopExe = $candidate }
    }
    if (-not $desktopExe -or -not (Test-Path -LiteralPath $desktopExe)) {
        $uninstallKeys = @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        foreach ($key in $uninstallKeys) {
            $installedApps = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
            $dockerApp = $installedApps | Where-Object { $_.DisplayName -like 'Docker Desktop*' } | Select-Object -First 1
            if ($dockerApp.InstallLocation) {
                $candidate = Join-Path $dockerApp.InstallLocation 'Docker Desktop.exe'
                if (Test-Path -LiteralPath $candidate) { $desktopExe = $candidate; break }
            }
            if ($dockerApp.DisplayIcon) {
                $candidate = ($dockerApp.DisplayIcon -replace ',\d+$', '') -replace '^"|"$', ''
                if (Test-Path -LiteralPath $candidate) { $desktopExe = $candidate; break }
            }
        }
    }
    if (-not $desktopExe -or -not (Test-Path -LiteralPath $desktopExe)) {
        throw 'Docker Engine 未启动，且未能定位 Docker Desktop。设置 DOCKER_DESKTOP_EXE 指向 Docker Desktop.exe 后重试。'
    }
    Start-Process -FilePath $desktopExe -WindowStyle Hidden
    }
    Write-Output '正在等待 Docker Desktop 启动...'
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        $engine = (& $docker.Source info --format '{{.ServerVersion}}' 2>$null | Out-String).Trim()
        $engineReady = ($LASTEXITCODE -eq 0 -and $engine)
        if ((Get-Date) -ge $deadline -and -not $engineReady) {
            throw 'Docker Engine 在 3 分钟内未就绪。请检查 Docker Desktop。'
        }
    } while (-not $engineReady)
}

$managedContainers = @(
    'mineru-api',
    'mineru-webui',
    'mineru-postgres',
    'mineru-redis',
    'nagarjuna-postgres'
)
foreach ($containerName in $managedContainers) {
    $containerId = (& $docker.Source ps -aq --filter "name=^/$containerName$" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "无法检查容器：$containerName" }
    if ($containerId) {
        & $docker.Source update --restart=no $containerId | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "无法关闭容器自动重启：$containerName" }
    }
}

foreach ($stack in $stacks) {
    Write-Output "正在启动：$($stack.Name)"
    Push-Location $stack.Directory
    try {
        $composeArgs = @('compose', '--env-file', $stack.EnvFile, '-f', $stack.Compose, 'up', '-d')
        if ($Rebuild) { $composeArgs += '--build' }
        & $docker.Source @composeArgs
        if ($LASTEXITCODE -ne 0) { throw "服务栈启动失败：$($stack.Name)" }
    } finally {
        Pop-Location
    }
}

Write-Output '基础服务启动命令已完成。MinerU Compose 配置申请使用 GPU 0。'
Write-Output '实时工作台请单独运行 start-nodejs.ps1。'
