---
name: tcm-dual-track
description: 中医三观四证·内伤外感双规辨证引擎 — 津液/表里/正邪三观，水/火/气/血四证，六经开路与五脏填补
category: 中医玄学
exposure_level: core
when-to-use: 症状复杂、虚实难辨，需要先定表里寒热虚实津血气机，或判断能否直接补益、如何先开六经后补五脏时使用。
keywords: [三观四证, 内伤外感, 双规辨证, 六经开路, 五脏填补, 津液观, 表里观, 正邪观, 水证, 火证, 气证, 血证]
argument-hint: "口苦 胸胁满 纳差 乏力 --pulse 脉弦 --tongue 舌淡苔白"
arguments:
  - name: symptoms
    type: string
    required: true
    description: 症状描述（可多个词）
  - name: --pulse
    type: string
    required: false
    description: 脉象
  - name: --tongue
    type: string
    required: false
    description: 舌象
  - name: --json
    type: bool
    required: false
    description: JSON 输出
metadata:
  author: OpenKitsune
  version: "1.0.0"
  type: decision-engine
---

# 中医三观四证 · 内伤外感双规辨证引擎

把两条辨证主线合成一个可执行流程：

1. **三观四证**（许家栋金匮病机体系）：津液观、表里观、正邪观；水证、火证、气证、血证。
2. **内伤外感双规**：先以六经开路调气机，再以五脏填补补精血。

> 核心公式：**以六经调阴阳，以五脏补气血；先通后补，双规并重。**

## 何时使用

- 症状复杂、虚实难辨，需要先定「表里—寒热—虚实—津血—气机」五步
- 需要判断「见虚能不能直接补」，避免越补越堵
- 需要把辨证结论落到开路方、填补方与针法

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="tcm-dual-track",
  script_name="scripts/tcm_dual_track.py",
  args=["--pulse", "脉弦", "--tongue", "舌淡苔白",
        "口苦", "胸胁满", "纳差", "乏力", "便溏"]
)
```

## 用法

```bash
python scripts/tcm_dual_track.py "口苦 胸胁满 纳差 乏力 失眠"
python scripts/tcm_dual_track.py --tongue "舌淡苔白腻" --pulse "脉沉弦" "腹胀 便溏 畏寒"
python scripts/tcm_dual_track.py --json "发热 恶寒 无汗 身痛"
```

## Python API

```python
from tcm_dual_track import DualTrackEngine

engine = DualTrackEngine()
report = engine.analyze("口苦 胸胁满 纳差 乏力", pulse="脉弦", tongue="舌淡苔白")
print(report["three_views"])
print(report["four_syndromes"])
print(report["dual_track"]["open_road"])
```

## 输出结构

| 字段 | 内容 |
|:----|:-----|
| `three_views` | 津液观、表里观、正邪观定位 |
| `differentiation_steps` | 病机约分五步：表里→寒热→虚实→津血→气机 |
| `four_syndromes` | 水/火/气/血四证及亚型 |
| `six_channels` | 六经评分与开路方 |
| `organs` | 五脏虚损评分与填补方 |
| `dual_track` | 先开六经、后补五脏的次序方案 |
| `acupuncture` | 开路/填补/收功配穴 |
| `cautions` | 误补、过汗、开路过久等禁忌 |

## 技能协同

| 技能 | 衔接 |
|:----|:-----|
| `qimen-diagnosis` | 奇门定病宫/病势，本引擎定三观四证与开路/填补次序 |
| `zhenfa-jiugong` | 六经开路穴 + 五脏填补穴 + 水火收功阵 |
| `nongli-paipan` | 统一节气与四柱口径 |

## 边界

- 本引擎是传统辨证知识的结构化辅助，不替代执业中医师的四诊合参与处方权。
- 方药剂量、煎服法与加减必须由医师根据个体情况决定。
- 急危重症、出血、意识障碍、持续高热等应优先现代医学处置。
