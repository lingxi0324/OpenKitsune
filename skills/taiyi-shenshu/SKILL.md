---
name: taiyi-shenshu
description: 太乙神数岁计推演引擎 — 积年、太乙宫、文昌/始击、主客算、主客大将参将、八门与掩迫囚击格对格局
category: 中医玄学
exposure_level: core
when-to-use: 需要以太乙神数看年度大势、主客胜负、格局吉凶，或与奇门/五运六气交叉验证时使用。
keywords: [太乙神数, 太乙积年, 太乙宫, 文昌, 始击, 主算, 客算, 掩迫囚击格对]
argument-hint: "--year 2026"
arguments:
  - name: --year
    type: int
    required: false
    description: 公元年份
  - name: --json
    type: bool
    required: false
    description: JSON 输出
metadata:
  author: OpenKitsune
  version: "1.0.0"
  type: decision-engine
---

# 太乙神数推演引擎（岁计）

以太乙金镜式经的「上元积年 → 太乙宫 → 天目/计神 → 始击 → 主客算 → 主客将 → 格局」为主线，输出可复核的结构化岁计盘。

## 何时使用

- 需要以太乙神数看年度大势、主客胜负、格局吉凶
- 需要与奇门、五运六气、九宫飞星做交叉验证
- 需要把「太乙」从名词变成可计算、可复现的排盘结果

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="taiyi-shenshu",
  script_name="scripts/taiyi_shenshu.py",
  args=["--year", "2026"]
)
```

## 用法

```bash
# 当前年岁计
python scripts/taiyi_shenshu.py

# 指定年份
python scripts/taiyi_shenshu.py --year 2026

# JSON 输出
python scripts/taiyi_shenshu.py --year 2026 --json
```

## Python API

```python
from taiyi_shenshu import TaiyiEngine

engine = TaiyiEngine()
pan = engine.year_pan(2026)
print(pan["taiyi"]["palace"], pan["calculations"]["host"]["count"])
print(pan["patterns"])
```

## 输出结构

| 字段 | 内容 |
|:----|:-----|
| `jinian` | 上元积年、纪数、入纪年 |
| `taiyi` | 太乙落宫、入宫年数、阴阳宫 |
| `tianmu` | 文昌/天目十六神与落宫 |
| `jishen` | 计神、合神、太岁 |
| `shiji` | 始击（客目）十六神与落宫 |
| `calculations` | 主算/客算、主客大将、参将 |
| `eight_doors` | 岁计直门 |
| `patterns` | 掩、迫、囚、击、格、对等格局 |
| `judgement` | 主客胜负与用事建议 |

## 算法口径

- 积年锚点：唐开元十二年甲子（公元 724 年）= 1,937,281 算（《太乙金镜式经》）。
- 太乙宫：积年去周纪 360、元法 72、小周 24，三约取宫，顺行八宫、不游中五。
- 天目：积年去 360、72、18，命起武德，顺行十六神，遇武德、大武重留一算。
- 计神：积年去 60，命起寅宫，逆行十二辰。
- 主算：自文昌数至太乙；客算：自始击数至太乙；个位为主客大将，大将加三为参将。
- 计数采用十二宫顺行、含首尾的简法；若师承使用十六神逐位计数或“左门依宫数”累加法，可在 `_count_between()` 中替换。
- 格局：掩（始击临太乙）、迫（始击邻太乙）、囚（文昌临太乙）、击（始击临文昌）、格（始击对太乙）、对（文昌对太乙）。

> 太乙流派众多，本引擎采用《太乙金镜式经》岁计主线与《太乙统宗宝鉴》常用格局，参数在代码中显式可查，便于按师承调整。
