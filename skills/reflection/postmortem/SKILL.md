---
name: postmortem
description: 对任务失败、回滚、异常事件进行结构化复盘，总结经验教训并更新记忆系统。
---

# Postmortem - Agent 事后复盘工具

**ID**: postmortem
**描述**: 对任务失败、回滚、异常事件进行结构化复盘，总结经验教训并更新记忆系统。
**类型**: 反思层工具

---

# Postmortem - Agent 事后复盘工具

## 核心功能

在任务失败、回滚、重大异常后，进行**结构化复盘**，分析根本原因、记录经验教训、更新记忆系统，避免同类问题重复发生。

## 复盘流程

```
1. 事件收集
   - 失败详情
   - 错误日志
   - 操作历史
   - 检查结果

2. 根因分析
   - root_cause 分析
   - 证据链收集
   - 因果链构建

3. 经验提取
   - 失败模式识别
   - 预防措施制定
   - 检查清单更新

4. 记忆更新
   - 写入 error 记忆
   - 写入 skill 记忆
   - 更新 decision_log

5. 报告生成
   - 复盘报告
   - 行动项
   - 预防措施
```

## 复盘报告结构

| 章节 | 内容 |
|------|------|
| **事件概述** | 时间、影响范围、严重程度 |
| **时间线** | 事件发生的完整时间线 |
| **根因分析** | 5Why 分析结果 |
| **影响评估** | 影响的用户/系统/数据 |
| **修复方案** | 短期修复 + 长期预防 |
| **经验教训** | 可复用的经验、检查清单 |
| **行动项** | 具体要做的改进项 |
| **记忆更新** | 更新了哪些记忆 |

## 参数说明

- **event_id**: 事件 ID（必填）
- **event_type**: 事件类型（test_failure/service_down/config_error/rollback/other）
- **description**: 事件描述（必填）
- **severity**: 严重程度（low/medium/high/critical，默认 medium）
- **evidence_sources**: 证据来源列表
- **update_memory**: 是否更新记忆（默认 true）

## 输出格式

```json
{
  "postmortem_id": "pm_20240101_120000_001",
  "event_id": "event_config_error_001",
  "timestamp": "2024-01-01T12:00:00",
  "event_type": "config_error",
  "severity": "high",
  "timeline": [
    {"time": "12:00", "event": "修改数据库配置"},
    {"time": "12:01", "event": "服务启动失败"},
    {"time": "12:02", "event": "执行回滚"},
    {"time": "12:03", "event": "服务恢复正常"}
  ],
  "root_cause": "配置语法错误，缺少必填字段",
  "impact": {
    "downtime_seconds": 120,
    "affected_users": "本地开发环境",
    "data_affected": false
  },
  "lessons_learned": [
    "配置修改前应检查语法",
    "重要配置应创建检查点",
    "添加配置验证脚本"
  ],
  "action_items": [
    {"item": "添加配置语法检查脚本", "owner": "Agent", "deadline": "2024-01-02"},
    {"item": "更新配置修改检查清单", "owner": "Agent", "deadline": "2024-01-02"}
  ],
  "memory_updates": {
    "error_memories_added": 2,
    "skill_memories_added": 1,
    "decision_logs_updated": 1
  },
  "recommendation": "implement_actions|monitor|close"
}
```

## 与相关工具的关系

- **root_cause** — 提供根因分析结果
- **evidence_verify** — 收集事件证据
- **rollback_apply** — 回滚操作记录
- **self_review** — 修复后验证
- **add_memory** — 更新记忆系统
- **decision_log** — 记录决策过程
- **audit_log** — 记录复盘操作

## 使用示例

```python
# 任务失败后复盘
postmortem(
    event_id="event_test_failure_001",
    event_type="test_failure",
    description="重构后单元测试失败 6/50",
    severity="high",
    evidence_sources=["test_output", "git_diff", "error_log"]
)
# 返回复盘报告
# 自动更新记忆
# 生成行动项

# 服务异常后复盘
postmortem(
    event_id="event_service_down_001",
    event_type="service_down",
    description="配置错误导致服务启动失败",
    severity="critical",
    update_memory=True
)
```

## 注意事项

- **及时复盘** — 事件发生后 24 小时内复盘
- **客观记录** — 基于事实，不主观臆断
- **经验提取** — 提炼可复用的经验
- **行动项** — 制定具体可执行的改进项
- **记忆更新** — 更新 error/skill 记忆
- **定期检查** — 定期回顾历史复盘，检查行动项完成
- **隐私保护** — 复盘报告脱敏处理
- **知识库** — 经验教训更新到知识库
