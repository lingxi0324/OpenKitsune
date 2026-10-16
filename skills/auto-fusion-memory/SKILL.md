---
name: auto-fusion-memory
description: 玄医融合记忆自动内化技能——每轮对话后自动提取、索引、结晶为长期知识；经本地 fusion-memory（lcs-fusion-memory 三速记忆引擎，127.0.0.1:4010）提供语义检索、记忆回溯、玄医知识统计与知识图谱。
category: 知识与效率
---

# 🧠 Auto-Memory System (fusion-memory) — 自主记忆内化技能

## 概述

这是一个自动记忆内化技能，会将每次对话中的重要信息**自动提取、索引、结晶为长期知识**，无需手动操作。后端为本地 Rust 引擎 **fusion-memory**（lcs-fusion-memory：QMD 量化记忆 + 混合检索 + 自动索引 watcher）。

## 服务地址

- **fusion-memory**（记忆引擎）: `http://127.0.0.1:4010`
- **Embedding**（向量模型）: `http://127.0.0.1:8120`（`POST /v1/embeddings`，维度 2560）

## API 端点一览（与 server.rs 路由实测一致，2026-10-10）

| 操作 | 端点 | 必需参数 | 用途 |
|------|------|------|------|
| 健康检查 | `GET /health` | 无 | 引擎存活状态 |
| 状态统计 | `GET /stats` | 无 | 索引统计（chunks / dim / 数据目录） |
| 玄医知识统计 | `GET /xuan-yi/stats` | 无 | 玄医知识库聚合统计 |
| 语义搜索 | `POST /search` | `{"query": "...", "limit"?: 5}` | 混合检索 + 图谱扩展 |
| 记忆回溯 | `POST /recall` | `{"keyword": "...", "limit"?: 5}` | 关键词回溯 |
| 深度分析 | `POST /analyze` | `{"query": "...", "mode"?: "..."}` | 综合分析 |
| 综合问答 | `POST /synthesis` | `{"question": "...", "answer": "..."}` | 问答综合记录（写入 xuan-yi/syntheses） |
| 知识图谱 | `POST /graph/expand` | `{"nodes": ["..."]}` | 图谱邻接关系展开 |
| 知识提取 | `POST /knowledge/extract` | `{"text": "...", "domain"?: "...", "language"?: "zh"}` | 结构化提取（source_summary/entities/relations/facts/contradictions） |
| 知识摄入 | `POST /knowledge/ingest` | `{"text": "...", "embedding"?: [2560维]}` | 写入向量库 |
| 知识结晶 | `POST /knowledge/crystallize` | `{"content": "..."}`（必需 `content` 字段） | 去重、合并、提炼核心知识 |
| 知识消化 | `POST /knowledge/digest` | `{"topic": "..."}`（必需 `topic` 字段） | 主题深度报告 |
| 知识融合 | `POST /knowledge/fusion` | `{"content": "..."}` | 多源知识融合 |
| 知识合并 | `POST /knowledge/merge` | `{"content": "..."}` | 合并相似条目 |
| 会话管理 | `GET /memory/list` | 无 | 列出会话记忆条目 |
| 记忆摄入 | `POST /memory/ingest` | `{"messages":[{"role":"user","content":"..."}],"session_id"?: "...","extract_mode"?: "facts"}` | 提取事实并入对话记忆 |
| 记忆编辑/删除/归档 | `POST /memory/edit` / `/memory/delete` / `/memory/archive` | 按记忆条目参数 | 记忆维护 |
| 分层记忆 | `GET /memory/layers` | 无 | 记忆分层视图 |
| 每日记忆 | `GET /memory/daily` / `/memory/daily/list` / `/memory/daily/stats` | 无 | 日级记忆统计 |
| 自愈分析 | `GET /api/errors` | 无 | 引擎错误事件 |
| 维护 | `POST /maintenance` | 无 | 索引优化、压缩、清理（lint + 缺口补全） |

### 调用规范（重要：中文 JSON 编码）

PowerShell 5.1 下直接 `curl -d` 或 `Invoke-RestMethod -Body (string)` 发送中文 body 会把中文转成乱码。统一改用以下任一方式：

1. **推荐：本仓库 Python 客户端**（UTF-8 安全，覆盖常用端点）：
   ```
   F:\llama-cpp-server\.venv\Scripts\python.exe F:\llama-cpp-server\scripts\fm-api.py search "王书贤" 3
   F:\llama-cpp-server\.venv\Scripts\python.exe F:\llama-cpp-server\scripts\fm-api.py stats
   F:\llama-cpp-server\.venv\Scripts\python.exe F:\llama-cpp-server\scripts\fm-api.py ingest "我偏好用中成药作为内服方案的补充。"
   F:\llama-cpp-server\.venv\Scripts\python.exe F:\llama-cpp-server\scripts\fm-api.py maintenance
   ```
   支持：stats / health / search / recall / list / ingest / extract / crystallize / digest / synthesis / maintenance。
2. **Python 内联**：`json.dumps(payload, ensure_ascii=False).encode('utf-8')` + `urllib`，`Content-Type: application/json; charset=utf-8`。
3. **PowerShell**：`Invoke-RestMethod -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType 'application/json'`。
4. **curl.exe**：把 JSON 写入临时文件后 `curl.exe -X POST http://127.0.0.1:4010/<endpoint> --data-binary @body.json`。

