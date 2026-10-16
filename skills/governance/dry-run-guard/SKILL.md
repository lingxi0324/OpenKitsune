---
name: dry-run-guard
description: 在执行文件修改、配置变更等写操作前，强制预览变更 diff，未确认不得写入。
---

# Dry Run Guard - Agent 变更预览保护工具

**ID**: dry_run_guard
**描述**: 在执行文件修改、配置变更等写操作前，强制预览变更 diff，未确认不得写入。
**类型**: 治理层工具

---

# Dry Run Guard - Agent 变更预览保护工具

## 核心功能

在执行任何**写操作**（文件修改、配置变更、代码编辑）前，自动预览变更内容（diff），展示**修改前 → 修改后**的对比，确保 Agent 和用户清楚知道将要修改什么。

## 保护范围

| 操作类型 | 保护级别 | 说明 |
|---------|---------|------|
| **文件修改** | 强制 dry-run | 必须预览后才能写入 |
| **配置变更** | 强制 dry-run | 必须预览后才能写入 |
| **代码编辑** | 强制 dry-run | 必须预览后才能写入 |
| **文件删除** | 强制 dry-run | 必须预览并确认 |
| **批量修改** | 强制 dry-run | 所有修改一起预览 |
| **简单查询** | 不保护 | read/grep/搜索不保护 |

## 预览格式

### 文件修改预览

```diff
--- config.yaml (修改前)
+++ config.yaml (修改后)
@@ -5,7 +5,7 @@
 database:
-  host: localhost
+  host: 192.168.1.100
   port: 5432
-  password: old_password
+  password: [REDACTED]
   timeout: 30
```

### 代码修改预览

```diff
--- src/user.py
+++ src/user.py
@@ -10,7 +10,10 @@
 def login(username, password):
-    if username == "admin":
+    if not username:
+        return False, "用户名不能为空"
+    if username == "admin":
         return True
-    return False
+    return False, "用户名不存在"
```

## 工作流

```
1. 准备修改
   - 生成修改内容
   - 计算 diff

2. dry_run_guard 预览
   - 展示 diff 对比
   - 标注风险点

3. 确认/拒绝
   - 用户确认 → 执行修改
   - 用户拒绝 → 取消修改
   - Agent 自动 → 高风险操作暂停

4. 执行修改
   - 执行实际写操作
   - 记录审计日志
```

## 风险标注

| 风险等级 | 标注 | 示例 |
|---------|------|------|
| **高风险** | 🔴 | 删除文件、修改系统配置 |
| **中风险** | 🟡 | 修改代码逻辑、修改数据库配置 |
| **低风险** | 🟢 | 添加注释、格式化代码 |

## 参数说明

- **operation_type**: 操作类型（file_edit/config_change/code_edit/file_delete）
- **target**: 操作目标（文件路径）
- **preview_content**: 预览内容（修改前后对比）
- **risk_level**: 风险等级（high/medium/low）
- **auto_approve**: 是否自动批准低风险操作（默认 false）
- **max_changes**: 单次预览最大变更行数（默认 100）

## 输出格式

```json
{
  "dry_run_id": "dryrun_20240101_120000_001",
  "timestamp": "2024-01-01T12:00:00",
  "operation_type": "file_edit",
  "target": "config/database.yaml",
  "risk_level": "high",
  "diff_preview": "--- config/database.yaml\n+++ config/database.yaml\n@@ -5,7 +5,7 @@\n-  host: localhost\n+  host: 192.168.1.100\n...",
  "changes_summary": {
    "files_modified": 1,
    "lines_added": 3,
    "lines_removed": 1,
    "risk_factors": ["数据库配置变更", "涉及生产环境"]
  },
  "approval_required": true,
  "recommendation": "confirm|reject|modify"
}
```

## 与相关工具的关系

- **edit_file** — 文件修改工具，dry_run 在其前执行
- **write_file** — 文件写入工具，dry_run 在其前执行
- **permission_gate** — 权限门禁，dry_run 是其中一部分
- **audit_log** — 记录 dry_run 结果
- **self_review** — 修改后自检确认

## 使用示例

```python
# 修改配置前预览
dry_run_guard(
    operation_type="config_change",
    target="config/database.yaml",
    preview_content="diff内容...",
    risk_level="high",
    auto_approve=False
)
# 返回预览结果
# 高风险，需要用户确认
# 确认后执行修改

# 添加注释（低风险，可自动批准）
dry_run_guard(
    operation_type="code_edit",
    target="src/user.py",
    preview_content="diff内容...",
    risk_level="low",
    auto_approve=True
)
# 低风险，自动批准
```

## 注意事项

- **强制预览** — 所有写操作必须经过 dry-run
- **风险标注** — 明确标注风险等级
- **批量修改** — 批量操作一起预览
- **脱敏处理** — 敏感信息自动脱敏
- **自动批准** — 低风险操作可设置自动批准
- **用户确认** — 高风险操作必须用户确认
- **审计记录** — dry_run 结果记录到审计日志
- **回退机制** — 预览后用户可取消操作
