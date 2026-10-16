---
name: hetu-core
description: 河图洛书核心推演工具 — 三元推演、五行转化、宫位映射轻量 API
author: 灵汐
version: 1.0.0
type: skill
execution-context: script
category: nine-palace-pipeline
exposure_level: core
---

# 河图洛书核心推演 (hetu-core)

## 简介
轻量级河图洛书推演工具，不侵入主流程，按需调用。

## 核心函数
- `san_yuan_tuiyi(wuxing_a, wuxing_b)` — 三元推演（两行生一行）
- `wu_xing_zhuanhua(wuxing_list)` — 五行转化计算
- `gongwei_mapping(gong_id)` — 宫位映射查询

## 使用方式
```python
from skills.hetu_core import san_yuan_tuiyi, wu_xing_zhuanhua, gongwei_mapping

# 三元推演
result = san_yuan_tuiyi("木", "火")  # 木生火 -> {"sheng": "火", "ke": "土", ...}

# 五行转化
result = wu_xing_zhuanhua(["木", "火", "土", "金", "水"])

# 宫位查询
mapping = gongwei_mapping("坎宫")
```

## 输入参数
| 函数 | 参数 | 类型 | 说明 |
|------|------|------|------|
| san_yuan_tuiyi | wuxing_a | str | 五行之一: 木火土金水 |
| san_yuan_tuiyi | wuxing_b | str | 五行之一 |
| wu_xing_zhuanhua | wuxing_list | list[str] | 五行列表 |
| gongwei_mapping | gong_id | str | 宫位标识: 坎宫/坤宫/震宫/巽宫/中宫/乾宫/兑宫/艮宫/离宫 |

## 返回格式
所有函数返回 dict，包含 `success` 和 `result` 字段。

## 输出响应
- success: bool
- result: dict 或 str
- error: str（失败时）
