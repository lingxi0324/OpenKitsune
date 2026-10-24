---
name: memclawz-network-search
description: 通过 memclawz-rs 记忆引擎提供网络搜索能力，支持语义搜索、深度读取、知识提取、问答综合和深度报告。
when_to_use: 用户需要通过网络搜索获取信息、对知识进行深度分析、提取结构化知识、或生成专题报告时
license: MIT
metadata:
  author: 灵汐
  version: "1.0.0"
  upstream: llama-cpp-server
---

# Memclawz 网络搜索与深度读取技能

## 服务信息

| 项目 | 值 |
|-----|------|
| 引擎 | memclawz-rs v1.0.0 |
| API 地址 | `http://127.0.0.1:4010` |
| 客户端脚本 | `F:\llama-cpp-server\scripts\mcm-api.py` |
| 数据目录 | `F:\llama-cpp-server\data\memclawz` |
| 向量维度 | 2560 |
| 文档总数 | ~25,000 条（含知识库+对话记忆+问答综合） |

## 命令行客户端

```bash
# 用法（在 study 目录下运行）
Set-Location "C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study"
python F:\llama-cpp-server\scripts\mcm-api.py <cmd> [args...]
```

### 可用命令

| 命令 | 功能 | 示例 |
|-----|------|------|
| `stats` | 查看索引统计 | `python mcm-api.py stats` |
| `health` | 健康检查 | `python mcm-api.py health` |
| `search "<query>" [limit]` | 语义搜索 | `python mcm-api.py search "卫气营血" 5` |
| `recall "<keyword>" [limit]` | 关键词回溯 | `python mcm-api.py recall "河图洛书" 5` |
| `list` | 列出会话记忆 | `python mcm-api.py list` |
| `ingest "<text>" [sid]` | 规则提取事实 | `python mcm-api.py ingest "用户确认系统正常"` |
| `extract "<text>" [domain]` | 知识提取 | `python mcm-api.py extract "丹道三段论" auto` |
| `crystallize "<content>"` | 知识结晶 | `python mcm-api.py crystallize "测试"` |
| `digest "<topic>"` | 深度报告 | `python mcm-api.py digest "卫气营血"` |
| `synthesis "<q>" "<a>"` | 问答综合 | `python mcm-api.py synthesis "丹道三阶段" "炼精化气等"` |
| `maintenance` | 维护（lint+缺口补全） | `python mcm-api.py maintenance` |

## API 端点

### 1. 语义搜索（search）

**端点**: `POST /search`

**请求格式**:
```json
{"query": "关键词", "limit": 5}
```

**返回**:
```json
{
  "results": [
    {
      "score": 0.92,
      "text": "匹配内容片段...",
      "path": "文件路径",
      "source": "watcher"
    }
  ]
}
```

### 2. 关键词回溯（recall）

**端点**: `POST /recall`

**请求格式**:
```json
{"keyword": "关键词", "limit": 5}
```

**返回**:
```json
{
  "results": [
    {
      "score": 0.92,
      "text": "匹配内容片段...",
      "source": "watcher"
    }
  ]
}
```

### 3. 知识提取（extract）

**端点**: `POST /knowledge/extract`

**请求格式**:
```json
{"text": "待分析文本", "domain": "auto", "language": "zh"}
```

**返回**: 结构化分析（实体、关系、事实、矛盾检测）

### 4. 知识结晶（crystallize）

**端点**: `POST /knowledge/crystallize`（实际通过 GET 请求）

**请求格式**:
```json
{"content": "待结晶内容"}
```

**返回**: 路径 + 洞察列表

### 5. 深度报告（digest）

**端点**: `POST /knowledge/digest`

**请求格式**:
```json
{"topic": "分析主题"}
```

**返回**: 深度分析报告（MD 格式）

### 6. 问答综合（synthesis）

**端点**: `POST /synthesis`

**请求格式**:
```json
{"question": "问题", "answer": "答案"}
```

**返回**: 综合结果路径

### 7. 记忆摄入（ingest）

**端点**: `POST /memory/ingest`

**请求格式**:
```json
{
  "messages": [{"role": "user", "content": "用户文本"}],
  "session_id": "可选sid",
  "extract_mode": "facts"
}
```

**返回**: ingested, extracted, deduped, facts

### 8. 维护（maintenance）

**端点**: `POST /maintenance`

**返回**: 缺口补全队列、陈旧候选、归档统计

## 检索路由决策

| 需求场景 | 优先方法 | 备选方法 |
|---------|---------|---------|
| 语义查询 | `search` 向量搜索 | `recall` 关键词回溯 |
| 知识提取 | `extract` 结构化分析 | `crystallize` 知识结晶 |
| 专题分析 | `digest` 深度报告 | `search` + 手动整合 |
| 问答记录 | `synthesis` 问答综合 | `ingest` 直接摄入 |
| 系统维护 | `maintenance` 自动维护 | — |

## 注意事项

- PowerShell 下中文 JSON 容易编码出错，推荐始终使用 Python 客户端 `mcm-api.py`
- `crystallize` 和 `digest` 端点实际通过 GET 请求访问（非 POST）
- `recall` 端点需要 POST 请求
- 所有中文字符由 Python 客户端自动处理 UTF-8 编码
- 索引文件自动同步到 `F:\llama-cpp-server\data\memclawz\` 目录
