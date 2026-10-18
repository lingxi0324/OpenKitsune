# ============================================================
# OpenKitsune · 停止 Windows 原生服务
# 用法：powershell -ExecutionPolicy Bypass -File stop_win.ps1
# ============================================================
param([int]$Port = 0)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if ($Port -le 0) {
    $envPort = 0
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        $m = Select-String -Path $envFile -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -Last 1
        if ($m) { [void][int]::TryParse($m.Matches[0].Groups[1].Value, [ref]$envPort) }
    }
    $Port = if ($envPort -gt 0) { $envPort } else { 18900 }
}

Write-Host ""
Write-Host "  OpenKitsune · 停止 Windows 服务" -ForegroundColor Magenta
Write-Host "  ================================"

$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'openkitsune\s+serve' })
if ($procs.Count -eq 0) {
    Write-Host "  [OK] 没有正在运行的 Windows 服务" -ForegroundColor Green
    exit 0
}

foreach ($p in $procs) {
    Write-Host "  [..] 结束 PID $($p.ProcessId) ..." -ForegroundColor Cyan
    taskkill /PID $p.ProcessId /T /F 2>$null | Out-Null
}

Start-Sleep -Seconds 2
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -match 'openkitsune\s+serve') {
        Write-Host "  [FAIL] 端口 $Port 仍被 Windows 服务占用" -ForegroundColor Red
        exit 1
    }
}
Write-Host "  [OK] Windows 服务已停止，端口 $Port 已释放" -ForegroundColor Green
