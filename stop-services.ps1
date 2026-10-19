[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
$docker = Get-Command docker -ErrorAction Stop
$engine = (& $docker.Source info --format '{{.ServerVersion}}' 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $engine) {
    Write-Output 'Docker Engine 当前未运行；停止脚本不会启动 Docker Desktop。'
    exit 0
}

$stacks = @(
    [pscustomobject]@{
        Name = 'Nagarjuna PostgreSQL with pgvector'
        Directory = Join-Path $root 'Docker\nagarjuna-pgvector'
        Compose = Join-Path $root 'Docker\nagarjuna-pgvector\compose.yaml'
        EnvFile = Join-Path $root 'Docker\nagarjuna-pgvector\.env'
    },
    [pscustomobject]@{
        Name = 'MinerU GPU, PostgreSQL, Redis'
        Directory = Join-Path $root 'Docker\mineru-stack'
        Compose = Join-Path $root 'Docker\mineru-stack\compose.yaml'
        EnvFile = Join-Path $root 'Docker\mineru-stack\.env'
    }
)

foreach ($stack in $stacks) {
    if (-not (Test-Path -LiteralPath $stack.Compose)) {
        throw "找不到 Compose 文件：$($stack.Compose)"
    }
    if (-not (Test-Path -LiteralPath $stack.EnvFile)) {
        throw "缺少本机配置：$($stack.EnvFile)。停止服务前请恢复对应 .env 文件。"
    }

    Write-Output "正在停止：$($stack.Name)"
    Push-Location $stack.Directory
    try {
        & $docker.Source compose --env-file $stack.EnvFile -f $stack.Compose stop
        if ($LASTEXITCODE -ne 0) { throw "服务栈停止失败：$($stack.Name)" }
    } finally {
        Pop-Location
    }
}

Write-Output '基础容器已停止，数据库卷与本机数据已保留。Docker Desktop 本身仍保持运行。'
