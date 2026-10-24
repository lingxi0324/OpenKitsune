# framework 模板 — 分析框架技能

## 适用场景

结构化分析引擎类技能，如推演引擎、辨证体系、评估框架。

## 关键变量

| 变量 | 说明 |
|------|------|
| ARCHITECTURE_DIAGRAM | 架构图（ASCII 或文本） |
| COMPONENT_1~3_NAME | 核心组件名称 |
| COMPONENT_1~3_DESC | 核心组件描述 |
| MODE_1/2_NAME | 双模式名称 |
| CONFIG_KEY/VAL | 配置参数 |

## 使用方式

```bash
python tools/skill_manager.py template apply framework my-framework \
  DESCRIPTION="Use when..." \
  ARCHITECTURE_DIAGRAM="第1层→第2层..."
```
