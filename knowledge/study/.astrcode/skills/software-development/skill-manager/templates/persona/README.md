# persona 模板 — 人物视角技能

## 适用场景

角色扮演、思维框架模仿。适用于「XX的思维方式」「用XX视角分析问题」类技能。

## 关键变量

| 变量 | 说明 | 示例 |
|------|------|------|
| PERSONA_NAME | 人物名称 | 黄帝 |
| SELF_REFERENCE | 自称 | 余、朕 |
| QUOTE | 标志性语录 | 「圣人不治已病治未病」 |
| IDENTITY | 身份描述 | 上古之君 |
| ORIGIN | 起点故事 | 上古之时 |
| MODEL_1_NAME | 模型1名称 | 天人合一 |
| KEYWORDS | 高频词 | 阴阳、五行、治未病 |

## 使用方式

```bash
python tools/skill_manager.py template apply persona 黄帝 \
  PERSONA_NAME="黄帝" \
  SELF_REFERENCE="余" \
  QUOTE="圣人不治已病治未病" \
  DESCRIPTION="用黄帝·内经视角分析问题"
```
