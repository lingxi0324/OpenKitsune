<#
.SYNOPSIS
  本地视觉服务（llama.cpp + Qwen3.8-35B mmproj）启动/探测/停止辅助。

.DESCRIPTION
  默认仅探测 8221 端口是否已提供服务；
  -Start 启动视觉服务（后台，日志 temp\vision_server.log）；
  -Stop  停止视觉服务进程。

.NOTES
  模型：llama.cpp server 根目录（环境变量 LLAMACPP_SERVER_ROOT）下
        model\llm\Qwen3.8-35B-A3B-IQ3_M.gguf
        + mmproj-Qwen3.8-35B-A3B-F16.gguf
  端口：8221（与文本服务 8220 区分）
#>
param(
    [switch]$Start,
    [switch]$Stop
)

# llama.cpp server 根目录：优先环境变量，未设置则探测常见部署位置。
# 不要在此硬编码机器专属路径。
$serverRoot = $env:LLAMACPP_SERVER_ROOT
if (-not $serverRoot) {
    $candidates = @(
        "F:\llama-cpp-server",
        "E:\llama-cpp-server",
        "D:\llama-cpp-server"
    )
    $serverRoot = $candidates | Where-Object { Test-Path (Join-Path $_ "model\bin\llama-server.exe") } | Select-Object -First 1
}
if (-not $serverRoot) {
    Write-Error "未找到 llama.cpp server 根目录。请设置环境变量 LLAMACPP_SERVER_ROOT 后重试。"
    exit 1
}

$serverExe = Join-Path $serverRoot "model\bin\llama-b10488\llama-server.exe"
$model     = Join-Path $serverRoot "model\llm\Qwen3.8-35B-A3B-IQ3_M.gguf"
$mmproj    = Join-Path $serverRoot "model\llm\mmproj-Qwen3.8-35B-A3B-F16.gguf"
$port      = 8221
$logPath   = Join-Path $PSScriptRoot "..\..\temp\vision_server.log"

function Test-VisionPort {
    # 防误报：端口监听且占用进程必须是 llama 系服务
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.Name -like "llama*") {
            Write-Output "[探测] 端口 $port 已监听 (PID $($conn.OwningProcess)) — 视觉服务运行中"
            return $true
        }
    }
    Write-Output "[探测] 端口 $port 未监听 — 视觉服务未启动"
    return $false
}

if ($Stop) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force
        Write-Output "[停止] 已终止视觉服务进程 $($conn.OwningProcess)"
    } else {
        Write-Output "[停止] 视觉服务未在运行"
    }
    exit 0
}

if (Test-VisionPort) {
    if ($Start) { Write-Output "[提示] 已在运行，无需重复启动" }
    exit 0
}

if (-not $Start) {
    Write-Output "[提示] 未加 -Start，仅探测。启动命令: powershell -File start_vision_server.ps1 -Start"
    exit 0
}

if (-not (Test-Path $serverExe)) { Write-Output "[错误] 找不到 llama-server: $serverExe"; exit 1 }
if (-not (Test-Path $model))     { Write-Output "[错误] 找不到主模型: $model"; exit 1 }
if (-not (Test-Path $mmproj))    { Write-Output "[错误] 找不到 mmproj: $mmproj"; exit 1 }

New-Item -ItemType Directory -Force (Split-Path $logPath -Parent) | Out-Null
Write-Output "[启动] 加载视觉模型 $([IO.Path]::GetFileName($model)) ..."
$proc = Start-Process -FilePath $serverExe -ArgumentList @(
    "-m", $model,
    "--mmproj", $mmproj,
    "--host", "127.0.0.1",
    "--port", "$port",
    "-ngl", "99",
    "-c", "8192",
    "-t", "16",
    "--flash-attn", "on"
) -RedirectStandardOutput $logPath -RedirectStandardError "$logPath.err" -PassThru -WindowStyle Hidden

Write-Output "[启动] 视觉服务进程 PID $($proc.Id)，日志: $logPath"
Write-Output "[等待] 探测 8221 就绪（最多 120 秒）..."
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 5
    if (Test-VisionPort) {
        Write-Output "[完成] 视觉服务就绪: http://127.0.0.1:$port/v1"
        exit 0
    }
}
Write-Output "[警告] 120 秒内未就绪，请检查日志: $logPath / $logPath.err"
exit 2