## 自动内化流程（每轮对话后自动触发）

### Phase 1: 提取 (Extract)
```
输入: 完整对话文本（用户消息 + AI回复）
动作: POST /knowledge/extract
参数: {"text": "...", "domain": "auto", "language": "zh"}
输出: 结构化知识片段 analysis（source_summary, entities, relations, facts, contradictions）
```

### Phase 2: 摄入 (Ingest)
```
输入: 提取的 knowledge 片段 + 嵌入向量
动作: 先用 8120 生成 2560 维 embedding，再 POST /knowledge/ingest（或 /index 语义等价）
参数: {"text": "<知识文本>", "embedding": [2560维向量]}
输出: 向量索引条目（已嵌入到向量空间）
```

> **ingest 行为说明**
> - 无事实可沉淀（规则/LLM 均未提取出事实）时，`/memory/ingest` 返回 `ingested:0, fallback_reason:"no_facts_skip_write"`，**不再写对话段**，从源头杜绝「## 会话 unknown + 空记忆事实」噪音。
> - `session_id` 缺失/为空时，会话名自动派生：取首条用户消息前 20 字（清理非法字符）生成 `auto-<标签>`；无有效用户消息时退回 `auto-YYYYMMDD`。
> - watcher 分块时，chunk 内无 `## 会话` 头则向上继承文件内最近一个会话头，避免事实块 session_id 落空。

### Phase 3: 结晶 (Crystallize)
```
输入: 所有近期提取的知识片段
动作: POST /knowledge/crystallize
参数: {"content": "<聚合后的核心知识点文本>"}
输出: 去重合并后的核心知识点（写入 sessions 目录）
```

### Phase 4: 消化 (Digest)
```
输入: 结晶后的核心知识点
动作: POST /knowledge/digest
参数: {"topic": "<主题名>"}
输出: 该主题的深度分析报告（写入 synthesis 目录，watcher 自动索引）
```

### Phase 5: 融合 (Fusion) — 可选，定期运行
```
输入: 消化后的知识图谱 + 历史知识
动作: POST /knowledge/fusion
输出: 融合后的统一知识库
```

## 自动触发条件

以下任一条件满足时，自动执行内化流程：

1. **对话结束标记**: 用户明确结束对话（"好了""就这样吧"）
2. **会话超时**: 用户超过 15 分钟无新消息
3. **对话长度**: 单轮对话超过 10 个回合（每 3 回合触发一次）
4. **关键知识出现**: 检测到"记住""保存""这个很重要"等关键词时立即触发
5. **定时任务**: 每 30 分钟检查一次对话历史并内化

## 使用方法

**无需任何操作**——此技能由后台自动调度。当你完成一次有意义的对话后，系统会自动：
1. 从对话文本中提取结构化知识
2. 写入 fusion-memory 向量库
3. 结晶为可检索的长期记忆
4. 下次对话时自动检索相关历史

## 手动触发（可选）

如果需要立即内化某段对话：
- 调用 `run_shell` 发送 `POST /knowledge/extract` 并指定对话文本
- 或调用 `run_shell` 发送 `POST /knowledge/crystallize`（参数 `{"content": "..."}`）立即结晶
- 需要向量化时先调 `POST http://127.0.0.1:8120/v1/embeddings` 获取 2560 维向量再写入 `/knowledge/ingest`

## 维护

- `POST /maintenance` — 执行索引优化、压缩、清理（lint + 缺口补全队列）
- `POST /knowledge/merge` — 手动合并重复知识
- `python F:\llama-cpp-server\scripts\clean_empty_entries.py` — 移除 dialogue-*.md 中无事实的空会话段
- `python F:\llama-cpp-server\scripts\fm-api.py maintenance` — 等价于 `POST /maintenance`

### watcher 索引一致性

- 变更文件：**先 `delete_by_path` 删除该路径全部旧分块，再嵌入写入新分块**（避免旧 start_line 分块残留成孤儿索引）。
- 空文件/纯标题文件：同样先删除旧分块再记录哈希。
- 删除文件：下一轮 sync 摘除其全部索引块。
- 会话头继承：chunk 无 `## 会话` 头时向上继承文件内最近一个会话头。

### 二进制与端口治理（运维要点）

- **主运行二进制为 release**：`F:\llama-cpp-server\target\release\fusion-memory.exe`（由 start_services.ps1 启动，`--root F:\llama-cpp-server --port 4010 serve`）。
- 端口唯一事实源：`config\ports.yaml`（键 `fusion-memory: 4010`）；watchdog / start_services.ps1 均从 ports.yaml 读取。不要手工用旧端口起实例，否则与定时任务/技能端口不一致。
- 启动入口：`F:\llama-cpp-server\start_services.ps1 start`（fusion-memory 在 SERVICES 列表内，health 检查 /health）。
- PowerShell 5.1 下给 python.exe 传中文命令行参数会乱码（search/ingest 全部失效）；一律用脚本文件内嵌 UTF-8 文本或 fm-api.py。
