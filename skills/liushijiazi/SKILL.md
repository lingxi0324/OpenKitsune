---
name: liushijiazi
description: 六十甲子综合分析工具——干支推算、纳音五行、神煞、黄道吉日
category: 中医玄学
exposure_level: core
when-to-use: 需要查某日干支、纳音、神煞、黄道吉日、建除，或做六十甲子偏移推算时使用。
keywords: [六十甲子, 干支, 纳音, 神煞, 黄道吉日, 建除, 日课]
argument-hint: "--date 2026-05-15 --hour 10 | --ganzhi 丁未 | --offset 丁未 3"
arguments:
  - name: --date
    type: string
    required: false
    description: 公历日期 YYYY-MM-DD
  - name: --hour
    type: int
    required: false
    description: 小时 0-23
  - name: --hours all
    type: flag
    required: false
    description: 列出十二时辰
  - name: --detail
    type: flag
    required: false
    description: 详细输出
  - name: --ganzhi
    type: string
    required: false
    description: 查询干支
  - name: --offset
    type: string[int]
    required: false
    description: 干支偏移
metadata:
  author: Lingxi
  version: "1.1.0"
  type: tool
  openkitsune:
    python:
      dependencies:
        - lunar-python
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

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="liushijiazi",
  script_name="scripts/liushijiazi_cli.py",
  args=["--date", "2026-05-15", "--hour", "10"]
)
```

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
- 安装 `lunar_python` 时，年/月/日柱自动改用精确节气与历法；未安装时回退到内置基准日算法。
