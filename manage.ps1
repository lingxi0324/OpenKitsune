# ============================================================
# OpenKitsune · 纯 PowerShell 管理脚本（替代 OpenKitsunewinLauncher.exe）
# ============================================================
# 职责：一键启动 / 停止 / 状态 / 重启 / 日志跟随 / 崩溃守护
#   - start   : 端口自检（已在运行则只开浏览器）→ 委派 start.ps1 启动 serve
#               （隐藏进程 + 90s 健康门控 + 自动开浏览器）
#   - start -Watchdog : 启动后驻留守护，health 探活，serve 崩溃自动重启
#   - stop    : 委派 stop_win.ps1 按「命令行匹配 openkitsune serve」结束进程树
#   - status  : 端口 / 健康 / PID / 运行时长
#   - restart : stop → start
#   - log     : 前台实时跟随 serve_win.log（Ctrl+C 退出，不影响服务）
# 通用参数：-NoBrowser（start 时不自动开浏览器）、-ShowLog（启动后跟随日志）
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File manage.ps1 start [-Watchdog] [-NoBrowser] [-ShowLog]
#   powershell -NoProfile -ExecutionPolicy Bypass -File manage.ps1 stop
#   powershell -NoProfile -ExecutionPolicy Bypass -File manage.ps1 status
#   powershell -NoProfile -ExecutionPolicy Bypass -File manage.ps1 restart
#   powershell -NoProfile -ExecutionPolicy Bypass -File manage.ps1 log
# 说明：无需管理员权限；Ctrl+C / 关闭本窗口不影响已启动的 serve（独立隐藏进程）。
# ============================================================
param(
    [ValidateSet("start", "stop", "status", "restart", "log")]
    [string]$Action = "start",
    [switch]$Watchdog,   # start 后驻留守护（Ctrl+C 退出守护，服务不受影响）
    [switch]$NoBrowser,  # start 时不自动打开浏览器
    [switch]$ShowLog     # start 后在前台跟随服务日志
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$StartScript = Join-Path $ProjectRoot "start.ps1"
$StopScript  = Join-Path $ProjectRoot "stop_win.ps1"
$ServeLog    = Join-Path $ProjectRoot "data\logs\serve_win.log"

# 端口单一事实源：.env 的 API_PORT（与 start.ps1 / stop_win.ps1 一致）
$Port = 18900
$envFile = Join-Path $ProjectRoot ".env"
if (Test-Path $envFile) {
    $m = Select-String -Path $envFile -Pattern '^\s*API_PORT\s*=\s*(\d+)' | Select-Object -Last 1
    if ($m) { [void][int]::TryParse($m.Matches[0].Groups[1].Value, [ref]$Port) }
}
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$WebUrl    = "http://127.0.0.1:$Port/web/"

function Write-Header {
    try { $Host.UI.RawUI.WindowTitle = "OpenKitsune · $Action" } catch { }
    Write-Host ""
    Write-Host "  OpenKitsune · PowerShell 管理 ($Action)" -ForegroundColor Magenta
    Write-Host "  ========================================"
}

function Get-ServeInfo {
    # 返回 @{ PortOwner=$bool; Pid=$int|0; CmdLine=$str|''; Healthy=$bool|$null }
    $owner = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $info = @{ Owner = $false; Pid = 0; CmdLine = ""; Healthy = $null }
    if (-not $owner) { return $info }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)" -ErrorAction SilentlyContinue
    $cmdline = if ($proc) { [string]$proc.CommandLine } else { "" }
    if ($cmdline -match 'openkitsune\s+serve') {
        $info.Owner = $true
        $info.Pid = [int]$owner.OwningProcess
        $info.CmdLine = $cmdline
        try {
            $r = Invoke-WebRequest $HealthUrl -TimeoutSec 3 -UseBasicParsing
            $info.Healthy = ($r.StatusCode -eq 200)
        } catch { $info.Healthy = $false }
    }
    return $info
}

