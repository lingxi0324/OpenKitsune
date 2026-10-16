---
name: nine-palace-reasoning
description: 九宫并行推演引擎 v2.0 — 八宫Agent并行推演 + 五行生克博弈 + 心智故障自检 + 中宫收敛整合
author: lingxi
version: 2.0.0
type: skill
system: true
handler: persona
tool-name: nine_palace_reasoning
execution-context: fork
category: nine-palace-reasoning-pipeline
exposure_level: core
when-to-use: |
  当需要多视角并行辨证、病案分析、推演问题时使用。
  完整三阶段架构：

  第一阶段（已就绪）：八宫Agent并行推演 + 中宫收敛
  第二阶段（触发条件）：当推演累积>30次后自动启用记忆分域
  第三阶段（已就绪）：五行生克权重制衡 + 心智故障自检 + 场景靶向调控

  **适用场景**：
  - 中医病案分析（六经辨证、方药配伍）
  - 玄学推演（奇门、八字）
  - 复杂决策问题（需要多角度审视）
  - 情志/身心问题（需要共情+精准+全局多维度）
metadata:
  openkitsune:
    python:
      venv: agent
      dependencies: []
    category: tcm
    tags: [nine-palace, parallel-reasoning, tcm, delegation, phase-3, fault-diagnosis, balance-mechanism]
---

scripts:
  init_nine_palace.py: Phase 3 集成版 — 生成委派任务 + 整合框架（含场景感知）
  palace_weights.py: Phase 3 核心 — 五行生克博弈 + 场景靶向调控
  fault_diagnosis.py: Phase 3 核心 — 心智紊乱自检 + 优雅降级

usage: |
  1. 灵汐接收用户问题（推演/辨证/决策）
  2. 在回复前执行 `run_skill_script("nine-palace-reasoning", "init_nine_palace.py", {"query": "..."})`
  3. 脚本返回并行委派任务 + 当前九要素快照 + 场景标签 + 制衡参数
  4. 用 delegate_parallel 发送8个任务（每次最多5个，分两批）
  5. 八宫结果回传后：
     a. 构建冲突矩阵（fault_diagnosis.build_conflict_matrix）
     b. 五行生克博弈（palace_weights.balance_weights_battle）
     c. 心智自检（fault_diagnosis.FaultDiagnosis.diagnose）
  6. 按博弈后的动态权重整合输出最终结论

architecture: |
  ┌─────────────────────────────────────────────────────────────────┐
  │                        中宫·灵汐                               │
  │        (冲突对比 + 五行博弈 + 心智自检 + 最终输出)              │
  └────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬────────┘
       │      │      │      │      │      │      │      │
    震魂   离神   坤情   坎精   艮志   巽性   乾气   兑魄
    木     火     土     水     土     木     金     金
   万象   慧眼   善应   墨阁   天机   知言   天书   灵文

  **三阶段联动**：
  Phase 1（基础）：八视角并行 + 九要素权重
  Phase 2（待感知触发）：记忆分域休眠
  Phase 3（已就绪）：五行生克博弈 + 心智自检 + 场景靶向

  **Phase 3 核心能力**：
  ① 五行生克相生（木→火→土→金→水→木）— 结论一致的相生宫互相增益
  ② 五行相克（木→土→水→火→金→木）— 结论对立的相克宫互相压制
  ③ 心智自检：检测决策内耗/局部缺损/感知失真，优雅降级
  ④ 场景靶向：急救→离神优先；情志→坤情优先；考证→坎精优先

deliverable: |
  `心智快照：震52 乾51 巽51 离38 | 场景：辨证 | 心智诊断：normal | 八宫并行推演整合`
