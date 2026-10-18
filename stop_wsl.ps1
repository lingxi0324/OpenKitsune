# ============================================================
# OpenKitsune · 停止 WSL 服务
# 用法：powershell -ExecutionPolicy Bypass -File stop_wsl.ps1
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

$WslCtl = "/mnt/e/agents/OpenKitsune-main/scripts/wsl_serve.sh"

Write-Host ""
Write-Host "  OpenKitsune · 停止 WSL 服务" -ForegroundColor Magenta
Write-Host "  ================================"

$out = wsl -d Ubuntu -- bash $WslCtl stop $Port 2>&1 | Out-String
Write-Host ("  " + $out.Trim()) -ForegroundColor Green

# 清理 start_wsl.ps1 建立的 127.0.0.1 端口代理，避免切回 Windows 版时端口被 svchost 占用
netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$Port 2>$null | Out-Null
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-Host "  [WARN] 端口 $Port 仍被 PID $($listener.OwningProcess) 占用" -ForegroundColor Yellow
} else {
    Write-Host "  [OK] 端口 $Port 已释放" -ForegroundColor Green
}
