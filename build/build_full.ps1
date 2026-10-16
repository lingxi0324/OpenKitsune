# OpenKitsune desktop package with optional modules (Windows PowerShell)

param([switch]$Fast)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SetupCenterDir = Join-Path $ProjectRoot "apps\setup-center"
$ResourceDir = Join-Path $SetupCenterDir "src-tauri\resources"

Write-Host "[1/4] Building web frontend..." -ForegroundColor Yellow
Push-Location $SetupCenterDir
try {
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build:web
    if ($LASTEXITCODE -ne 0) { throw "Web frontend build failed" }
} finally { Pop-Location }

Write-Host "[2/4] Preparing managed Python runtime..." -ForegroundColor Yellow
uv run --no-sync python "$ScriptDir\prepare_bootstrap_resources.py" --commit-resources --target-platform win-x64 --require-python-seed
if ($LASTEXITCODE -ne 0) { throw "Bootstrap resource preparation failed" }

Write-Host "[3/4] Pre-bundling optional modules..." -ForegroundColor Yellow
uv run --no-sync python "$ScriptDir\bundle_modules.py"
if ($LASTEXITCODE -ne 0) { throw "Module pre-bundling failed" }
$ModulesDir = Join-Path $ScriptDir "modules"
$TargetModulesDir = Join-Path $ResourceDir "modules"
if (Test-Path $TargetModulesDir) { Remove-Item -Recurse -Force $TargetModulesDir }
if (Test-Path $ModulesDir) { Copy-Item -Recurse $ModulesDir $TargetModulesDir }

Write-Host "[4/4] Building Tauri app..." -ForegroundColor Yellow
Push-Location $SetupCenterDir
try {
    npx tauri build --bundles nsis --config src-tauri/tauri.local-full-build.conf.json
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
} finally {
    Pop-Location
}

Write-Host "Full desktop package build completed." -ForegroundColor Green
