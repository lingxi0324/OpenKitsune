# ============================================================
# OpenKitsune · 启动脚本（WSL 版）
# 与 start.ps1（Windows 原生）并列，供 OpenKitsunewslLauncher.exe 调用
# 使用最新代码：/mnt/e/agents/OpenKitsune-main（与 Windows 同一仓库）
# 用法：
#   powershell -ExecutionPolicy Bypass -File start_wsl.ps1
#   powershell -ExecutionPolicy Bypass -File start_wsl.ps1 -Port 18900 -ShowLog
# ============================================================
param([int]$Port = 0, [switch]$ShowLog)

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

$WslDir = "/mnt/e/agents/OpenKitsune-main"
$WslCtl = "$WslDir/scripts/wsl_serve.sh"
$WslLog = "$WslDir/data/logs/serve_wsl.log"

Write-Host ""
Write-Host "  OpenKitsune · WSL 直启" -ForegroundColor Magenta
Write-Host "  ================================"

# ---------- 1. WSL 可用性 ----------
wsl -d Ubuntu -- true 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] WSL Ubuntu 不可用，请确认已安装并启动 WSL" -ForegroundColor Red
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}
Write-Host "  [OK] WSL Ubuntu 可用" -ForegroundColor Green

# ---------- 2. 端口冲突检查 ----------
# WSL 进程不会出现在 Windows 的 Win32_Process 列表里；能匹配到的一定是 Windows 原生版
$winServe = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'openkitsune\s+serve' } |
    Select-Object -First 1
if ($winServe) {
    Write-Host "  [FAIL] Windows 原生版正在运行（PID $($winServe.ProcessId)）" -ForegroundColor Red
    Write-Host "         请先结束该 Windows 服务，再启动 WSL 版" -ForegroundColor DarkGray
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $procName = if ($proc) { [string]$proc.Name } else { "" }
    if ($procName -notin @("wslrelay.exe", "svchost.exe")) {
        Write-Host "  [FAIL] 端口 $Port 被其他进程占用：$procName PID $($listener.OwningProcess)" -ForegroundColor Red
        if ($ShowLog) { Read-Host "  按回车退出" }
        exit 1
    }
}

# ---------- 3. 启动 WSL serve ----------
Write-Host "  [..] 启动 WSL openkitsune serve（端口 $Port）..." -ForegroundColor Cyan
$startOut = wsl -d Ubuntu -- bash $WslCtl start $Port 2>&1 | Out-String
$startCode = $LASTEXITCODE
Write-Host ("        " + ($startOut.Trim() -replace "`r?`n", " / ")) -ForegroundColor DarkGray
if ($startOut -match 'START_FAILED') {
    Write-Host "  [FAIL] WSL serve 启动失败，最近日志：" -ForegroundColor Red
    wsl -d Ubuntu -- tail -n 30 $WslLog 2>$null | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}

# ---------- 4. 确保 Windows 侧 127.0.0.1 可达 ----------
$wslIp = ((wsl -d Ubuntu -- hostname -I 2>$null | Out-String).Trim() -split "\s+" | Select-Object -First 1)
if ($wslIp) {
    try {
        netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$Port 2>$null | Out-Null
        netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$Port connectaddress=$wslIp connectport=$Port 2>$null | Out-Null
    } catch { }
}

# ---------- 5. 等待健康检查 ----------
$webUrl = "http://127.0.0.1:$Port/web/"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    foreach ($base in @("http://127.0.0.1:$Port", "http://${wslIp}:$Port")) {
        if (-not $base) { continue }
        try {
            $r = Invoke-WebRequest "$base/api/health" -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $healthUrl = "$base/api/health"
                $webUrl = "$base/web/"
                $ready = $true
                break
            }
        } catch { }
    }
    if ($ready) { break }
}
if (-not $ready) {
    Write-Host "  [FAIL] WSL 服务启动超时，最近日志：" -ForegroundColor Red
    wsl -d Ubuntu -- tail -n 30 $WslLog 2>$null | ForEach-Object { Write-Host "        $_" -ForegroundColor DarkGray }
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}
Write-Host "  [OK] WSL 服务已就绪：$webUrl" -ForegroundColor Green

# ---------- 6. 打开浏览器 ----------
Start-Process $webUrl
Write-Host ""
Write-Host "  对话入口：$webUrl" -ForegroundColor Green
Write-Host "  服务日志：wsl -d Ubuntu -- tail -f $WslLog" -ForegroundColor DarkGray
Write-Host ""

# ---------- 7. 可选：实时日志 ----------
if ($ShowLog) {
    Write-Host "  实时 WSL 日志（Ctrl+C 退出，不会停止服务）..." -ForegroundColor DarkGray
    wsl -d Ubuntu -- tail -f $WslLog
}
