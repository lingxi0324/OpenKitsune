# CLI 命令参考

## 概述

OpenKitsune 提供 `openkitsune` 命令行工具，是与系统交互的另一种方式。适合无桌面环境的服务器部署、脚本自动化，或者你就是喜欢终端。

::: tip 如何获得 `openkitsune` / `oa` 命令
这些命令由 Python 包提供，需先通过 `pip install openkitsune` 安装（详见[安装指南](/guide/installation)）。安装后 `openkitsune` 可执行文件会随 pip 自动加入 PATH。

桌面版安装包**不会**向系统 PATH 注册 `openkitsune` / `oa` 命令——桌面用户请直接使用图形界面；如需终端命令，按上面的方式用 pip 安装即可。
:::

## 子命令一览

| 命令 | 说明 | 示例 |
|------|------|------|
| `openkitsune` | 启动交互式 CLI + IM 通道 | `openkitsune` |
| `openkitsune init [dir]` | 初始化配置向导 | `openkitsune init ~/my-workspace` |
| `openkitsune run "task"` | 执行单个任务后退出 | `openkitsune run "总结今天的邮件"` |
| `openkitsune selfcheck` | 运行系统自检 | `openkitsune selfcheck` |
| `openkitsune status` | 查看 Agent 运行状态 | `openkitsune status` |
| `openkitsune compile` | 编译 Identity 文件 | `openkitsune compile` |
| `openkitsune prompt-debug` | 输出当前组装的完整 Prompt | `openkitsune prompt-debug` |
| `openkitsune serve` | 仅启动 API 服务（IM + HTTP） | `openkitsune serve` |

### openkitsune（交互模式）

最常用的启动方式。进入交互式对话的同时，自动启动已配置的 IM 通道：

```bash
openkitsune
```

启动后在终端中直接输入消息与 Agent 对话，同时 Telegram/飞书等通道也在监听。

### openkitsune init

初始化工作区并运行配置向导：

```bash
openkitsune init              # 在当前目录初始化
openkitsune init ~/workspace  # 在指定目录初始化
```

向导会依次引导你完成 LLM 端点、IM 通道等配置，等同于 Web 界面的 [配置向导](/web/#/config/llm)。

### openkitsune run

执行单个任务，完成后自动退出，适合脚本调用：

```bash
openkitsune run "帮我把 report.md 翻译成英文"
openkitsune run "分析 data.csv 中的销售趋势"
```

### openkitsune selfcheck

运行自检，诊断常见问题：

```bash
openkitsune selfcheck
```

检查项包括：LLM 连接、IM 通道状态、依赖完整性、Identity 文件有效性。

### openkitsune status

查看当前运行状态的快照：

```bash
openkitsune status
```

输出包括：活跃的 Agent 数量、已连接的 IM 通道、内存用量、任务队列状态。

### openkitsune compile

手动编译 Identity 文件（`identity/` 目录下的 SOUL.md、AGENT.md 等）到 `identity/runtime/`：

```bash
openkitsune compile
```

::: tip 提示
通常不需要手动执行。`prompt/builder.py` 会自动检测 Identity 文件是否过期并触发编译。修改 Identity 后若未自动生效，可手动执行此命令。
:::

### openkitsune prompt-debug

输出当前完整的系统 Prompt（编译后），用于调试：

```bash
openkitsune prompt-debug
```

输出内容为 PromptBuilder 组装的最终 Prompt，包含所有层级：Identity → Persona → Runtime → Session Rules → Catalogs → Memory。

### openkitsune serve

启动 HTTP API 服务和 IM 通道，不进入交互式 CLI：

```bash
openkitsune serve
```

适用于后台服务部署。Web 界面通过 `http://localhost:18900` 访问。

## 交互式命令

在交互模式（`openkitsune`）中，以 `/` 开头输入命令：

### 通用命令

| 命令 | 说明 |
|------|------|
| `/help` | 查看所有可用命令和说明 |
| `/status` | 查看系统运行状态 |
| `/selfcheck` | 运行自检诊断 |
| `/memory` | 查看和管理 Agent 记忆 |
| `/skills` | 列出已启用的技能 |
| `/channels` | 查看 IM 通道连接状态 |
| `/agents` | 列出当前 Agent 及子 Agent |
| `/clear` | 清空当前会话历史 |
| `/exit` | 退出交互模式 |

### 模型切换命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/model` | 查看当前使用的模型与端点 | `/model` |
| `/switch <model>` | 临时切换到指定模型 | `/switch claude-sonnet-4-20250514` |
| `/priority` | 查看或调整端点优先级 | `/priority` |
| `/restore` | 恢复默认模型配置 | `/restore` |

::: tip 作用范围
`/switch` 仅对当前会话生效。永久修改请前往 [LLM 端点配置](/web/#/config/llm)。
:::

## 相关页面

- [聊天对话](/features/chat) — Web 界面的对话功能与命令
- [配置向导详解](/advanced/wizard) — 完整配置字段说明
- [高级设置](/advanced/advanced) — 网络与系统配置
- [生产部署](/network/production) — 服务器部署指南

