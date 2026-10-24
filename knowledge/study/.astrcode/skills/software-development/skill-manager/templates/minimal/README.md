# minimal 模板 — 最小化技能

## 适用场景

简单的工具/命令类技能，仅需核心元信息和少量操作指引。

## 关键变量

| 变量 | 说明 |
|------|------|
| DESCRIPTION | 简短描述 |
| WHEN_TO_USE | 触发条件 |
| OVERVIEW | 概述 |
| TRIGGER_A | 触发场景 |
| DONT_USE | 不适用的场景 |

## 使用方式

```bash
python tools/skill_manager.py template apply minimal my-skill \
  DESCRIPTION="Use when doing X" \
  WHEN_TO_USE="trigger condition"
```
