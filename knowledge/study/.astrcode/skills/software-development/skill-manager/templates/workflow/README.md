# workflow 模板 — 工作流技能

## 适用场景

步骤化流程驱动型技能。适用于有明确步骤序列的操作。

## 关键变量

| 变量 | 说明 |
|------|------|
| STEP_1_NAME~STEP_4_NAME | 各步骤名称 |
| STEP_1_DETAIL~STEP_4_DETAIL | 各步骤详细描述 |
| CONFIG_KEY/DESC/DEFAULT | 配置参数 |

## 使用方式

```bash
python tools/skill_manager.py template apply workflow my-workflow \
  DESCRIPTION="Use when..." \
  STEP_1_NAME="第一步名称"
```
