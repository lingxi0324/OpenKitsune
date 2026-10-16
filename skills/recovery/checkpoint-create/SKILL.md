---
name: checkpoint-create
description: 在执行高风险操作前，自动创建文件/配置/Git 状态的快照检查点，为回滚提供基础。
---

# Checkpoint - Agent 检查点创建工具

**ID**: checkpoint_create
**描述**: 在执行高风险操作前，自动创建文件/配置/Git 状态的快照检查点，为回滚提供基础。
**类型**: 恢复层工具

---

# Checkpoint Create - Agent 检查点创建工具

## 核心功能

在执行文件修改、配置变更、代码重构等**高风险操作前**，自动创建检查点快照。检查点包括文件内容、Git 状态、配置快照，确保失败时可快速回滚。

## 检查点内容

| 检查点类型 | 内容 | 示例 |
|-----------|------|------|
| **文件快照** | 修改前文件完整内容 | `config.yaml` 原始内容 |
| **Git 快照** | git status、当前分支、未提交变更 | git diff 输出 |
| **配置快照** | 关键配置文件备份 | `.env`、`settings.json` |
| **依赖快照** | 当前依赖版本列表 | pip freeze、package-lock.json |
| **进程快照** | 运行中的服务状态 | 端口占用、PID 列表 |

## 使用场景

- **文件修改前** — 修改重要配置/代码前创建
- **代码重构前** — 大规模重构前创建
- **依赖更新前** — 安装/卸载/升级依赖前创建
- **服务重启前** — 重启关键服务前创建
- **手动执行前** — 高风险手动操作前创建

## 检查点命名

采用时间戳 + 描述格式：`checkpoint_YYYYMMDD_HHMMSS_描述`

示例：
- `checkpoint_20240101_120000_config_backup`
- `checkpoint_20240101_140000_refactor_main`
- `checkpoint_20240101_160000_dependency_update`

## 快照存储

检查点存储在固定目录，保持最新 10 个检查点：

```
data/checkpoints/
├── checkpoint_20240101_120000_config_backup/
│   ├── files/
│   │   ├── config.yaml
│   │   ├── settings.json
│   │   └── ...
│   ├── git_snapshot.txt
│   ├── dependencies.txt
│   └── manifest.json
├── checkpoint_20240101_140000_refactor_main/
│   └── ...
```

## 参数说明

- **description**: 检查点描述（必填）
- **files**: 需要快照的文件列表（可选，默认检测 git diff）
- **include_git**: 是否包含 Git 状态快照（默认 true）
- **include_dependencies**: 是否包含依赖快照（默认 true）
- **max_checkpoints**: 保留的最大检查点数（默认 10）

## 输出格式

```json
{
  "checkpoint_id": "checkpoint_20240101_120000_config_backup",
  "timestamp": "2024-01-01T12:00:00",
  "description": "配置备份",
  "files_snapshot": [
    {
      "path": "config.yaml",
      "original_hash": "sha256:abc123...",
      "snapshot_path": "data/checkpoints/.../files/config.yaml"
    }
  ],
  "git_snapshot": {
    "branch": "main",
    "status": "clean|modified",
    "diff_path": "data/checkpoints/.../git_snapshot.txt"
  },
  "dependencies_snapshot": {
    "path": "data/checkpoints/.../dependencies.txt"
  },
  "storage_path": "data/checkpoints/checkpoint_20240101_120000_config_backup/",
  "rollback_command": "rollback_apply(checkpoint_id='checkpoint_20240101_120000_config_backup')"
}
```

## 与相关工具的关系

- **rollback_apply** — 检查点的主要消费者，执行回滚
- **file_restore** — 恢复单个文件
- **git_revert** — 通过 Git 回退
- **snapshot_manage** — 管理检查点列表、清理旧快照
- **audit_log** — 记录检查点创建和操作

## 使用示例

```python
# 示例 1：修改配置前创建检查点
checkpoint_create(
    description="修改数据库配置前备份",
    files=["config/database.yaml", ".env"],
    include_git=True
)
# 返回检查点 ID
# 执行配置修改
# 如果失败，使用 rollback_apply 回滚

# 示例 2：代码重构前创建检查点
checkpoint_create(
    description="重构用户模块前备份",
    files=["src/user.py", "src/user_test.py"],
    include_git=True,
    include_dependencies=True
)
# 返回检查点 ID
# 执行重构
# 验证通过后，检查点自动归档

# 示例 3：依赖更新前创建检查点
checkpoint_create(
    description="升级 Flask 依赖前备份",
    include_git=True,
    include_dependencies=True
)
# 返回检查点 ID
# 执行 pip install flask==2.0.0
# 如果测试失败，回滚到检查点
```

## 注意事项

- 检查点创建应在**操作前**立即执行
- 重要操作建议手动创建检查点
- 检查点目录应定期清理（保留最近 10 个）
- Git 快照应在 clean 状态下创建
- 检查点不替代版本控制，仅作为快速回滚机制
- 大文件快照注意磁盘空间
- 检查点创建失败不应阻止后续操作（仅警告）
