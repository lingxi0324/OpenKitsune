---
name: plan-discipline
description: 多步任务的计划执行纪律。当任务需要 2 步以上、涉及写文件/删除/发送消息/权限变更、或用户要求"先出方案再执行"时使用。提供固定格式的 PLAN 块、逐步 STEP-CHECK 自检块与确定性进度汇报模板。
---

# Plan Discipline —— 计划执行纪律

**定位**：本文是模型侧的软约束（提示词层）。服务端另有 `process_rules.plan_guard`
代码 Hook 层做硬门禁；两者使用同一套字段与自检口径，避免模型"说一套、做一套"。

## 何时使用

命中任一条件即启用：

- 任务需要 2 个以上工具步骤；
- 涉及不可逆/外部副作用（删除、覆盖、发送消息、发布、付款、权限变更）；
- 用户说"先出方案/先给计划/plan first"；
- 首次执行的陌生长流程。

单步问答（"现在几点"）不启用。

## 铁律

1. **先有 PLAN，后有工具**：计划必须先落成下方固定格式，才能执行第一步。
2. **一次只推进一个步骤**：任意时刻只有一个 `in_progress` 步骤。
3. **无证据不算完成**：每步结束必须写 `STEP-CHECK`，并把同一口径写进
   `update_todo_step` 的 `result`；没有 `verdict=` 的完成一律视为未完成。
4. **进度只从状态机读**：汇报进度必须调用 `get_todo_status` 或读取计划块，
   禁止凭记忆复述。
5. **偏离先改计划**：工具/结果与计划不符时，先 `update_todo_step` 或重写计划，
   再继续执行；不允许"先做了再说"。

---

## 一、PLAN 固定块

创建计划时（`create_todo`）按此结构产出，并在回复中展示同一份内容：

```markdown
## PLAN v1
goal: <一句话目标，可验证>
constraints: <时间/权限/不可逆边界；无则写 none>
risk: <none | irreversible | external | permission | user_requested | first_time>

| id | action | tool | expected | done_when | risk |
|----|--------|------|----------|-----------|------|
| step_1 | <动作> | <工具> | <预期结果> | <可验证判定> | none |
| step_2 | <动作> | <工具> | <预期结果> | <可验证判定> | none |
```

字段要求：

- `expected`：这一步"应该看到什么"，用于事后对照；
- `done_when`：可执行/可观察的判定，例如"命令退出码为 0"、"页面包含目标标题"；
- `tool`：该步的主工具；需要多工具时写 `allow_tools`；
- 步骤数控制在 2–8 条；超过 8 条必须合并或分层。

对应工具调用：

```json
create_todo(
  task_summary="...",
  steps=[
    {"id":"step_1","description":"...","tool":"read_file",
     "expected":"拿到配置内容","done_when":"文件存在且包含 database 段"},
    {"id":"step_2","description":"...","tool":"edit_file",
     "expected":"配置改为新地址","done_when":"diff 仅一行变化且语法校验通过"}
  ]
)
```

---

## 二、逐步执行循环（每步四拍）

```text
1) 复述：当前步骤 step_N「action」；预期 expected；完成标准 done_when
2) 执行：调用该步声明的工具（不夹带计划外副作用）
3) 自检：对照工具返回写 STEP-CHECK
4) 落库：update_todo_step(step_id, status, result="<与 STEP-CHECK 同口径>")
```

### STEP-CHECK 固定格式

```text
STEP-CHECK step_2: actual=<证据摘要，≤120字> | verdict=PASS|FAIL|DEVIATE
```

- `PASS`：结果满足 `done_when`；
- `FAIL`：执行失败或结果不符合预期；
- `DEVIATE`：结果与计划假设不一致（例如页面结构变了、接口字段缺失）。

落库示例：

```json
update_todo_step(
  step_id="step_2",
  status="completed",
  result="actual=nginx -t 返回 syntax is ok | verdict=PASS"
)
```

判定与状态必须一致：`verdict=FAIL/DEVIATE` 时用 `status="failed"`；
`verdict=PASS` 时才用 `status="completed"`。

---

## 三、偏离处理

| 现象 | 判定 | 动作 |
|------|------|------|
| 工具返回空/类型不符/异常码 | DEVIATE | 先记录证据；同一步最多重试 2 次 |
| 同类错误累计 3 次 | 共性成因 | 停止重试，回到计划层查共同原因 |
| 必须换工具才能继续 | 计划偏离 | 先改计划（重写步骤/换 tool），再执行 |
| 用户改需求 | 计划失效 | 重写 PLAN，废弃旧步骤并说明原因 |
| 高风险动作前（删除/对外发送） | 检查点 | 先向用户确认，再执行 |

---

## 四、进度汇报模板（确定性）

数据源优先级：`get_todo_status()` > 计划块原文 > 记忆。

```markdown
📊 计划进度：<done>/<total>（<percent>%）
✅ 已完成：step_1 <一句话结果>
🔄 进行中：step_2 <当前动作>
⬜ 待执行：step_3, step_4
⚠️ 风险/阻塞：<无 或 具体项>
```

要求：

- 数字必须来自状态机，不能自行估算；
- 未完成时禁止使用"已完成/全部完成/搞定了"等完成口径；
- 有停滞步骤（长时间 `in_progress`）时主动说明原因与下一步。

---

## 五、完成口径

只有同时满足以下条件才能宣告任务完成：

1. 所有步骤状态为 `completed` / `skipped`（skip 必须写明原因）；
2. 每个 `completed` 步骤的 `result` 都含 `actual=` 与 `verdict=PASS`；
3. 最终回复列出关键证据（命令输出、文件 diff、页面标题等）。

否则必须如实汇报：完成了哪些、剩余哪些、卡在哪里。

---

## 六、与代码层的关系

| 约束 | SKILL.md（软） | plan_guard（硬） |
|------|----------------|------------------|
| 固定计划结构 | 模板引导 | `create_todo` 缺 `expected/done_when` 直接拒绝 |
| 步骤绑定 | 提示先置 in_progress | 无活动步骤时阻断有副作用工具 |
| 显式自检 | 要求写 STEP-CHECK | `result` 缺 `actual=/verdict=` 拒绝完成 |
| 进度汇报 | 提供模板 | 轮末由代码生成进度并检测假完成 |

配置项：`process_rules_plan_guard_mode = off | observe | enforce`（默认 `enforce`）。
历史非结构化计划会自动降级为 `observe`，只提示不阻断。
