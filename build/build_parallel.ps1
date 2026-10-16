# ==========================================================
#  OpenKitsune Parallel Build Script (PowerShell)
#  将前端、Rust 和 managed Python runtime 构建并行执行
#
#  Usage:
#    powershell -File build/build_parallel.ps1          # core mode
#    powershell -File build/build_parallel.ps1 -Mode full
#
# ==========================================================

param(
    [ValidateSet("core", "full")]
    [string]$Mode = "core",
    [switch]$Fast,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = "Stop"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SetupCenter = Join-Path $ProjectRoot "apps\setup-center"
$SrcTauri    = Join-Path $SetupCenter "src-tauri"
$ResourceDir = Join-Path $SrcTauri "resources"

$modeLabel = if ($Fast) { "$Mode, FAST" } else { $Mode }
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  OpenKitsune Parallel Build (mode: $modeLabel)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# ── Resolve tools ─────────────────────────────────────────
Write-Host ""
Write-Host "[Setup] Resolving build tools..." -ForegroundColor Yellow

# Resolve full native paths for tools so Start-Job can find them.
# On Windows, npm/cargo are .cmd batch files; Get-Command may return extensionless bash scripts
# that don't work in PowerShell jobs. Prefer .cmd/.exe variants explicitly.
function Resolve-NativeCmd($name) {
    # Try .cmd first (Windows batch wrapper), then .exe, then fallback to Get-Command
    foreach ($ext in @(".cmd", ".exe", "")) {
        $candidate = Get-Command "$name$ext" -ErrorAction SilentlyContinue
        if ($candidate) { return $candidate.Source }
    }
    return $null
}

$npmCmd    = Resolve-NativeCmd "npm"
$cargoCmd  = Resolve-NativeCmd "cargo"
$uvCmd     = Resolve-NativeCmd "uv"

Write-Host "  Resolved: uv=$uvCmd"
Write-Host "  Resolved: npm=$npmCmd"
Write-Host "  Resolved: cargo=$cargoCmd"

if (-not $npmCmd)    { Write-Host "  [WARN] npm not found in PATH" -ForegroundColor Yellow }
if (-not $cargoCmd)  { Write-Host "  [WARN] cargo not found in PATH" -ForegroundColor Yellow }
if (-not $uvCmd)     { Write-Host "  [WARN] uv not found in PATH" -ForegroundColor Yellow }

# ── Phase 1: Build shared web frontend ────────────────────
# dist-web is embedded in the wheel used to create bootstrap/app-venv.
Write-Host ""
Write-Host "[Phase 1/4] Building web frontend (dist-web)..." -ForegroundColor Yellow
Push-Location $SetupCenter
try {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $npmCmd run build:web 2>&1
    $webExit = $LASTEXITCODE
    $ErrorActionPreference = $oldEap
    if ($webExit -ne 0) { throw "Web frontend build failed (exit $webExit)" }
} finally {
    if ($oldEap) { $ErrorActionPreference = $oldEap }
    Pop-Location
}
Write-Host "  ✓ Web frontend built" -ForegroundColor Green
$phase0Time = [math]::Round($sw.Elapsed.TotalSeconds)

# ── Phase 2: Four parallel jobs ───────────────────────────
Write-Host ""
if ($SkipBootstrap) {
    Write-Host "[Phase 2/4] Starting 2 parallel build tasks..." -ForegroundColor Yellow
} else {
    Write-Host "[Phase 2/4] Starting 3 parallel build tasks..." -ForegroundColor Yellow
}

# Job A: Frontend build
$jobFe = Start-Job -Name "Frontend" -ScriptBlock {
    param($dir, $npm)
    Set-Location $dir
    $env:VITE_PREVIEW_BUILD = "true"
    $ErrorActionPreference = "Continue"
    & $npm run build 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed (exit $LASTEXITCODE)" }
} -ArgumentList $SetupCenter, $npmCmd
Write-Host "  -> [A] Frontend build (Vite)          (Job: $($jobFe.Id))"

# Job B: Rust pre-compile
$jobRs = Start-Job -Name "RustCompile" -ScriptBlock {
    param($dir, $cargo)
    Set-Location $dir
    $ErrorActionPreference = "Continue"
    & $cargo build --release --features tauri/custom-protocol 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Rust compile failed (exit $LASTEXITCODE)" }
} -ArgumentList $SrcTauri, $cargoCmd
Write-Host "  -> [B] Rust release compile           (Job: $($jobRs.Id))"

# Job C: Bootstrap resources for dual-venv runtime
if (-not $SkipBootstrap) {
    $jobBootstrap = Start-Job -Name "Bootstrap" -ScriptBlock {
        param($root, $scriptDir, $uv)
        Set-Location $root
        $ErrorActionPreference = "Continue"
        & $uv run --no-sync python "$scriptDir\prepare_bootstrap_resources.py" --commit-resources --target-platform win-x64 --require-python-seed 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Bootstrap resources failed (exit $LASTEXITCODE)" }
    } -ArgumentList $ProjectRoot, $ScriptDir, $uvCmd
    Write-Host "  -> [C] Bootstrap resources            (Job: $($jobBootstrap.Id))"
}

Write-Host ""
Write-Host "  Waiting for all tasks to complete..."

# Wait for all jobs
$allJobs = @($jobFe, $jobRs)
if (-not $SkipBootstrap) { $allJobs += $jobBootstrap }
$failed = $false

# Poll with progress
while ($allJobs | Where-Object { $_.State -eq 'Running' }) {
    Start-Sleep -Seconds 3
    foreach ($job in $allJobs) {
        if ($job.State -eq 'Completed' -and -not $job.HasMoreData) { continue }
        if ($job.State -ne 'Running') {
            # Print completion status once
        }
    }
    $running = ($allJobs | Where-Object { $_.State -eq 'Running' }).Count
    $elapsed = [math]::Round($sw.Elapsed.TotalSeconds)
    Write-Host "`r  [${elapsed}s] $running task(s) still running..." -NoNewline
}
Write-Host ""

# Check results
foreach ($job in $allJobs) {
    $result = Receive-Job $job -ErrorAction SilentlyContinue
    if ($job.State -eq 'Completed') {
        Write-Host "  ✓ $($job.Name) done" -ForegroundColor Green
    } elseif ($job.State -eq 'Failed') {
        if ($job.Name -eq 'RustCompile') {
            Write-Host "  ⚠ $($job.Name) failed (Tauri will retry)" -ForegroundColor Yellow
        } else {
            Write-Host "  ✗ $($job.Name) FAILED" -ForegroundColor Red
            Write-Host "    Output:" -ForegroundColor Red
            $result | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" }
            $failed = $true
        }
    }
}
Remove-Job $allJobs -Force

$phase1Time = [math]::Round($sw.Elapsed.TotalSeconds)
$parallelTime = [math]::Round($sw.Elapsed.TotalSeconds - $phase0Time)
Write-Host ""
Write-Host "  Phase 2 completed in ${parallelTime}s" -ForegroundColor Cyan

if ($failed) {
    Write-Host "ERROR: Critical task failed. Aborting." -ForegroundColor Red
    exit 1
}

# ── Phase 3: Copy optional module resources ──────────────
Write-Host ""
Write-Host "[Phase 3/4] Preparing optional module resources..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $ResourceDir | Out-Null

if ($Mode -eq "full") {
    $modulesDir = Join-Path $ProjectRoot "build\modules"
    if (Test-Path $modulesDir) {
        $targetModules = Join-Path $ResourceDir "modules"
        if (Test-Path $targetModules) { Remove-Item -Recurse -Force $targetModules }
        Copy-Item -Recurse $modulesDir $targetModules
    }
}
Write-Host "  Optional resources ready" -ForegroundColor Green

# ── Phase 3: Tauri NSIS bundling ──────────────────────────
Write-Host ""
Write-Host "[Phase 4/4] Creating NSIS installer..." -ForegroundColor Yellow

Push-Location $SetupCenter
try {
    $env:CI = $null
    # Skip frontend build (already done), Rust binary is cached
    npx tauri build --bundles nsis --config src-tauri/tauri.local-parallel-build.conf.json
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
} finally {
    Pop-Location
}

$totalTime = [math]::Round($sw.Elapsed.TotalSeconds)

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  Build completed in ${totalTime}s" -ForegroundColor Green
Write-Host "  Phase 1 (web): ${phase0Time}s" -ForegroundColor Green
Write-Host "  Phase 2 (parallel): ${parallelTime}s" -ForegroundColor Green
Write-Host "  Phase 3+4 (sequential): $($totalTime - $phase1Time)s" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green

# Rename latest installer with timestamp + git hash
$nsisDir = Join-Path $SrcTauri "target\release\bundle\nsis"
if (Test-Path $nsisDir) {
    $latest = Get-ChildItem "$nsisDir\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmm"
        $gitHash = ""
        try {
            $gitHash = (git -C $ProjectRoot rev-parse --short=7 HEAD 2>$null)
            if (-not $gitHash) { $gitHash = "unknown" }
        } catch { $gitHash = "unknown" }
        $baseName = $latest.BaseName   # e.g. "OpenKitsune Desktop_1.22.5_x64-setup"
        $tag      = "$([char]0x9884)$([char]0x89C8)$([char]0x7248)"  # 预览版
        $newName  = "${baseName}_${timestamp}_${gitHash}_${tag}.exe"
        $newPath  = Join-Path $nsisDir $newName
        Copy-Item $latest.FullName $newPath
        Write-Host ""
        Write-Host "  Installer:" -ForegroundColor Cyan
        Write-Host "    $newName ($([math]::Round((Get-Item $newPath).Length / 1MB))MB)" -ForegroundColor White
        Write-Host "    Git: $gitHash" -ForegroundColor Gray
        Write-Host "    Path: $newPath" -ForegroundColor Gray
    }
}

# Also list recent installers
Write-Host ""
Write-Host "  Recent builds:" -ForegroundColor Cyan
Get-ChildItem "$nsisDir\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
    Write-Host "    $($_.Name) ($([math]::Round($_.Length / 1MB))MB)"
}
