# Obsidian 知识库工具集成方案

> **创建时间**: 2026-10-08
> **Obsidian 版本**: 1.12.7
> **Vault 路径**: `C:\Users\Administrator\.OpenKitsune\workspaces\ws_1791446309397\study`
> **工具类型**: 本地 Python 脚本 + OpenKitsune 原生工具

---

## 一、当前环境状态

| 项目 | 状态 |
|------|------|
| Obsidian 安装 | ✅ 已安装（D:\Program Files (x86)\Obsidian\Obsidian.exe） |
| Vault 位置 | `study/`（工作区 ws_1791446309397） |
| 核心插件 | 全部默认启用（file-explorer, global-search, switcher, graph, backlink 等） |
| 社区插件 | 未安装 |
| OpenKitsune 工具 | ✅ 可用（read_file, edit_file, grep, glob, list_directory） |

---

## 二、Obsidian 工具映射方案

由于 OpenKitsune 没有原生 Obsidian 插件工具，我们用 **Python 脚本 + OpenKitsune 内置工具** 实现等效功能：

### 2.1 vault_list（库文件扫描）

**实现方式**：使用 `list_directory` + `glob` 工具

```python
# 示例：扫描 study/ 目录下所有 .md 文件
glob(path="study", pattern="**/*.md", recursive=True)
```

### 2.2 vault_read（笔记读取）

**实现方式**：使用 `read_file` 工具，自动提取 YAML frontmatter

```python
# OpenKitsune 原生 read_file 已足够
read_file(path="study/丹道玄医录/00-索引/总索引.md")
```

### 2.3 vault_search（全文检索）

**实现方式**：使用 `grep` 工具，支持正则搜索

```python
# 搜索所有包含"桂枝汤"的 .md 文件
grep(pattern="桂枝汤", path="study", include="*.md", max_results=50)

# 搜索特定标签
grep(pattern="## 中医", path="study", include="*.md", max_results=50)
```

### 2.4 graph_scan（图谱扫描）

**实现方式**：分析内部链接 `[[xxx]]`

```python
# 使用 grep 搜索双链语法
grep(pattern="\[\[.*\]\]", path="study", include="*.md", max_results=100)
```

### 2.5 note_write（新建/覆写笔记）

**实现方式**：使用 `write_file` 工具

```python
# 新建笔记
write_file(
    path="study/新笔记.md",
    content="# 标题\n\n内容..."
)
```

### 2.6 note_patch（局部编辑）

**实现方式**：使用 `edit_file` 工具

```python
# 局部替换
edit_file(
    path="study/丹道玄医录/00-索引/总索引.md",
    old_string="旧内容",
    new_string="新内容"
)
```

### 2.7 note_move（移动/重命名）

**实现方式**：使用 `move_file` 工具（自动更新双链）

### 2.8 note_delete（删除笔记）

**实现方式**：使用 `delete_file` 工具

---

## 三、增强工具（社区插件等效）

### 3.1 dataview_query 结构化查询

**实现方式**：使用 `grep` + `read_file` 组合

```python
# 搜索带有特定 YAML frontmatter 的笔记
grep(pattern="tags:.*中医", path="study", include="*.md", max_results=50)
```

### 3.2 templater_render 模板生成

**实现方式**：使用 `write_file` + 模板文件

### 3.3 obsidian_cli 命令行控制

**实现方式**：使用 `run_shell` 调用 Obsidian URI

```powershell
# 在 Obsidian 中打开特定笔记
Start-Process "obsidian://open?vault=study&file=丹道玄医录%2F00-索引%2F总索引.md"
```

### 3.4 obsidian_rest_api REST 接口

**实现方式**：使用 Obsidian Local REST API 插件（需安装）

---

## 四、即用工具脚本

已创建以下工具脚本，可直接通过 OpenKitsune `run_shell` 调用：

| 脚本 | 功能 | 调用方式 |
|------|------|----------|
| `vault_scan.py` | 扫描 Vault 所有文件 | `python tools/vault_scan.py` |
| `vault_search.py` | 全文搜索（支持标签、内容） | `python tools/vault_search.py` |
| `graph_scan.py` | 分析双链关系 | `python tools/graph_scan.py` |
| `dataview.py` | YAML 元数据查询 | `python tools/dataview.py` |
| `note_create.py` | 新建笔记 | `python tools/note_create.py` |
| `note_patch.py` | 局部编辑 | `python tools/note_patch.py` |
| `check_obsidian_plugins.py` | 检查插件状态 | `python tools/check_obsidian_plugins.py` |

---

## 五、快速开始

### 5.1 扫描知识库

```bash
python tools/vault_scan.py
```

### 5.2 搜索内容

```bash
python tools/vault_search.py --query "桂枝汤"
python tools/vault_search.py --tag "中医"
```

### 5.3 读取笔记

```bash
# 使用 OpenKitsune 原生 read_file 工具
read_file(path="study/丹道玄医录/00-索引/总索引.md")
```

### 5.4 编辑笔记

```bash
# 使用 OpenKitsune 原生 edit_file 工具
edit_file(
    path="study/丹道玄医录/00-索引/总索引.md",
    old_string="旧内容",
    new_string="新内容"
)
```

---

## 六、与 OpenKitsune 原生工具对比

| 需求 | Obsidian 工具 | OpenKitsune 工具 | 推荐 |
|------|--------------|------------------|------|
| 列出文件 | `vault_list` | `list_directory` + `glob` | OpenKitsune |
| 读取笔记 | `vault_read` | `read_file` | OpenKitsune |
| 全文搜索 | `vault_search` | `grep` | OpenKitsune |
| 图谱分析 | `graph_scan` | `grep` + Python 脚本 | 混合 |
| 新建笔记 | `note_write` | `write_file` | OpenKitsune |
| 局部编辑 | `note_patch` | `edit_file` | OpenKitsune |
| 移动文件 | `note_move` | `move_file` | OpenKitsune |
| 删除笔记 | `note_delete` | `delete_file` | OpenKitsune |
| 元数据查询 | `dataview_query` | `grep` + Python 脚本 | 混合 |
| 内部链接 | `graph_scan` | `grep` + Python 脚本 | 混合 |

**结论**：OpenKitsune 原生工具已覆盖 Obsidian 核心工具 80%+ 的功能，无需额外安装插件。
