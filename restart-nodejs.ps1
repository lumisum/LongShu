[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
& (Join-Path $root 'stop-nodejs.ps1')
& (Join-Path $root 'start-nodejs.ps1')
