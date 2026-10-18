# ============================================================
# OpenKitsune · 启动脚本 v6（纯 WSL 直启）— 2026-10-18
# 设计：WSL 单栈。双击启动器 → 本脚本只做三件事：
#   1) 确保 WSL 内 openkitsune serve(18900) 就绪（未运行自动拉起，带重试探活）
#   2) 探测 WSL 内推理端点（仅警告，不阻断）
#   3) 打开 Web 前端
# 前置：WSL Ubuntu 可用；serve 侧代码位于
#       /mnt/e/agents/OpenKitsune-main（WSL 内，E:\agents\OpenKitsune-main）。
# 用法：powershell -ExecutionPolicy Bypass -File start.ps1 [-Port 18900] [-ShowLog]
#   -ShowLog：调试模式，实时 tail WSL serve 日志并输出完整诊断信息
# ============================================================
param([int]$Port = 0, [switch]$ShowLog)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# 端口单一事实源：未显式传 -Port 时读取 .env 的 API_PORT，避免启动脚本与实际服务端口脱节。
if ($Port -le 0) {
    $envPort = 0
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        $m = Select-String -Path $envFile -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -Last 1
        if ($m) { [void][int]::TryParse($m.Matches[0].Groups[1].Value, [ref]$envPort) }
    }
    $Port = if ($envPort -gt 0) { $envPort } else { 18900 }
}

$LogRoot = Join-Path $ProjectRoot "data\logs"
if (-not (Test-Path $LogRoot)) { New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null }
$TranscriptPath = Join-Path $LogRoot ("launcher_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

# ---------- 0. 单实例互斥（防止双击并发各拉一套） ----------
$mutex = New-Object System.Threading.Mutex($false, "OpenKitsuneStartV2")
if (-not $mutex.WaitOne(0)) {
    Write-Host "  已有 OpenKitsune 启动实例在运行，本实例直接退出。"
    exit 0
}
try { Start-Transcript -Path $TranscriptPath -Append | Out-Null } catch { }

# 候选访问地址：优先 127.0.0.1（WSL2 localhost 转发可用时），失败回退 WSL IP 直连。
# 2026-10-18 v6：serve 监听 0.0.0.0（API_HOST），WSL IP 路径保证转发中继缺失时仍可访问。
$WslIp = ((wsl -d Ubuntu -- bash -lc "hostname -I" 2>$null | Out-String).Trim() -split "\s+" | Select-Object -First 1)
$BaseUrls = @("http://127.0.0.1:$Port", "http://$WslIp`:$Port")

# ---------- 0.5 兜底修复 WSL localhost 转发缺失 ----------
# 本机实测 WSL2 的 127.0.0.1 转发中继缺失（Windows 侧连不上 0.0.0.0 监听端口）。
# 补一条 portproxy 让 127.0.0.1:$Port 可达；需管理员，失败不阻断（仍走 WSL IP）。
# 注意：WSL IP 变化后需重跑本脚本刷新代理。
function Ensure-LoopbackProxy {
    param([string]$TargetIp, [int]$PortNo)
    if (-not $TargetIp -or $PortNo -le 0) { return }
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            Write-Host "  [..] 非管理员，跳过 127.0.0.1 端口代理（改用 WSL IP 访问）" -ForegroundColor DarkGray
            return
        }
        netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=$PortNo 2>$null | Out-Null
        netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=$PortNo connectaddress=$TargetIp connectport=$PortNo | Out-Null
        Write-Host "  [OK] 127.0.0.1:$PortNo → ${TargetIp}:$PortNo 端口代理已就绪" -ForegroundColor DarkGray
    } catch { }
}
Ensure-LoopbackProxy -TargetIp $WslIp -PortNo $Port
$WebUrl = $null
$HealthUrl = $null
$WslCtl = "/mnt/e/agents/OpenKitsune-main/scripts/wsl_serve.sh"
$WslServeLog = "/mnt/e/agents/OpenKitsune-main/data/logs/serve_wsl.log"

Write-Host ""
Write-Host "  OpenKitsune · WSL 直启（v6）" -ForegroundColor Magenta
Write-Host "  启动日志: $TranscriptPath" -ForegroundColor DarkGray
Write-Host "  ================================"

