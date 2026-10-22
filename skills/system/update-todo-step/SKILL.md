---
name: update-todo-step
description: Update the status of a plan step. MUST call after completing each step to track progress. Status values - pending, in_progress, completed, failed, skipped.
system: true
handler: plan
tool-name: update_todo_step
category: Plan
---

# Update Todo Step

更新计划中某个步骤的状态。每完成一步必须调用。

## Parameters

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| step_id | string | 是 | 步骤 ID |
| status | string | 是 | pending / in_progress / completed / failed / skipped |
| result | string | 完成/失败时必填 | 证据，格式：`actual=<摘要> \| verdict=PASS\|FAIL\|DEVIATE` |

## Examples

**步骤完成（带自检证据）**:
```json
{
  "step_id": "step_1",
  "status": "completed",
  "result": "actual=百度首页标题为『百度一下』 | verdict=PASS"
}
```

**步骤失败**:
```json
{
  "step_id": "step_2",
  "status": "failed",
  "result": "actual=未找到搜索框元素（selector 超时 10s） | verdict=FAIL"
}
```

> 标记 completed/failed 但 `result` 缺少 `actual=` 或 `verdict=` 时，
> `plan_guard` 会拒绝更新，步骤状态不会推进。

## Related Skills

- `create-todo`: 创建计划
- `get-todo-status`: 查看计划状态
- `complete-todo`: 完成计划

