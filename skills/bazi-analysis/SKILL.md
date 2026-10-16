---
name: openkitsune/skills@bazi-analysis
description: "八字命理完整推演工具。输入农历/公历出生年月日时和性别，输出完整的15步八字推演报告：排四柱→安十神→人元司令→生旺死绝→量化强弱→天干五合→地支刑冲→定格局→取用神→十神配置→富贵等级→查神煞→排大运→论流年→综合论断。基于渊海子平、子平真诠、滴天髓、命理正宗、八字实战讲义等典籍方法论。"
license: MIT

category: 中医玄学
exposure_level: core
metadata:
  author: lingxi
  version: "2.0.0"
---

# 八字命理推演工具

基于《渊海子平》《子平真诠评注》《滴天命理新论》《命理正宗》《八字实战讲义》等典籍的八字命理推演系统。

## 功能

- **完整15步推演流程**：排四柱→安十神→人元司令→生旺死绝→量化强弱→天干五合→地支刑冲→定格局→取用神→十神配置→富贵等级→查神煞→排大运→论流年→综合论断
- **多典籍融合**：渊海子平为基础框架，子平真诠为格局体系，滴天髓为气象论，命理正宗为口诀，八字实战讲义为验证
- **量化辅助**：何建忠式计分辅助判断日主强弱
- **用神五法**：扶抑→病药→调候→通关→专旺，逐级递进

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