# ---------- 工具函数 ----------
function Invoke-WslCtl {
    # 返回 stdout+stderr 合并文本；同时输出 wsl 退出码（非 0 即警告）
    # 第二参数端口透传给 wsl_serve.sh：脚本不再写死 18900，改 .env 后仍能对准端口
    param([string]$Action)
    $out = wsl -d Ubuntu -- bash $WslCtl $Action $Port 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Host "  [WARN] wsl $Action 退出码 $code：" -ForegroundColor Yellow
        ($out -split "`r?`n" | Where-Object { $_.Trim() }) | ForEach-Object {
            Write-Host "        $_" -ForegroundColor DarkGray
        }
    }
    return $out.Trim()
}
function Show-WslServeLogTail {
    param([int]$Lines = 25)
    $tailOut = wsl -d Ubuntu -- bash -lc "tail -n $Lines '$WslServeLog'" 2>$null | Out-String
    # serve_wsl.log 现在含 ANSI 彩色码，诊断输出时剥离，避免控制台显示裸转义序列
    $tailOut = $tailOut -replace "`e\[[0-9;]*m", ""
    if ($tailOut.Trim()) {
        ($tailOut -split "`r?`n" | Where-Object { $_.Trim() }) | ForEach-Object {
            Write-Host "        $_" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "        （WSL serve 日志不存在或无内容）" -ForegroundColor DarkGray
    }
}
function Test-ServeHttp {
    # 依次探测候选地址（127.0.0.1 localhost 转发 → WSL IP 直连），命中即记录可达地址
    foreach ($base in $BaseUrls) {
        try {
            $r = Invoke-WebRequest "$base/api/health" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $script:HealthUrl = "$base/api/health"
                $script:WebUrl = "$base/web/"
                return $true
            }
        } catch { }
        try {
            $r2 = Invoke-WebRequest "$base/web/" -TimeoutSec 3 -UseBasicParsing
            if ($r2.StatusCode -eq 200) {
                $script:HealthUrl = "$base/api/health"
                $script:WebUrl = "$base/web/"
                return $true
            }
        } catch { }
    }
    return $false
}

function Watch-ServeLog {
    # 在当前控制台持续跟踪 WSL serve 日志（Ctrl+C 退出）。
    # 输出留在启动窗口内，窗口不会在启动完成后立刻关闭；sed -u 剥离 ANSI 转义码。
    $logDir = $WslServeLog -replace '/[^/]+$', ''
    Write-Host "  [DEBUG] 实时跟踪 WSL serve 日志（Ctrl+C 退出）：$WslServeLog" -ForegroundColor DarkGray
    wsl -d Ubuntu -- bash -lc "mkdir -p '$logDir'; touch '$WslServeLog'; tail -n 40 -F '$WslServeLog' | sed -u 's/\x1b\[[0-9;]*m//g'"
}

# ---------- 1. 确保 WSL serve 运行 ----------
# 关键背景：WSL2 localhost 转发中继在 serve 于 Windows 端口空闲时绑定；
# 若中继缺失导致 127.0.0.1 不可达，重试时 stop→start 重启 serve 以重建中继。
# v5: 预算 120s/60s/60s 共 3 轮；每 15s 打进度；失败时透传 WSL serve 日志尾部。
function Ensure-WslServeUp {
    # 快速路径：127.0.0.1 已可访问（localhost 转发下即 WSL serve）
    if (Test-ServeHttp) {
        Write-Host "  [OK] WSL 实例已就绪（端口 $Port）" -ForegroundColor Green
        return $true
    }
    $attempt = 0
    while ($attempt -lt 3) {
        $attempt++
        if ($attempt -gt 1) {
            Write-Host "  [..] 重试（第 $attempt 次）：重启 WSL serve 以重建转发中继..." -ForegroundColor Yellow
            $null = Invoke-WslCtl stop
            Start-Sleep -Seconds 3
        } else {
            Write-Host "  [..] 启动 WSL serve（WSL 未运行时自动拉起，boot 亦会自动启动）..." -ForegroundColor Cyan
        }
        $r = Invoke-WslCtl start
        if ($r -match 'START_FAILED') {
            Write-Host "  [WARN] wsl_serve.sh start 报 START_FAILED，WSL serve 日志尾部：" -ForegroundColor Yellow
            Show-WslServeLogTail -Lines 20
        }
        $budget = if ($attempt -eq 1) { 120 } else { 60 }
        $t = 0
        while ($t -lt $budget) {
            Start-Sleep -Seconds 1; $t++
            if (Test-ServeHttp) {
                Write-Host "  [OK] WSL 实例已就绪（端口 $Port，等待 ${t}s）" -ForegroundColor Green
                return $true
            }
            if ($t % 15 -eq 0) {
                $st = Invoke-WslCtl status
                Write-Host "  [..] 等待 WSL 实例就绪（${t}s / ${budget}s, WSL内: $st）..." -ForegroundColor Cyan
            }
        }
        $st = Invoke-WslCtl status
        Write-Host "  [WARN] 第 $attempt 次探活超时（WSL 内 18900: $st）" -ForegroundColor Yellow
        if ($attempt -ge 3) {
            Write-Host "  [..] 最终诊断 · WSL serve 日志尾部：" -ForegroundColor Yellow
            Show-WslServeLogTail -Lines $(if ($ShowLog) { 100 } else { 30 })
        }
    }
    Write-Host "  [FAIL] WSL 实例启动超时（3 次尝试）；" -ForegroundColor Red
    return $false
}

