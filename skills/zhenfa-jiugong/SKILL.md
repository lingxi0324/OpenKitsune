---
name: zhenfa-jiugong
description: 北斗七星与九宫飞星针法引擎 — 十二命宫×十二时辰三才针阵、九宫配穴、四时变阵与禁忌校验
category: 中医玄学
exposure_level: core
when-to-use: 需要按出生时辰与施针时辰生成针阵、按症状落九宫取穴、做四时变阵或九宫飞星择时时使用。
keywords: [北斗七星, 九宫飞星, 针法, 针灸, 十二命宫, 三才针阵, 九宫配穴, 四时变阵, 飞星]
argument-hint: "--birth-hour 子 --treat-hour 辰 --symptoms 失眠 --syndrome 太阴病 --year 2026 --month 10"
arguments:
  - name: --birth-hour
    type: string
    required: false
    description: 出生时辰（0-23 或 子..亥）
  - name: --treat-hour
    type: string
    required: false
    description: 施针时辰（0-23 或 子..亥）
  - name: --symptoms
    type: string
    required: false
    description: 症状描述
  - name: --season
    type: string
    required: false
    description: 春/夏/秋/冬
  - name: --syndrome
    type: string
    required: false
    description: 太阴病/少阴病/厥阴病
  - name: --year / --month
    type: int
    required: false
    description: 飞星年月
  - name: --jiugong
    type: string
    required: false
    description: 只查九宫：坎/坤/震/巽/中/乾/兑/艮/离
  - name: --json
    type: bool
    required: false
    description: JSON 输出
metadata:
  author: OpenKitsune
  version: "1.0.0"
  type: decision-engine
---

# 北斗七星与九宫飞星针法引擎

把丹道玄医录中的两套针法落成可执行引擎：

- **北斗七星三才针阵**：以出生时辰定命宫，以施针时辰定当令经络，按「天→地→人→四辅」布针。
- **九宫飞星针法**：以洛书九宫定病位，一宫一组主穴三角，按时辰与五行生克取补泻。
- **两法融合**：七星定纲（纵向贯通三焦）+ 九宫入微（横向精准打击）。

## 何时使用

- 需要按患者出生时辰与就诊时辰生成针阵
- 需要把症状落到九宫病位并给出主穴/配穴
- 需要四时变阵、针深校核、禁忌与疗程建议

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="zhenfa-jiugong",
  script_name="scripts/zhenfa_jiugong.py",
  args=["--birth-hour", "子", "--treat-hour", "辰",
        "--symptoms", "失眠 打嗝 纳差", "--syndrome", "太阴病",
        "--year", "2026", "--month", "10"]
)
```

只查九宫：

```text
run_skill_script(
  skill_name="zhenfa-jiugong",
  script_name="scripts/zhenfa_jiugong.py",
  args=["--jiugong", "离", "--symptoms", "口舌生疮心烦"]
)
```

## 用法

```bash
# 子时命宫，子时施针
python scripts/zhenfa_jiugong.py --birth-hour 0 --treat-hour 0

# 按症状自动选九宫
python scripts/zhenfa_jiugong.py --birth-hour 午 --treat-hour 辰 --symptoms "失眠心悸盗汗"

# 指定季节（春/夏/秋/冬）
python scripts/zhenfa_jiugong.py --birth-hour 卯 --treat-hour 酉 --season 秋

# 带六经病证与飞星年月
python scripts/zhenfa_jiugong.py --birth-hour 子 --treat-hour 辰 \
  --symptoms "失眠 打嗝 纳差" --syndrome 太阴病 --year 2026 --month 10

# 只查九宫配穴
python scripts/zhenfa_jiugong.py --jiugong 离 --symptoms "口舌生疮心烦"
```

## Python API

```python
from zhenfa_jiugong import ZhenfaEngine

engine = ZhenfaEngine()
plan = engine.prescribe(birth_hour="子", treat_hour="辰",
                        symptoms="失眠盗汗心烦", season="冬")
print(plan["main_points"])
print(plan["technique"])
```

## 输出结构

| 字段 | 内容 |
|:----|:-----|
| `natal_palace` | 出生时辰命宫与对应星君 |
| `main_points` | 天、地、人三才主穴 |
| `assist_points` | 四象辅穴 |
| `technique` | 手法与补泻 |
| `jiugong` | 症状落宫、九宫主穴三角 |
| `feixing` | 年飞星/月飞星入中与九宫分布 |
| `classic` | 经典北斗七星阵（含玉衡/开阳辨证替换与配穴加减） |
| `season_adjust` | 四时变阵修正 |
| `cautions` | 禁忌与针深校核 |

## 技能协同

| 技能 | 衔接 |
|:----|:-----|
| `qimen-diagnosis` | 天芮落宫/病宫 → 九宫主穴；时干化合 → 五门十变 |
| `tcm-dual-track` | 六经开路穴、五脏填补穴、水火收功阵 |
| `nongli-paipan` | 出生时辰与施针时辰的干支、节气口径 |

## 边界

- 本引擎是传统针法知识的结构化推演，不替代执业医师的辨证与操作。
- 孕妇、垂危、出血倾向、严重心肺疾病等情形必须在医师指导下处理。
- 针深以《针灸大成》临床记载为准；引擎内置了百会、外关、照海、关元、带脉的校核值。
