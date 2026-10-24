# reference 模板 — 知识参考技能

## 适用场景

知识问答、索引查阅类技能。适用于特定领域的知识库封装。

## 关键变量

| 变量 | 说明 |
|------|------|
| TOPIC_1~3_NAME | 主题名称 |
| TOPIC_1~3_CONTENT | 主题内容 |
| REF_KEY/VAL_HEADER | 快速参考表头 |
| REF_KEY/VAL_1~3 | 快速参考条目 |

## 使用方式

```bash
python tools/skill_manager.py template apply reference my-reference \
  DESCRIPTION="Use when..." \
  TOPIC_1_NAME="核心概念"
```
