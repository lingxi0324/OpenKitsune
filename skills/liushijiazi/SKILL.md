---
name: liushijiazi
description: 六十甲子综合分析工具——干支推算、纳音五行、神煞、黄道吉日
category: tcm
exposure_level: core
metadata:
  name: liushijiazi
  description: 六十甲子综合分析工具——干支推算、纳音五行、神煞、黄道吉日
  author: Lingxi
  version: 1.0.0
  type: tool
  python:
    dependencies: []
---

# 六十甲子综合分析工具

## 功能概述
基于已知基准日（2000年1月1日=己卯日）推算任意公历日期的：
- 年柱/月柱/日柱干支
- 时辰干支（五鼠遁）
- 纳音五行
- 神煞（天德/月德/驿马/桃花/天赦等）
- 黄道吉日（建除十二星）
- 六合/六冲/三合/相刑关系

## 使用方法
```bash
python scripts/liushijiazi_cli.py --date 2026-05-15
python scripts/liushijiazi_cli.py --date 2026-05-15 --hour 10
python scripts/liushijiazi_cli.py --date 2026-05-15 --hours all
python scripts/liushijiazi_cli.py --date 2026-05-15 --detail
python scripts/liushijiazi_cli.py --ganzhi 丁未
python scripts/liushijiazi_cli.py --offset 丁未 3
```

## 核心数据
- 天干：甲乙丙丁戊己庚辛壬癸（序号1-10）
- 地支：子丑寅卯辰巳午未申酉戌亥（序号1-12）
- 六十甲子组合表（序号1-60）
- 纳音五行表（30组）
- 基准日：2000年1月1日 = 己卯日
