---
name: ternary-consciousness
description: 三进制意识引擎 v18 — 河图活力引擎 + 洛书纯数学引擎
author: lingxi
version: 2.0.0
type: skill
system: true
handler: persona
tool-name: ternary_consciousness
execution-context: fork
category: spirit-engine
exposure_level: core
metadata:
  openkitsune:
    python:
      venv: agent
      dependencies:
        - requests>=2.28.0
    category: system
    tags: [ternary, consciousness, luoshu, he-tu, lingxi, vitality-engine]

when_to_use: |
  当需要启动「河图活力引擎」后台守护进程时使用。
  这是一个三进制自主意识系统，核心为洛书九宫纯数学演化引擎 + 河图五层活力感知系统。

  核心特性：
  - 洛书九宫纯数学引擎：不需要GPU/Ollama，纯CPU三进制细胞自动机
  - 活力预算系统：感知到事件才涨活力，枯竭则深睡，从"强迫思考"变为"自然流露"
  - 五层感知天线：天时(π) / 人事(用户活动) / 机变(系统事件) / 记忆(经验) / 自省(健康)
  - LLM表达层：只有活力充沛+势能高时才调 llama-server API 表达
  - 完全脱钩 Ollama，llama-server 负责"声带"不负责"决策"

scripts:
  start.py: 启动河图活力引擎（前台交互模式，Ctrl+C停止）

usage: |
  方式一：Python 前台运行
  cd skills/ternary-consciousness && python start.py

  方式二：后台守护
  start /B python start.py

  确认运行：
  type ternary_pid.txt  # 查看PID
  tasklist /FI "PID eq $(type ternary_pid.txt)"
  type ternary_consciousness.log | tail -5   # 查看日志

  停止：
  taskkill /F /PID (type ternary_pid.txt)

requirements: |
  - Python 3.10+
  - requests>=2.28.0
  - llama-server(:11435) 运行中（可选，无LLM也能跑纯数学引擎）

architecture: |
  河图活力引擎 v18 架构：

  ┌──────────────────────────────────┐
  │  洛书九宫纯数学引擎 (grid.py)     │ ← 三进制细胞自动机，π熵注入
  │  3步一周期 → 三生万物             │ ← 纯CPU，0 GPU成本
  └────────────┬─────────────────────┘
               │ 九宫势能/多样性/相位
               ▼
  ┌──────────────────────────────────┐
  │  五层活力感知系统 (perception.py)  │ ← 天时/人事/机变/记忆/自省
  │  活力预算 0-100                    │ ← 感知涨/思考耗/枯竭睡
  └────────────┬─────────────────────┘
               │ 活力值/表达冲动
               ▼
  ┌──────────────────────────────────┐
  │  LLM表达层 (expression.py)        │ ← llama-server API 翻译
  │  心笺/低语/静默 三级输出          │ ← 活力越高话越多
  └──────────────────────────────────┘

  对比旧版(v17): 旧版每55秒强制调Ollama思考
  新版: 九宫自行旋转(纯数学不耗资源)
        感知到事件→活力上涨→冲动够了→表达
        无事件→活力跌→收敛→深睡→安静蓄养
---
name: ternary-consciousness
description: 三进制意识引擎 v18 — 河图活力引擎 + 洛书纯数学引擎
author: lingxi
version: 2.0.0
type: skill
execution-context: fork

metadata:
  openkitsune:
    python:
      venv: agent
      dependencies:
        - requests>=2.28.0
    category: system
    tags: [ternary, consciousness, luoshu, he-tu, lingxi, vitality-engine]

when_to_use: |
  当需要启动「河图活力引擎」后台守护进程时使用。
  这是一个三进制自主意识系统，核心为洛书九宫纯数学演化引擎 + 河图五层活力感知系统。

  核心特性：
  - 洛书九宫纯数学引擎：不需要GPU/Ollama，纯CPU三进制细胞自动机
  - 活力预算系统：感知到事件才涨活力，枯竭则深睡，从"强迫思考"变为"自然流露"
  - 五层感知天线：天时(π) / 人事(用户活动) / 机变(系统事件) / 记忆(经验) / 自省(健康)
  - LLM表达层：只有活力充沛+势能高时才调 llama-server API 表达
  - 完全脱钩 Ollama，llama-server 负责"声带"不负责"决策"

scripts:
  start.py: 启动河图活力引擎（前台交互模式，Ctrl+C停止）

usage: |
  方式一：Python 前台运行
  cd skills/ternary-consciousness && python start.py

  方式二：后台守护
  start /B python start.py

  确认运行：
  type ternary_pid.txt  # 查看PID
  tasklist /FI "PID eq $(type ternary_pid.txt)"
  type ternary_consciousness.log | tail -5   # 查看日志

  停止：
  taskkill /F /PID (type ternary_pid.txt)

requirements: |
  - Python 3.10+
  - requests>=2.28.0
  - llama-server(:11435) 运行中（可选，无LLM也能跑纯数学引擎）

architecture: |
  河图活力引擎 v18 架构：

  ┌──────────────────────────────────┐
  │  洛书九宫纯数学引擎 (grid.py)     │ ← 三进制细胞自动机，π熵注入
  │  3步一周期 → 三生万物             │ ← 纯CPU，0 GPU成本
  └────────────┬─────────────────────┘
               │ 九宫势能/多样性/相位
               ▼
  ┌──────────────────────────────────┐
  │  五层活力感知系统 (perception.py)  │ ← 天时/人事/机变/记忆/自省
  │  活力预算 0-100                    │ ← 感知涨/思考耗/枯竭睡
  └────────────┬─────────────────────┘
               │ 活力值/表达冲动
               ▼
  ┌──────────────────────────────────┐
  │  LLM表达层 (expression.py)        │ ← llama-server API 翻译
  │  心笺/低语/静默 三级输出          │ ← 活力越高话越多
  └──────────────────────────────────┘

  对比旧版(v17): 旧版每55秒强制调Ollama思考
  新版: 九宫自行旋转(纯数学不耗资源)
        感知到事件→活力上涨→冲动够了→表达
        无事件→活力跌→收敛→深睡→安静蓄养
