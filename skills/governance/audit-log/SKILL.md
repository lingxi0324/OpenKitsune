---
name: audit-log
description: 记录 Agent 所有关键操作到审计日志，支持操作查询、统计分析、合规检查。
---

# Audit Log - Agent 审计日志工具

**ID**: audit_log
**描述**: 记录 Agent 所有关键操作到审计日志，支持操作查询、统计分析、合规检查。
**类型**: 治理层工具

---

# Audit Log - Agent 审计日志工具

## 核心功能

**不可关闭**的操作审计系统。记录 Agent 执行的每个关键操作：时间、操作类型、工具、参数（脱敏）、结果、状态。提供查询、统计、合规检查能力。

## 记录内容

| 字段 | 说明 | 示例 |
|------|------|------|
| **timestamp** | 操作时间 | 2024-01-01T12:00:00 |
| **operation** | 操作类型 | file_edit/test_run/rollback |
| **tool** | 使用的工具 | edit_file/pytest/git reset |
| **target** | 操作目标 | src/user.py/tests/ |
| **params** | 操作参数（脱敏） | {"path": "config.yaml"} |
| **result** | 操作结果 | success/failure |
| **user** | 操作用户 | agent/desktop_user |
| **session** | 会话 ID | session_abc123 |
| **trace_id** | 追踪 ID | trace_xyz789 |

## 审计日志存储

```
data/audit_logs/
├── audit_2024-01-01.jsonl
├── audit_2024-01-02.jsonl
└── ...
```

每个日志行是 JSON 格式（JSONL），支持按日期查询。

## 敏感信息脱敏

自动脱敏以下敏感字段：
- API Keys / Tokens
- Passwords
- Private Keys
- Credit Card Numbers
- Personal Identifiable Information (PII)

脱敏规则：`sk-xxxxx` → `sk-xxx[REDACTED]`

## 记录的操作类型

### 必须记录
- 文件修改（write/patch/delete）
- 配置变更
- 代码执行（exec_python/exec_shell）
- 回滚操作
- 依赖安装/卸载
- 服务控制
- 记忆写入
- 权限变更

### 可选记录
- 文件读取
- 搜索查询
- 网络请求
- 简单查询操作

## 参数说明

- **operation**: 操作类型（必填）
- **tool**: 使用的工具名
- **target**: 操作目标（文件/服务/配置）
- **params**: 操作参数（自动脱敏）
- **result**: 操作结果
- **session**: 会话 ID（自动获取）
- **trace_id**: 追踪 ID（自动生成）
- **record_level**: 记录级别（mandatory/voluntary，默认 mandatory）

## 查询功能

| 查询类型 | 参数 | 示例 |
|---------|------|------|
| 按日期查询 | date=2024-01-01 | 查询当天日志 |
| 按操作查询 | operation=file_edit | 查询文件编辑操作 |
| 按工具查询 | tool=edit_file | 查询 edit_file 操作 |
| 按结果查询 | result=failure | 查询失败操作 |
| 按会话查询 | session=abc123 | 查询特定会话 |
| 时间范围查询 | start_date/end_date | 查询时间范围 |

## 输出格式

```json
{
  "audit_id": "audit_20240101_120000_001",
  "timestamp": "2024-01-01T12:00:00",
  "operation": "file_edit",
  "tool": "edit_file",
  "target": "config/database.yaml",
  "params": {"path": "config/database.yaml", "old_string": "host: localhost", "new_string": "host: [REDACTED]"},
  "result": "success",
  "user": "agent",
  "session": "session_abc123",
  "trace_id": "trace_xyz789",
  "recorded": true
}
```

## 与相关工具的关系

- **permission_gate** — 权限门禁记录
- **rollback_apply** — 回滚操作记录
- **postmortem** — 复盘时查询审计日志
- **secret_redact** — 日志脱敏
- **self_review** — 自检时检查审计日志

## 使用示例

```python
# 自动记录（大多数操作自动记录）
# 无需手动调用

# 手动记录特殊操作
audit_log(
    operation="config_change",
    tool="yaml_edit",
    target="config/secrets.yaml",
    params={"key": "api_key", "value": "sk-xxx"},
    result="success"
)

# 查询审计日志
audit_query(
    date="2024-01-01",
    operation="file_edit",
    result="failure"
)
# 返回当天失败的 file_edit 操作

# 统计操作
audit_stats(
    start_date="2024-01-01",
    end_date="2024-01-07"
)
# 返回本周操作统计
```

## 注意事项

- **不可关闭** — 审计日志不可禁用
- **自动脱敏** — 敏感信息自动脱敏
- **日志轮转** — 按日期轮转，定期清理旧日志
- **查询性能** — 大量日志时考虑索引
- **合规要求** — 满足审计合规要求
- **权限控制** — 审计日志只读，不可修改
- **完整性** — 关键操作必须记录
- **追溯性** — 支持操作追溯
