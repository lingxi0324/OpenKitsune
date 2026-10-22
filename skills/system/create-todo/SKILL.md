---
name: create-todo
description: "MUST CALL FIRST for multi-step tasks! If user request needs 2+ tool calls (like 'open + search + screenshot'), call create_todo BEFORE any other tool."
system: true
handler: plan
tool-name: create_todo
category: Plan
---

# Create Todo

创建任务执行计划。多步骤任务必须先创建计划再执行。

## When to Use

- 任务需要超过 2 步完成时
- 用户请求中有"然后"、"接着"、"之后"等词
- 涉及多个工具协作

## Workflow

1. `create-todo` → 2. 执行步骤 → 3. `update-todo-step` → 4. ... → 5. `complete-todo`

## Parameters

| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| task_summary | string | 是 | 任务的一句话总结 |
| steps | array | 是 | 步骤列表 |

### Step Item

| 字段 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| id | string | 是 | 步骤 ID（如 step_1） |
| description | string | 是 | 步骤描述 |
| expected | string | 是* | 该步预期结果（代码门禁要求） |
| done_when | string | 是* | 可验证的完成判定标准（代码门禁要求） |
| tool | string | 否 | 预计使用的工具 |
| allow_tools | array | 否 | 该步允许的额外工具 |
| skills | array | 否 | 关联的 skill 名称列表（可选，用于追踪） |
| depends_on | array | 否 | 依赖的步骤 ID |

\* `process_rules_plan_guard_mode=enforce`（默认）时为必填；缺失会被
`plan_guard` 拒绝创建。

## Examples

**打开百度搜索天气并截图发给用户**:
```json
{
  "task_summary": "打开百度搜索天气并截图发送",
  "steps": [
    {"id": "step_1", "description": "打开百度", "tool": "browser_navigate",
     "expected": "百度首页可交互", "done_when": "页面标题包含『百度』"},
    {"id": "step_2", "description": "输入搜索关键词", "tool": "browser_type",
     "expected": "搜索框出现天气关键词", "done_when": "输入框 value 为『天气』",
     "depends_on": ["step_1"]},
    {"id": "step_3", "description": "截图", "tool": "browser_screenshot",
     "expected": "得到结果页截图", "done_when": "返回非空图片路径",
     "depends_on": ["step_2"]},
    {"id": "step_4", "description": "发送截图", "tool": "deliver_artifacts",
     "expected": "用户收到图片", "done_when": "发送工具返回成功",
     "depends_on": ["step_3"]}
  ]
}
```

## Related Skills

- `update-todo-step`: 更新步骤状态
- `get-todo-status`: 查看计划状态
- `complete-todo`: 完成计划

