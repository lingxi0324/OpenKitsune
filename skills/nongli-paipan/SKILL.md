---
name: nongli-paipan
description: 农历查询与排盘引擎 — 公历/农历互转、四柱干支、二十四节气、建除十二神、二十八宿、黄历宜忌与神煞
category: 中医玄学
exposure_level: core
when-to-use: 用户询问农历、黄历、节气、四柱、生肖、宜忌、冲煞，或需要统一的时间排盘底座时使用。
keywords: [农历, 黄历, 公历转农历, 四柱, 节气, 建除, 二十八宿, 神煞, 宜忌]
argument-hint: "2026-05-15 --hour 10 | --lunar 2026 3 29 | --range 2026-05-15 7"
arguments:
  - name: date
    type: string
    required: false
    description: 公历日期 YYYY-MM-DD；缺省为今天
  - name: --lunar
    type: int[3]
    required: false
    description: 农历年 月 日；闰月加 --leap
  - name: --hour
    type: int
    required: false
    description: 小时 0-23
  - name: --range
    type: string[2]
    required: false
    description: 起始日期 天数
  - name: --json
    type: bool
    required: false
    description: JSON 输出
metadata:
  author: OpenKitsune
  version: "1.0.0"
  type: tool
  openkitsune:
    python:
      dependencies:
        - lunar-python
---

# 农历查询与排盘引擎

把「查农历」升级为「可复用的排盘底座」：任一公历/农历时刻都能同时得到四柱、节气、建除、值神、二十八宿、神煞与黄历宜忌，供奇门、紫微、四柱、针法等技能直接调用。

## 何时使用

- 用户询问某日农历、节气、生肖、干支、宜忌、冲煞
- 其他推演技能需要一个统一的「时间 → 四柱/节气」入口
- 需要批量列出某段时间的日课信息（择日、排盘、复盘）

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="nongli-paipan",
  script_name="scripts/nongli_paipan.py",
  args=["2026-05-15", "--hour", "10"]
)
```

农历输入：

```text
run_skill_script(
  skill_name="nongli-paipan",
  script_name="scripts/nongli_paipan.py",
  args=["--lunar", "2026", "3", "29", "--hour", "10"]
)
```

## 用法

```bash
# 公历查询（默认当前时间）
python scripts/nongli_paipan.py 2026-05-15 --hour 10

# 农历查询（闰月加 --leap）
python scripts/nongli_paipan.py --lunar 2026-04-29 --hour 10

# 连续 7 天日课
python scripts/nongli_paipan.py --range 2026-05-15 7 --hour 8

# JSON 输出
python scripts/nongli_paipan.py 2026-05-15 --hour 10 --json
```

## Python API

```python
from nongli_paipan import NongliPaipan

engine = NongliPaipan()
info = engine.solar(2026, 5, 15, hour=10)
print(info["four_pillars"], info["jieqi"]["current"])
```

返回字段：

| 字段 | 内容 |
|:----|:-----|
| `solar` / `lunar` | 公历、农历日期与中文表述 |
| `four_pillars` | 年/月/日/时四柱 |
| `nayin` | 四柱纳音 |
| `jieqi` | 当前节气、上一节气、下一节气 |
| `jianchu` / `tianshen` | 建除十二神、黄道黑道值神 |
| `xiu` | 二十八宿、宿禽、吉凶 |
| `shensha` | 吉神、凶煞 |
| `yi` / `ji` | 当日宜、忌 |
| `chong` / `sha` | 日冲、日煞 |

## 依赖与边界

- 依赖 `lunar_python`（项目已作为可选依赖使用；缺失时脚本给出明确安装提示）。
- 节气与干支以 `lunar_python` 的节气表为准，不做近似推算。
- 黄历宜忌属于传统通书口径，仅作文化参考，不构成医疗、投资或法律建议。
