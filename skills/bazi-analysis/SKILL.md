---
name: openkitsune/skills@bazi-analysis
description: "八字命理完整推演工具。输入农历/公历出生年月日时和性别，输出完整的15步八字推演报告：排四柱→安十神→人元司令→生旺死绝→量化强弱→天干五合→地支刑冲→定格局→取用神→十神配置→富贵等级→查神煞→排大运→论流年→综合论断。基于渊海子平、子平真诠、滴天髓、命理正宗、八字实战讲义等典籍方法论。"
license: MIT
category: 中医玄学
exposure_level: core
when-to-use: 需要排四柱八字、判日主强弱格局、取用神、排大运流年时使用。
keywords: [八字, 四柱, 十神, 格局, 用神, 大运, 流年, 神煞, 人元司令]
argument-hint: "--lunar --year 1977 --month 5 --day 5 --hour 0 --gender male --level full"
arguments:
  - name: --lunar/--solar
    type: flag
    required: true
    description: 输入历法
  - name: --year/--month/--day/--hour
    type: int
    required: true
    description: 出生年月日时
  - name: --gender
    type: string
    required: true
    description: male/female
  - name: --level
    type: string
    required: false
    description: basic/standard/full
metadata:
  author: lingxi
  version: "2.1.0"
  openkitsune:
    python:
      dependencies:
        - lunar-python
---

# 八字命理推演工具

基于《渊海子平》《子平真诠评注》《滴天命理新论》《命理正宗》《八字实战讲义》等典籍的八字命理推演系统。

## 功能

- **完整15步推演流程**：排四柱→安十神→人元司令→生旺死绝→量化强弱→天干五合→地支刑冲→定格局→取用神→十神配置→富贵等级→查神煞→排大运→论流年→综合论断
- **多典籍融合**：渊海子平为基础框架，子平真诠为格局体系，滴天髓为气象论，命理正宗为口诀，八字实战讲义为验证
- **量化辅助**：何建忠式计分辅助判断日主强弱
- **用神五法**：扶抑→病药→调候→通关→专旺，逐级递进

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="bazi-analysis",
  script_name="scripts/bazi_analysis.py",
  args=["--lunar", "--year", "1977", "--month", "5", "--day", "5",
        "--hour", "0", "--gender", "male", "--level", "full"]
)
```

## 预置脚本

### scripts/bazi_analysis.py
八字命理完整推演脚本。支持农历和公历两种输入方式。

### 基础用法
```bash
# 农历输入（推荐，按农历年月日）
python scripts/bazi_analysis.py --lunar --year 1977 --month 5 --day 5 --hour 0 --gender male

# 公历输入
python scripts/bazi_analysis.py --solar --year 1977 --month 6 --day 21 --hour 0 --gender male

# 输出级别
python scripts/bazi_analysis.py --lunar --year 1977 --month 5 --day 5 --hour 0 --gender male --level full
# level: basic(基础排盘) | standard(标准:到用神) | full(完整15步,默认)
```
