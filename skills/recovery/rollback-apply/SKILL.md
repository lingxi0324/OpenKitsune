---
name: rollback-apply
description: 根据检查点快照恢复文件/配置/Git 状态，是检查点机制的核心回滚工具。
---

# Rollback Apply - Agent 回滚应用工具

**ID**: rollback_apply
**描述**: 根据检查点快照恢复文件/配置/Git 状态，是检查点机制的核心回滚工具。
**类型**: 恢复层工具

---

# Rollback Apply - Agent 回滚应用工具

## 核心功能

根据之前创建的检查点快照，**恢复文件、配置、Git 状态**到检查点时刻的状态。支持文件级、配置级、Git 级回滚。

## 回滚级别

| 回滚级别 | 范围 | 示例 |
|---------|------|------|
| **文件回滚** | 恢复指定文件到检查点状态 | `config.yaml` → 检查点版本 |
| **配置回滚** | 恢复所有配置到检查点状态 | `.env`、`settings.json` → 检查点版本 |
| **Git 回滚** | 恢复 Git 工作区到检查点状态 | git reset --hard 到检查点提交 |
| **完整回滚** | 文件 + 配置 + Git 全部恢复 | 完整恢复到检查点时刻 |

## 使用场景

- **修改失败后** — 文件修改导致错误，立即回滚
- **测试不通过** — 重构后测试失败，回滚到重构前
- **依赖冲突** — 依赖更新导致问题，回滚到旧版本
- **服务异常** — 配置变更导致服务异常，回滚配置
- **手动纠正** — 手动操作失误，回滚到检查点

## 回滚流程

```
1. 确认检查点
   - checkpoint_create 已创建检查点
   - checkpoint_id 可用

2. 执行回滚
   - rollback_apply(checkpoint_id=xxx)
   - 恢复文件内容
   - 恢复 Git 状态

3. 验证回滚
   - 检查文件是否恢复
   - 检查服务是否正常
   - 重新测试

4. 记录审计
   - 记录回滚操作
   - 记录回滚原因
```

## 参数说明

- **checkpoint_id**: 检查点 ID（必填）
- **rollback_type**: 回滚类型（file/config/git/complete，默认 complete）
- **force**: 是否强制回滚（覆盖当前文件，默认 false）
- **dry_run**: 仅预览不回滚（默认 false）
- **reason**: 回滚原因说明

## 输出格式

```json
{
  "rollback_id": "rollback_20240101_120000_001",
  "checkpoint_id": "checkpoint_20240101_120000_config_backup",
  "timestamp": "2024-01-01T12:05:00",
  "rollback_type": "complete",
  "reason": "配置修改导致服务启动失败",
  "files_restored": [
    {
      "path": "config.yaml",
      "original_hash": "sha256:abc123...",
      "restored_hash": "sha256:def456...",
      "status": "success"
    }
  ],
  "git_restored": true,
  "verification": {
    "file_check": "pass",
    "service_check": "pending",
    "test_check": "pending"
  },
  "warnings": [
    "Git 工作区有未提交变更，已备份到 .backup/"
  ]
}
```

## 与相关工具的关系

- **checkpoint_create** — 回滚依赖检查点存在
- **file_restore** — 回滚单个文件时调用
- **git_revert** — Git 级回滚时调用
- **self_review** — 回滚后验证是否恢复正常
- **root_cause** — 分析回滚原因
- **postmortem** — 复盘回滚事件
- **audit_log** — 记录回滚操作

## 使用示例

```python
# 示例 1：配置修改失败，回滚配置
rollback_apply(
    checkpoint_id="checkpoint_20240101_120000_config_backup",
    rollback_type="config",
    reason="数据库配置修改导致连接失败"
)
# 恢复 .env 和 config/database.yaml

# 示例 2：代码重构失败，完整回滚
rollback_apply(
    checkpoint_id="checkpoint_20240101_140000_refactor_main",
    rollback_type="complete",
    force=True,
    reason="重构后单元测试失败 15/50"
)
# 恢复文件 + Git 状态

# 示例 3：仅预览不回滚
rollback_apply(
    checkpoint_id="checkpoint_20240101_160000_dependency_update",
    rollback_type="complete",
    dry_run=True
)
# 输出预览：将恢复 3 个文件，回滚 2 个提交
```

## 注意事项

- **高风险操作** — 回滚会覆盖当前文件，需确认
- **优先使用检查点** — 没有检查点无法回滚
- **回滚后验证** — 必须验证服务/测试是否恢复正常
- **未提交变更** — 回滚前备份未提交变更
- **Git 回滚** — git reset --hard 会丢失未提交变更
- **审计记录** — 所有回滚操作记录到审计日志
- **定期清理** — 旧检查点应定期清理，释放磁盘空间
- **权限要求** — 回滚需要文件写权限
