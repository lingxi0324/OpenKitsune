#!/bin/bash
# ============================================================
# 兼容入口（v4，2026-10-18）
# 真正的管理逻辑统一在 scripts/wsl_serve.sh（从 .env 读取 API_PORT/API_HOST）。
# 本文件为历史根目录入口保留，防止旧文档/boot 任务调用到 v2 的硬编码路径
# （v2 指向已迁移的 ~/.openkitsune/OpenKitsune，会拉起错误部署）。
# 用法: wsl_serve.sh <status|stop|start|model> [port]
# ============================================================
exec bash "$(dirname "$0")/scripts/wsl_serve.sh" "$@"
