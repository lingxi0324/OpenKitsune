# ============================================================
# OpenKitsune · 启动脚本（Windows PowerShell）
# 前置：后端 llama-cpp-server（127.0.0.1:8240）在线；
#       已运行 install.ps1 完成依赖安装。
# 动作：启动 openkitsune serve（端口 18900）→ 打开 Web 前端对话
# 用法：powershell -ExecutionPolicy Bypass -File start.ps1
# ============================================================
param([int]$Port = 18900)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$WebUrl = "http://127.0.0.1:$Port/web/"
$ServePy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "  OpenKitsune · 启动前端对话" -ForegroundColor Magenta
Write-Host "  ================================"

# ---------- 1. 检查后端 llama-cpp-server ----------
try {
    $h = Invoke-RestMethod "http://127.0.0.1:8240/health" -TimeoutSec 5
    if ($h.status -ne "ok") { throw "status=$($h.status)" }
    Write-Host "  [OK] llama-cpp-server 在线（8240）" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] 后端未运行（127.0.0.1:8240）" -ForegroundColor Red
    Write-Host "  请先启动：F:\llama-cpp-server\scripts\start-server.bat"
    Read-Host "  按回车退出"; exit 1
}

# ---------- 2. 检查依赖 ----------
if (-not (Test-Path $ServePy)) {
    Write-Host "  [FAIL] 未找到 .venv，请先运行 install.ps1 安装依赖" -ForegroundColor Red
    Read-Host "  按回车退出"; exit 1
}
if (-not (Test-Path "apps\setup-center\dist-web\index.html")) {
    Write-Host "  [FAIL] 前端未构建，请先运行 install.ps1（或手动 npm run build:web）" -ForegroundColor Red
    Read-Host "  按回车退出"; exit 1
}
Write-Host "  [OK] 依赖与前端就绪" -ForegroundColor Green

# ---------- 2.5 运行时依赖自检（整改 2026-10-07） ----------
# 此前缺失 keyring / websockets 等运行时强依赖时服务静默降级或 500
# （账号接口 88 次、WebSocket 升级失败 81 次），且 venv 无 pip 无法自助补齐。
# 这里逐项探测，缺失时用 uv（若无 pip）或 pip 自动安装。
$RequiredModules = @("fastapi", "uvicorn", "pydantic", "httpx", "keyring", "websockets")
$Missing = @()
foreach ($m in $RequiredModules) {
    & $ServePy -c "import $m" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { $Missing += $m }
}
if ($Missing.Count -gt 0) {
    Write-Host "  [..] 缺失运行时依赖: $($Missing -join ', ')，尝试自动安装..." -ForegroundColor Yellow
    $Installer = $null
    $UvPath = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if ($UvPath) {
        & $UvPath pip install --python $ServePy @($Missing | ForEach-Object { $_ }) 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) { $Installer = "uv" }
    }
    if (-not $Installer) {
        & $ServePy -m pip install @($Missing | ForEach-Object { $_ }) 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) { $Installer = "pip" }
    }
    if (-not $Installer) {
        Write-Host "  [FAIL] 自动安装失败，请手动执行：" -ForegroundColor Red
        Write-Host "  uv pip install --python `"$ServePy`" $($Missing -join ' ')" -ForegroundColor Cyan
        Read-Host "  按回车退出"; exit 1
    }
    Write-Host "  [OK] 运行时依赖已补齐（$Installer）" -ForegroundColor Green
}

# ---------- 3. 端口占用检查 ----------
$already = $false
try {
    $c = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1
    if ($c) {
        Write-Host "  [OK] openkitsune 已在端口 $Port 运行，直接打开浏览器" -ForegroundColor Green
        $already = $true
    }
} catch { }

# ---------- 4. 启动服务 ----------
if (-not $already) {
    Write-Host "  [..] 启动 openkitsune serve（端口 $Port）..." -ForegroundColor Cyan
    # 端口由 .env 的 API_PORT 控制，serve 命令不接受 --port
    $cmd = "cd '$ProjectRoot'; .\.venv\Scripts\python.exe -m openkitsune serve"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-Command",$cmd) -WindowStyle Minimized
    Start-Sleep -Seconds 3

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            try {
                $r2 = Invoke-WebRequest $WebUrl -TimeoutSec 2 -UseBasicParsing
                if ($r2.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }
    }
    if (-not $ready) {
        Write-Host "  [FAIL] 服务启动超时，请检查最小化窗口中的日志" -ForegroundColor Red
        Read-Host "  按回车退出"; exit 1
    }
    Write-Host "  [OK] openkitsune 服务已就绪" -ForegroundColor Green
}

# ---------- 5. 打开浏览器 ----------
Start-Process $WebUrl
Write-Host ""
Write-Host "  对话入口：$WebUrl" -ForegroundColor Green
Write-Host "  提示：首次访问如需密码，请看服务日志（最小化窗口）中的 OPENKITSUNE_WEB_PASSWORD。"
Write-Host ""