function Start-Services {
    if (-not (Test-Path $StartScript)) {
        Write-Host "  [FAIL] 未找到启动脚本：$StartScript" -ForegroundColor Red
        exit 1
    }
    $info = Get-ServeInfo
    if ($info.Owner) {
        Write-Host ("  [OK] 服务已在端口 {0} 运行（PID {1}），无需重复启动" -f $Port, $info.Pid) -ForegroundColor Green
        if ($info.Healthy) { Write-Host "  [OK] 健康检查通过（/api/health）" -ForegroundColor Green }
        elseif ($info.Healthy -eq $false) { Write-Host "  [WARN] 端口在监听但健康检查未通过" -ForegroundColor Yellow }
        if (-not $NoBrowser) { Start-Process $WebUrl }
        return $true
    }
    Write-Host "  [..] 委派 start.ps1 启动（serve + 90s 健康门控 + 开浏览器）..." -ForegroundColor Cyan
    # 注意：不要把 -ShowLog 透传给 start.ps1。
    # start.ps1 带 -ShowLog 时会在末尾 Get-Content -Wait 死循环跟日志、永不退出，
    # 导致本函数 & powershell.exe @args 同步阻塞，父窗口永远卡在"委派..."这一行，
    # 入口处的 Show-Log 也永远走不到。日志跟随统一由本脚本入口的 Show-Log 负责。
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $StartScript)
    if ($NoBrowser) { $args += "-NoBrowser" }
    & powershell.exe @args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [FAIL] start.ps1 返回码 $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
    $info = Get-ServeInfo
    if (-not $info.Owner -or $info.Healthy -ne $true) {
        Write-Host "  [FAIL] 启动后仍未就绪（端口 $Port / /api/health）" -ForegroundColor Red
        Write-Host "    错误日志：$(Join-Path $ProjectRoot 'data\logs\serve_win.err')" -ForegroundColor DarkGray
        exit 1
    }
    Write-Host "  [OK] openkitsune serve 就绪（PID $($info.Pid)）" -ForegroundColor Green
    return $true
}

function Invoke-Watchdog {
    # 驻留守护：每 5s 探活，连续失败（>3 次 / 15s）→ 自动重启（委派 start.ps1）
    Write-Host "  [watchdog] 守护启动：探活 $HealthUrl（每 5s；服务崩溃将自动重启）" -ForegroundColor Cyan
    Write-Host "  [watchdog] Ctrl+C 退出守护（不影响正在运行的服务）" -ForegroundColor DarkGray
    $failStreak = 0
    while ($true) {
        $info = Get-ServeInfo
        if ($info.Owner -and $info.Healthy) {
            if ($failStreak -gt 0) { Write-Host "  [watchdog] 服务已恢复（PID $($info.Pid)）" -ForegroundColor Green }
            $failStreak = 0
        } else {
            $failStreak++
            $reason = if ($info.Owner) { "端口在监听但 /api/health 未通过" } else { "端口未监听" }
            Write-Host ("  [watchdog] 探测异常（第 {0} 次）：{1}" -f $failStreak, $reason) -ForegroundColor Yellow
            if ($failStreak -ge 3) {
                Write-Host "  [watchdog] 服务疑似崩溃，自动重启..." -ForegroundColor Yellow
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript -NoBrowser
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  [watchdog] 重启完成" -ForegroundColor Green
                } else {
                    Write-Host "  [watchdog] 重启失败（start.ps1 返回码 $LASTEXITCODE），继续探测" -ForegroundColor Red
                }
                $failStreak = 0
            }
        }
        Start-Sleep -Seconds 5
    }
}