# ---------- 2. 主流程 ----------
if ($ShowLog) {
    Write-Host "  [DEBUG] 端口: $Port" -ForegroundColor DarkGray
    Write-Host "  [DEBUG] 候选地址: $($BaseUrls -join ' , ')" -ForegroundColor DarkGray
    Write-Host "  [DEBUG] WSL serve 日志: $WslServeLog" -ForegroundColor DarkGray
    Write-Host "  [DEBUG] 启动器日志(Transcript): $TranscriptPath" -ForegroundColor DarkGray
}
try {
    if (-not (Ensure-WslServeUp)) {
        Write-Host ""
        Write-Host "  [FAIL] WSL 实例启动失败。请按以下路径排查：" -ForegroundColor Red
        Write-Host "    WSL 服务日志: wsl -d Ubuntu -- tail -n 50 $WslServeLog" -ForegroundColor Cyan
        Write-Host "    本次启动日志: $TranscriptPath" -ForegroundColor Cyan
        Write-Host "    手工启动试跑: powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`""
        Write-Host ""
        try { Read-Host "  按回车退出（或直接关闭窗口）" } catch { }
        exit 1
    }

    # ---------- 3. 探测 WSL 内推理端点（仅警告，不阻断） ----------
    # [2026-10-18] 对齐 WSL 全栈：8240 网关（qwen36 主模型）在线即 OK；8200(qwen38 按需) 次之。
    $model = Invoke-WslCtl model
    if ($model -match 'OK') {
        Write-Host "  [OK] 推理端点在线（8240 网关 / 8220 主模型 / 8200 按需）" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] 推理端点未就绪（8240/8220/8200 均不可达）——界面/记忆可用，对话需等模型拉起" -ForegroundColor Yellow
    }

    # ---------- 4. 打开浏览器 ----------
    Start-Sleep -Seconds 1
    if (-not $WebUrl) { $WebUrl = "http://127.0.0.1:$Port/web/" }
    Start-Process $WebUrl
    Write-Host ""
    Write-Host "  对话入口：$WebUrl" -ForegroundColor Green
    Write-Host "  提示：首次访问如需密码，请看 WSL 服务日志中的 OPENKITSUNE_WEB_PASSWORD。"
    Write-Host "        WSL 服务日志：wsl -d Ubuntu -- tail -f $WslServeLog"
    Write-Host "        本次启动日志：$TranscriptPath"
    Write-Host ""

    # ---------- 5. 显示日志并保持窗口（调试模式）：先回显尾部，再实时跟踪 ----------
    if ($ShowLog) {
        Write-Host ""
        Write-Host "  [DEBUG] WSL serve 日志尾部：" -ForegroundColor DarkGray
        Show-WslServeLogTail -Lines 60
        Write-Host ""
        Watch-ServeLog
        try { Read-Host "  日志跟踪已结束，按回车关闭启动窗口" } catch { }
    }
} finally {
    try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch { }
    try { $mutex.ReleaseMutex() } catch { }
    try { $mutex.Dispose() } catch { }
}
