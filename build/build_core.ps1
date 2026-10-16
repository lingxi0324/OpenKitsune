# OpenKitsune desktop package build script (Windows PowerShell)
# Usage: .\build_core.ps1

param([switch]$Fast)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SetupCenterDir = Join-Path $ProjectRoot "apps\setup-center"

Write-Host "[1/3] Building web frontend..." -ForegroundColor Yellow
Push-Location $SetupCenterDir
try {
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build:web
    if ($LASTEXITCODE -ne 0) { throw "Web frontend build failed" }
} finally { Pop-Location }

Write-Host "[2/3] Preparing managed Python runtime..." -ForegroundColor Yellow
uv run --no-sync python "$ScriptDir\prepare_bootstrap_resources.py" --commit-resources --target-platform win-x64 --require-python-seed --require-real-assets
if ($LASTEXITCODE -ne 0) { throw "Bootstrap resource preparation failed" }

Write-Host "[3/3] Building Tauri app..." -ForegroundColor Yellow
Push-Location $SetupCenterDir
try {
    npx tauri build --bundles nsis --config src-tauri/tauri.local-build.conf.json
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
} finally {
    Pop-Location
}

Write-Host "Desktop package build completed." -ForegroundColor Green
