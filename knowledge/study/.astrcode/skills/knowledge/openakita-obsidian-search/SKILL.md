---
name: openakita-obsidian-search
description: 检索 workstation-study 工作区 Obsidian 知识库（丹道玄医录 + 图书馆），支持向量语义搜索 + 关键词检索 + 目录浏览。
when_to_use: 用户需要查询知识库内容、查找特定笔记、检索中医/丹道/玄学相关知识时
license: MIT
metadata:
  author: 灵汐
  version: "1.0.0"
  upstream: openakita
---

# Obsidian 知识库检索技能

## 知识库路径

**根目录**: `C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\`

**子库结构**:
```
study/
├── 丹道玄医录/       ← 活跃推演层（个人理论·AI辨证·推演决策 · 4997篇MD）
│   ├── 00-索引/      ← 总索引、知识图谱、学习路线
│   ├── 01-中医/      ← 中医基础理论、辨证方法、临床医案
│   ├── 02-丹道/      ← 修炼次第、体悟理论
│   ├── 03-玄学/      ← 命理、奇门、市场推演
│   ├── 04-融合/      ← 河洛数理、交叉创新、医道桥梁
│   ├── 05-设计/      ← AI引擎、脚本工具、技术文档
│   └── 06-灵汐档案/  ← 灵汐助手核心档案
├── 图书馆/           ← 原典参考层（道藏/医藏/易经/丹道 · 按需检索）
│   ├── 道藏/         ← 正统道藏 9 部
│   ├── 医藏/         ← 30 类医书
│   ├── 易经/         ← 450+ 本
│   └── 丹道/         ← 丹道经典
├── tools/            ← 工具集
└── .obsidian/        ← Obsidian 配置
```

## 检索方法

### 1. 向量语义搜索（推荐，最智能）

使用 memclawz 引擎进行语义检索：

```bash
# 搜索
python F:\llama-cpp-server\scripts\mcm-api.py search "丹道玄医谱" 5

# 记忆回溯
python F:\llama-cpp-server\scripts\mcm-api.py recall "河图洛书" 5

# 健康检查
python F:\llama-cpp-server\scripts\mcm-api.py health

# 统计信息
python F:\llama-cpp-server\scripts\mcm-api.py stats
```

**参数说明**：
- `search <query> <limit>`：语义检索，返回 score + path + text
- `recall <keyword> <limit>`：关键词回溯，返回相关记忆片段
- 需要中文字符时，Python 客户端自动处理 UTF-8 编码

### 2. 目录浏览

使用索引生成器或 PowerShell 查看目录结构：

```bash
# 快速查看子目录
python C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\tools\auto_index_generator.py list "C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\丹道玄医录" --max-depth 2

# 生成索引
python C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\tools\auto_index_generator.py scan "C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\丹道玄医录" --max-depth 2 --style table
```

### 3. 直接读取笔记

使用 `read_file` 工具直接读取 Markdown 笔记内容。

### 4. 索引搜索工具

```bash
# 使用 index_search.py 搜索笔记内容
python C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study\tools\index_search.py "卫气营血"
```

## 检索路由决策

| 用户需求 | 优先方法 | 备选方法 |
|---------|---------|---------|
| 语义查询（"有什么关于XX的知识"） | memclawz 向量搜索 | 目录浏览 |
| 查找特定笔记 | read_file 直接读取 | 索引搜索 |
| 探索知识结构 | 目录浏览 + 总索引 | memclawz recall |
| 交叉引用检索 | 知识图谱索引 | 向量搜索 |

## 维护

- 定期运行索引更新：`auto_index_generator.py scan`
- 向量索引更新：memclawz watcher 自动同步（丹道玄医录文件变化时自动触发）
- 索引文件：`study\全库索引.md`（最新生成 2026-10-10）

## 注意事项

- 丹道玄医录含 4997 篇 Markdown 文件，首次索引约需 1-2 分钟
- 向量搜索优先（语义理解），目录浏览用于探索
- 注意中文字符编码，使用 Python 客户端而非 curl.exe 发送中文参数
- 索引文件位于 `study\` 目录，包含完整的目录结构和文件列表
