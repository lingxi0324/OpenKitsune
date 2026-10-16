---
name: risk-assess
description: 在执行变更前评估操作的影响面、回滚难度、安全风险，为决策提供依据。
---

# Risk Assess - Agent 风险评估工具

**ID**: risk_assess
**描述**: 在执行变更前评估操作的影响面、回滚难度、安全风险，为决策提供依据。
**类型**: 反思层工具

---

# Risk Assessment - Agent 风险评估工具

## 核心功能

在执行**高风险操作**（文件删除、配置修改、依赖升级、服务重启）前，自动评估操作的风险等级、影响范围、回滚难度，为决策提供数据支持。

## 评估维度

| 维度 | 评估内容 | 权重 |
|------|---------|------|
| **影响面** | 影响多少文件/用户/服务 | 30% |
| **回滚难度** | 失败后能否快速回滚 | 25% |
| **安全风险** | 是否引入安全漏洞 | 20% |
| **数据风险** | 是否影响数据完整性 | 15% |
| **时间成本** | 修复需要多少时间 | 10% |

## 风险等级

| 等级 | 颜色 | 分数 | 行动 |
|------|------|------|------|
| **低风险** | 🟢 | 0-30 | 可执行，记录日志 |
| **中风险** | 🟡 | 31-60 | 建议 dry-run + 检查点 |
| **高风险** | 🟠 | 61-80 | 必须检查点 + 人工确认 |
| **极高风险** | 🔴 | 81-100 | 建议暂停，人工审查 |

## 评估流程

```
1. 操作分析
   - 操作类型
   - 影响文件/配置
   - 依赖关系

2. 影响面评估
   - 文件数量
   - 用户影响
   - 服务影响

3. 回滚评估
   - 是否有检查点
   - 回滚复杂度
   - 回滚时间

4. 安全评估
   - 权限变更
   - 数据暴露
   - 漏洞引入

5. 综合评分
   - 加权计算
   - 风险等级
   - 建议行动
```

## 参数说明

- **operation_type**: 操作类型（file_delete/config_change/dependency_update/service_restart/code_refactor）
- **target**: 操作目标
- **files_affected**: 影响文件列表
- **has_checkpoint**: 是否有检查点（默认 false）
- **requires_approval**: 是否需要人工审批（默认 true）

## 输出格式

```json
{
  "risk_id": "risk_20240101_120000_001",
  "timestamp": "2024-01-01T12:00:00",
  "operation": "dependency_update",
  "target": "flask==2.0.0",
  "assessment": {
    "impact": {
      "score": 65,
      "level": "high",
      "details": "影响 15 个文件，3 个服务需要重启"
    },
    "rollback": {
      "score": 70,
      "level": "high",
      "details": "无检查点，需要手动回滚依赖版本"
    },
    "security": {
      "score": 40,
      "level": "medium",
      "details": "Flask 2.0 有安全更新，但可能引入 breaking changes"
    },
    "data": {
      "score": 20,
      "level": "low",
      "details": "不涉及数据变更"
    },
    "time": {
      "score": 50,
      "level": "medium",
      "details": "修复预计需要 2-4 小时"
    }
  },
  "total_score": 59,
  "risk_level": "medium",
  "recommendations": [
    "创建检查点后再执行",
    "在测试环境先验证",
    "准备回滚脚本"
  ],
  "approval_required": true,
  "can_proceed": false
}
```

## 与相关工具的关系

- **checkpoint_create** — 高风险操作前创建检查点
- **dry_run_guard** — 预览变更内容
- **permission_gate** — 权限门禁
- **self_review** — 操作后自检
- **decision_log** — 记录决策依据

## 使用示例

```python
# 依赖更新前评估
risk_assess(
    operation_type="dependency_update",
    target="flask==2.0.0",
    files_affected=["requirements.txt", "src/app.py"],
    has_checkpoint=False
)
# 返回风险评估
# 中风险，建议创建检查点
# 确认后执行

# 文件删除前评估
risk_assess(
    operation_type="file_delete",
    target="temp/old_data/",
    has_checkpoint=True
)
# 返回风险评估
# 高风险，必须人工确认
```

## 注意事项

- **操作前评估** — 所有高风险操作必须评估
- **检查点优先** — 高风险操作先创建检查点
- **人工确认** — 高风险操作需要人工审批
- **记录日志** — 评估结果记录到审计日志
- **定期回顾** — 定期回顾风险评估准确性
- **阈值调整** — 根据项目调整风险阈值
- **安全优先** — 安全风险评估优先
