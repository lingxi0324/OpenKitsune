# ============================================================
# OpenKitsune · 启动脚本（纯 Windows，无 WSL 依赖）
# 前置：
#   1) 已运行 install.ps1，.venv 与 apps/setup-center/dist-web 就绪
#   2) 本地推理后端（model-manager 8240）在线
# 动作：
#   1) 校验 Python 环境、前端产物与推理后端
#   2) 以 .venv\Scripts\python.exe -m openkitsune serve 启动服务
#   3) 等待 /api/health 就绪后打开 Web 对话页
# 用法：
#   powershell -ExecutionPolicy Bypass -File start.ps1
#   powershell -ExecutionPolicy Bypass -File start.ps1 -Port 18900 -ShowLog
# ============================================================
param([int]$Port = 0, [switch]$ShowLog)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# 端口单一事实源：未显式传 -Port 时读取 .env 的 API_PORT
if ($Port -le 0) {
    $envPort = 0
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        $m = Select-String -Path $envFile -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -Last 1
        if ($m) { [void][int]::TryParse($m.Matches[0].Groups[1].Value, [ref]$envPort) }
    }
    $Port = if ($envPort -gt 0) { $envPort } else { 18900 }
}

$WebUrl = "http://127.0.0.1:$Port/web/"
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$ServePy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogRoot = Join-Path $ProjectRoot "data\logs"
if (-not (Test-Path $LogRoot)) { New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null }
$ServeLog = Join-Path $LogRoot "serve_win.log"
$ServeErr = Join-Path $LogRoot "serve_win.err"

Write-Host ""
Write-Host "  OpenKitsune · Windows 直启" -ForegroundColor Magenta
Write-Host "  ================================"

# ---------- 1. 检查推理后端（仅警告，不阻断） ----------
try {
    $h = Invoke-WebRequest "http://127.0.0.1:8240/health" -TimeoutSec 5 -UseBasicParsing
    if ($h.StatusCode -eq 200) {
        Write-Host "  [OK] 推理后端在线（8240）" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] 推理后端返回 $($h.StatusCode)，模型类功能可能不可用" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [WARN] 推理后端未运行（127.0.0.1:8240）" -ForegroundColor Yellow
    Write-Host "         可先运行 E:\models\Kitsune\scripts\start_services.ps1" -ForegroundColor DarkGray
}

# ---------- 2. 检查 Python 与前端 ----------
if (-not (Test-Path $ServePy)) {
    Write-Host "  [FAIL] 未找到 .venv，请先运行 install.ps1 安装依赖" -ForegroundColor Red
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}
if (-not (Test-Path "apps\setup-center\dist-web\index.html")) {
    Write-Host "  [FAIL] 前端未构建，请先运行 install.ps1（或 npm run build:web）" -ForegroundColor Red
    if ($ShowLog) { Read-Host "  按回车退出" }
    exit 1
}
Write-Host "  [OK] Python 与前端产物就绪" -ForegroundColor Green

# ---------- 3. 运行时依赖自检 ----------
$RequiredModules = @("fastapi", "uvicorn", "pydantic", "httpx", "keyring", "websockets")
$Missing = @()
foreach ($m in $RequiredModules) {
    & $ServePy -c "import $m" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { $Missing += $m }
}
if ($Missing.Count -gt 0) {
    Write-Host "  [..] 缺失运行时依赖: $($Missing -join ', ')，尝试自动安装..." -ForegroundColor Yellow
    $UvPath = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if ($UvPath) {
        & $UvPath pip install --python $ServePy @Missing 1>$null 2>$null
    }
    if ($LASTEXITCODE -ne 0) {
        & $ServePy -m pip install @Missing
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] 自动安装失败，请手动执行：" -ForegroundColor Red
        Write-Host "  uv pip install --python `"$ServePy`" $($Missing -join ' ')" -ForegroundColor Cyan
        if ($ShowLog) { Read-Host "  按回车退出" }
        exit 1
    }
    Write-Host "  [OK] 运行时依赖已补齐" -ForegroundColor Green
}

# ---------- 4. 端口占用检查 ----------
$already = $false
try {
    $c = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1
    if ($c) {
        $owner = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "  [OK] 端口 $Port 已有服务（$($owner.ProcessName)，PID $($c.OwningProcess)），直接打开浏览器" -ForegroundColor Green
        $already = $true
    }
} catch { }

# ---------- 5. 启动 Windows 原生服务 ----------
if (-not $already) {
    Write-Host "  [..] 启动 openkitsune serve（Windows，端口 $Port）..." -ForegroundColor Cyan
    if (Test-Path $ServeLog) { Remove-Item $ServeLog -Force -ErrorAction SilentlyContinue }
    if (Test-Path $ServeErr) { Remove-Item $ServeErr -Force -ErrorAction SilentlyContinue }

    Start-Process -FilePath $ServePy `
        -ArgumentList @("-m", "openkitsune", "serve") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $ServeLog `
        -RedirectStandardError $ServeErr `
        -WindowStyle Minimized | Out-Null

    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest $HealthUrl -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
        if (-not (Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $ServePy })) {
            # 进程提前退出：继续等待几秒，避免刚启动时的误判
            if ($i -gt 10) { break }
        }
    }
    if (-not $ready) {
        Write-Host "  [FAIL] 服务启动超时，请检查日志：" -ForegroundColor Red
        Write-Host "    $ServeLog" -ForegroundColor DarkGray
        Write-Host "    $ServeErr" -ForegroundColor DarkGray
        if (Test-Path $ServeErr) {
            Get-Content $ServeErr -Tail 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        }
        if ($ShowLog) { Read-Host "  按回车退出" }
        exit 1
    }
    Write-Host "  [OK] openkitsune 服务已就绪（Windows PID 见日志）" -ForegroundColor Green
}

# ---------- 6. 打开 Web 对话页 ----------
Start-Process $WebUrl
Write-Host ""
Write-Host "  对话入口：$WebUrl" -ForegroundColor Green
Write-Host "  服务日志：$ServeLog" -ForegroundColor DarkGray
Write-Host "  提示：首次访问如需密码，请看服务日志中的 OPENKITSUNE_WEB_PASSWORD。"
Write-Host ""

# ---------- 7. 可选：在当前窗口实时跟随日志 ----------
if ($ShowLog -and (Test-Path $ServeLog)) {
    Write-Host "  实时日志（Ctrl+C 退出，不会停止服务）..." -ForegroundColor DarkGray
    Get-Content $ServeLog -Tail 20 -Wait
}