function Stop-Services {
    if (-not (Test-Path $StopScript)) {
        Write-Host "  [FAIL] 未找到停止脚本：$StopScript" -ForegroundColor Red
        exit 1
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript
    exit $LASTEXITCODE
}

function Show-Status {
    $info = Get-ServeInfo
    if ($info.Owner) {
        Write-Host ("  [OK] openkitsune serve  端口 {0}  PID {1}" -f $Port, $info.Pid) -ForegroundColor Green
        if ($info.Healthy) { Write-Host "  [OK] /api/health 健康" -ForegroundColor Green }
        else { Write-Host "  [WARN] /api/health 未通过" -ForegroundColor Yellow }
        try {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($info.Pid)" -ErrorAction SilentlyContinue
            if ($proc) {
                $started = [Management.ManagementDateTimeConverter]::ToDateTime($proc.CreationDate)
                $uptime = (Get-Date) - $started
                Write-Host ("  [..] 运行时长 {0} 分 {1} 秒" -f [int]$uptime.TotalMinutes, $uptime.Seconds) -ForegroundColor DarkGray
            }
        } catch { }
        Write-Host "  对话入口：$WebUrl" -ForegroundColor DarkGray
    } else {
        Write-Host "  [..] 未在运行（端口 $Port 无 openkitsune serve 监听）" -ForegroundColor Yellow
    }
}

function Resolve-TailTarget {
    # 与 start.ps1 保持同一策略：
    #   优先跟 file handler 实时写入的 <workspace>\logs\openkitsune.log
    #   （不受 python stdout 块缓冲 / -RedirectStandardOutput 句柄归属影响，
    #    无论 serve 由 start.ps1 / 桌面端 / 手动启动都在写）。
    #   找不到时回退到 data\logs\serve_win.log（python stdout 重定向文件）。
    $OkRoot = $env:OPENKITSUNE_ROOT
    if (-not $OkRoot) { $OkRoot = Join-Path $env:USERPROFILE ".openkitsune" }
    $stateFile = Join-Path $OkRoot "state.json"
    $candidates = New-Object System.Collections.Generic.List[string]
    if (Test-Path $stateFile) {
        try {
            $state = Get-Content $stateFile -Encoding UTF8 -Raw | ConvertFrom-Json
            $wsId = [string]$state.currentWorkspaceId
            if ($wsId -and $wsId -ne "default") {
                $wsDir = Join-Path (Join-Path $OkRoot "workspaces") $wsId
                if (Test-Path $wsDir) {
                    $candidates.Add((Join-Path $wsDir "logs\openkitsune.log"))
                }
            }
        } catch { }
    }
    # 兜底：仓库根 logs\openkitsune.log（开发模式 / 工作区解析失败时）
    $candidates.Add((Join-Path $ProjectRoot "logs\openkitsune.log"))
    $candidates.Add($ServeLog)
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

function Show-Log {
    $tailTarget = Resolve-TailTarget
    if (-not $tailTarget) {
        Write-Host "  [..] 暂无可用日志文件（已检查工作区 openkitsune.log 与 $ServeLog）" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "  实时日志（Ctrl+C 退出，不影响服务）..." -ForegroundColor DarkGray
    Write-Host "  跟随文件：$tailTarget" -ForegroundColor DarkGray
    # 显式 -Encoding UTF8：PS 5.1 默认按 ANSI(GBK) 解码无 BOM 的 UTF-8 日志会乱码
    Get-Content -LiteralPath $tailTarget -Encoding UTF8 -Tail 20 -Wait
}

# ---------------- 入口 ----------------
Write-Header
switch ($Action) {
    "start" {
        Start-Services | Out-Null
        if ($ShowLog) { Show-Log }
        elseif ($Watchdog) { Invoke-Watchdog }
        else {
            Write-Host ""
            Write-Host "  管理入口（同窗口再次调用）：" -ForegroundColor DarkGray
            Write-Host "    停止：  manage.ps1 stop" -ForegroundColor DarkGray
            Write-Host "    状态：  manage.ps1 status" -ForegroundColor DarkGray
            Write-Host "    日志：  manage.ps1 log" -ForegroundColor DarkGray
            Write-Host "    守护：  manage.ps1 start -Watchdog" -ForegroundColor DarkGray
        }
    }
    "stop"    { Stop-Services }
    "status"  { Show-Status }
    "restart" {
        Write-Host "  [..] 停止旧服务..." -ForegroundColor Cyan
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript
        Write-Host "  [..] 重新启动..." -ForegroundColor Cyan
        Start-Services | Out-Null
    }
    "log"     { Show-Log }
}
Write-Host ""
