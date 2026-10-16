param(
    [switch]$SkipWheelBuild,
    [string]$UvUrl = $env:OPENKITSUNE_UV_URL
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArgsList = @()

if ($SkipWheelBuild) {
    $ArgsList += "--skip-wheel-build"
}

if ($UvUrl) {
    $ArgsList += "--uv-url"
    $ArgsList += $UvUrl
}

python (Join-Path $ScriptDir "prepare_bootstrap_resources.py") @ArgsList
