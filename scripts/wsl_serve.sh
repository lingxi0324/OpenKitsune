#!/bin/bash
# ============================================================
# OpenKitsune WSL serve 管理辅助脚本（v3，适配 E:\agents\OpenKitsune-main 部署）
# 被 start.ps1 调用；在 WSL 内以 administrator 用户运行
# 用法: wsl_serve.sh <status|stop|start|model>
#   status -> UP / DOWN（18900 是否监听）
#   stop   -> STOPPED / NOT_RUNNING / STOP_FAILED
#             先 SIGTERM 优雅停止 → 等待 18900 释放（最多 20s）
#             → 仍未释放则 SIGKILL 兜底
#   start  -> ALREADY_UP / STARTING / START_FAILED
#             若已有 serve 进程在初始化（boot 自动拉起等），
#             等待其完成绑定，不重复拉起（防双实例竞争 18900）
#   model  -> OK / DOWN（探测主推理端点 8240/8220/8200，供启动脚本提示）
# 与 v2 的区别：SERVE_DIR 指向 /mnt/e 挂载路径的新部署。
# ============================================================
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SERVE_DIR=/mnt/e/agents/OpenKitsune-main
PYTHON=$SERVE_DIR/venv/bin/python
LOG=$SERVE_DIR/data/logs/serve_wsl.log
PATTERN="python -m openkitsune serve"

# 端口不再硬编码：优先级 命令行第 2 参数 > 环境变量 API_PORT > .env 的 API_PORT > 18900。
# 这样改 .env 端口后，status/start/stop/model 仍能对准同一端口
# （旧版写死 18900，用户改端口后脚本会误判 DOWN 并重复拉起实例）。
ENV_API_PORT=$(sed -n 's/^[[:space:]]*API_PORT[[:space:]]*=[[:space:]]*//p' "$SERVE_DIR/.env" 2>/dev/null | tail -n 1 | tr -d '\r')
PORT="${2:-${API_PORT:-$ENV_API_PORT}}"
PORT="${PORT:-18900}"

port_up() { ss -tln 2>/dev/null | awk 'NR>1 {print $4}' | grep -qE "[:.]${PORT}$"; }
serve_running() { pgrep -f "$PATTERN" >/dev/null 2>&1; }

case "$1" in
  status)
    if port_up; then echo UP; else echo DOWN; fi
    ;;
  stop)
    if ! serve_running && ! port_up; then echo NOT_RUNNING; exit 0; fi
    pkill -f "$PATTERN" 2>/dev/null
    i=0
    while [ $i -lt 20 ]; do
      if ! port_up; then echo STOPPED; exit 0; fi
      sleep 1
      i=$((i+1))
    done
    # 优雅退出超时：强制兜底
    pkill -9 -f "$PATTERN" 2>/dev/null
    sleep 1
    if port_up; then echo STOP_FAILED; exit 1; fi
    echo STOPPED
    ;;
  start)
    if port_up; then
      echo ALREADY_UP
    elif serve_running; then
      # 已有 serve 进程在初始化（boot 自动拉起等），等待其完成绑定
      i=0
      while [ $i -lt 25 ]; do
        if port_up; then echo ALREADY_UP; exit 0; fi
        sleep 1
        i=$((i+1))
      done
      echo START_FAILED
      exit 1
    else
      cd "$SERVE_DIR" || { echo START_FAILED; exit 1; }
      # 确保日志目录存在
      mkdir -p data/logs
      export OPENKITSUNE_LOG_COLOR=1
      # v3.1: WSLg 会设置 DISPLAY=:0 使 headless 判定为 False，导致默认绑定
      # 127.0.0.1；Windows 侧访问需要 0.0.0.0（经 WSL IP）+ 首次访问强制设密码。
      # 若 .env 显式配置了 API_HOST 则尊重之，否则默认 0.0.0.0。
      ENV_API_HOST=$(sed -n 's/^[[:space:]]*API_HOST[[:space:]]*=[[:space:]]*//p' "$SERVE_DIR/.env" 2>/dev/null | tail -n 1 | tr -d '\r')
      export API_HOST="${API_HOST:-${ENV_API_HOST:-0.0.0.0}}"
      setsid nohup "$PYTHON" -m openkitsune serve >> "$LOG" 2>&1 &
      # 等待绑定（serve 初始化需数秒）：最多 12s；
      i=0
      while [ $i -lt 12 ]; do
        if port_up; then echo ALREADY_UP; exit 0; fi
        if ! serve_running; then
          echo START_FAILED
          tail -n 15 "$LOG" >&2
          exit 1
        fi
        sleep 1
        i=$((i+1))
      done
      echo STARTING
    fi
    ;;
  model)
    # 对齐 WSL 全栈：主模型 qwen36(8220) 由 model-manager(8240) 网关管理，
    # qwen38(8200) 为按需互斥模型。任一在线即视为推理就绪。
    if curl -s -m 3 http://127.0.0.1:8240/api/admin/health 2>/dev/null | grep -q '"code":200' ; then
      echo OK
    elif curl -s -m 3 http://127.0.0.1:8220/health 2>/dev/null | grep -q '"status"' ; then
      echo OK
    elif curl -s -m 3 http://127.0.0.1:8200/health 2>/dev/null | grep -q '"status"' ; then
      echo OK
    else
      echo DOWN
    fi
    ;;
  *)
    echo "usage: wsl_serve.sh <status|stop|start|model>"
    exit 2
    ;;
esac
