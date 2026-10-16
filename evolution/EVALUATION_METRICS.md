# EVALUATION_METRICS — 评估指标口径（V2.0 对齐）

> 对齐 V2.0 方案「评估指标」8 项 + 九尾复盘尾。标注采集点与当前状态。

## 指标清单与采集点

| # | 指标 | 口径 | 采集点 | 状态 |
|---|---|---|---|---|
| 1 | 意图识别准确率 | 意图评分与真实意图一致的比例 | skills 意图注入多维测试（D1 176/176） | ✅ 已实测 |
| 2 | 九维覆盖度 | 启用九尾议会时，覆盖尾数 / 9 | `turn_review.nine_tail_coverage` | 🔧 已接线（P2-2） |
| 3 | 用户满意度 | 用户显式正反馈/反馈评分的滚动均值 | feedback_store.py（feedback.db） | ✅ 已有 |
| 4 | 记忆召回率 | 记忆唤醒命中 / 应唤醒数 | memory 模块检索统计（待埋点） | 🔧 待埋点 |
| 5 | 人格一致性 | 人设自检分（是否像九尾狐，0-1） | `turn_review.persona_ok` | 🔧 已接线（P2-2） |
| 6 | 安全违规率 | 违规输出次数 / 总轮次 | prompts/core/safety.md + 审核记录 | 🔧 待埋点 |
| 7 | 决策有效性 | DecisionPath 推荐方案的事后命中率 | data/plans 复盘比对 | 🔧 待埋点（P3） |
| 8 | 长期迭代提升率 | confidence_history 序列的趋势斜率 | evolution/confidence_history.json | ✅ 有数据（玄学域待实测） |

## 能力域验证状态（P2-3 已执行）

`evolution/capability_domains.json` 已加 `validation_status` 字段：

- `validated`：有实测答案（搜索检索 120 答、系统工具 500 答、中医 15 答）
- `unverified`：无实测（含全部玄学/认知域：中医丹道、道家修行、AI与ML 等）

**约定**：`unverified` 的域在对外陈述能力时必须显式标注「未验证」，不得以 confidence=0.5 默认值冒充实测；实测后由 `validate_capability_status.py` 重跑升级为 `validated`。

## 接入方式

- 每轮对话六问（意图/九维/情绪/落地/人设/满意）→ `openkitsune.evolution.turn_review.record_turn_review()`；
- 每日汇总 → `self_check.py` 读取 retrospects 自动并入 DailyReport；
- 玄学域实测 → 由验卦闭环（未来）产出 correct_answers 后重跑标记脚本。
