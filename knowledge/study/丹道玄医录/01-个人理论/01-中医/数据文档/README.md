# 🗂️ 结构化数据总索引

> **创建**：2026-07-21 | **用途**：AI 可直接消费的 JSON 知识库
> **Schema 版本**：v1.0.0 | **总数据量**：63证 + 53病机 + 73味药

---

## 📋 数据文件一览

| 数据集 | 文件 | 大小 | 条目 | 路径 |
|:-------|:-----|:----:|:----:|:-----|
| **六经63证** | `six_channels_63.json` | 29 KB | 63 证 | `data/six_channels/` |
| **金匮五脏** | `jingui_organs_deduction.json` | 40 KB | 53 病机 | `data/jingui_organs/` |
| **体用编码** | `herb_tiyong_encoding.json` | 92 KB | 73 味药 | `data/tiyong_encoding/` |

---

## 🏗️ 数据结构说明

### 1. 六经63证 (`six_channels_63.json`)

```json
{
  "meta": { "version", "source", "date", "description" },
  "channels": {
    "太阳": { "symptoms_core", "pathogenesis", "pulse", "tongue" },
    "阳明": { ... },
    "少阳": { ... },
    "太阴": { ... },
    "少阴": { ... },
    "厥阴": { ... }
  },
  "conditions": [
    {
      "id": 1,
      "name": "太阳独病",
      "channels": ["太阳"],
      "channel_count": 1,
      "combination_type": "1经独病",
      "formula": "桂枝汤、麻黄汤",
      "severity": "轻-独经"
    }
    // ... 63条
  ],
  "combination_types": { "独病", "两经合病", ..., "六经俱病" },
  "mnemonics": { "chant", "notes" }
}
```

### 2. 金匮五脏 (`jingui_organs_deduction.json`)

```json
{
  "meta": { ... },
  "san_guan": { "表里观", "正邪观", "津液观" },
  "si_zheng": { "气证", "血证", "水证", "火证" },
  "hua_qi_relations": { "甲己化土", "乙庚化金", ..., "戊癸化火" },
  "chapters": [
    {
      "chapter_id": 1,
      "chapter_name": "脏腑经络先后病",
      "sections": [
        {
          "section_name": "总纲基础病机",
          "conditions": [
            {
              "id": 1,
              "name": "经络外邪束表，脏腑内气不和",
              "pathogenesis": "表里俱病...",
              "san_guan_assessment": "表里俱病·正邪相持·津液初滞",
              "si_zheng_type": ["气滞", "郁火", "津行不畅"],
              "hua_qi_mechanism": "诸干气化失调",
              "formula": "桂枝汤类调和营卫"
            }
            // 53条病机
          ]
        }
      ]
    }
    // 22篇
  ]
}
```

### 3. 本草体用编码 (`herb_tiyong_encoding.json`)

```json
{
  "meta": { "total_herbs": 73, "categories": ["补气", "补血", ...] },
  "nine_coordinates": [
    { "turn": 1, "name": "河图生数", "range": "1-5", "meaning": "气分归脏" }
    // 9个维度
  ],
  "herbs": [
    {
      "id": 1,
      "name": "人参",
      "flavor": "甘、微苦，微温",
      "meridian_return": ["脾", "肺", "心"],
      "ti": "味甘为土体之正味...",
      "yong": "大补元气...",
      "coordinate": {
        "values": [5, 9, 5, 2, 0.3, 0.4, 1, 0, 0.5],
        "dimensions": {
          "河图生数": 5,
          "河图成数": 9,
          "洛书正位": 5,
          "洛书变位": 2,
          "阴阳消长": 0.3,
          "三才层次": 0.4,
          "四象方向": 1,
          "八卦辨象": 0,
          "归元转化": 0.5
        }
      },
      "mnemonic": "土金之体，升化之用；中宫坐镇，厚德载物"
    }
    // 73味药
  ]
}
```

---

## 🔍 AI 消费指引

### 查询示例

```python
# 1. 症状→六经定位
import json

def find_channel_by_symptoms(symptoms: list[str]):
    with open("data/six_channels/six_channels_63.json") as f:
        data = json.load(f)
    results = []
    for condition in data["conditions"]:
        if any(s in condition["name"] for s in symptoms):
            results.append(condition)
    return results

# 2. 病机→金匮定位
def find_jingui_by_huaqi(hua_qi: str):
    with open("data/jingui_organs/jingui_organs_deduction.json") as f:
        data = json.load(f)
    results = []
    for ch in data["chapters"]:
        for sec in ch.get("sections", []):
            for cond in sec["conditions"]:
                if hua_qi in cond["hua_qi_mechanism"]:
                    results.append(cond)
    return results

# 3. 体用坐标→本草检索
from typing import Optional
def find_herbs_by_coordinate(
    coord_dim: int, min_val: float, max_val: float, top_k: int = 5
):
    with open("data/tiyong_encoding/herb_tiyong_encoding.json") as f:
        data = json.load(f)
    matches = []
    for herb in data["herbs"]:
        val = herb["coordinate"]["values"][coord_dim - 1]
        if min_val <= val <= max_val:
            matches.append(herb)
    return matches[:top_k]

# 4. 体用融合检索
def find_herbs_combining(body_channel: int, function_use: int):
    """体属某经+用属某经"""
    results = []
    with open("data/tiyong_encoding/herb_tiyong_encoding.json") as f:
        data = json.load(f)
    for herb in data["herbs"]:
        sv = int(herb["coordinate"]["values"][0])  # 体-生数
        cv = int(herb["coordinate"]["values"][1])  # 用-成数
        if sv == body_channel and cv == function_use:
            results.append(herb)
    return results
```

### 快速参考：九转坐标维度

| 转次 | 名称 | 值域 | 意义 |
|:----:|:-----|:----:|:-----|
| 1 | 河图生数 | 1-5 | 气分归脏（1水/2火/3木/4金/5土） |
| 2 | 河图成数 | 6-10 | 血分归脏（6水/7火/8木/9金/10土） |
| 3 | 洛书正位 | 1-9 | 九宫方位归经 |
| 4 | 洛书变位 | -4~+4 | 升降浮沉偏移（负降正升） |
| 5 | 阴阳消长 | -1.0~+1.0 | 寒热温凉（负寒正热） |
| 6 | 三才层次 | 0.0~1.0 | 气分(0-0.3)/血分(0.4-0.6)/精分(0.7-1.0) |
| 7 | 四象方向 | 0-3 | 冬藏(0)/夏长(1)/秋收(2)/春生(3) |
| 8 | 八卦辨象 | 0-7 | 坤(0)/震(1)/离(2)/兑(3)/乾(4)/巽(5)/坎(6)/艮(7) |
| 9 | 归元转化 | 0.0~1.0 | 食药同源度（高=近食物） |

---

## 📐 扩展计划

### 后续可添加的数据集

| # | 数据 | 规模 | 来源 |
|:-:|:-----|:----:|:-----|
| 1 | 经方数据库 | ~180方 | `01-中医/05-药学/01-经方数据库/` |
| 2 | 伤寒方药体用解 | ~50方 | `01-中医/05-药学/03-伤寒方药体用解/` |
| 3 | 体用真实味经方重解 | ~50方 | `01-中医/05-药学/04-体用真实味经方重解/` |
| 4 | 二十四脉象 | 24脉 | `01-中医/02-辨证方法/` |
| 5 | 温病要药体用编码 | 24味 | `01-中医/07-专题研究/01-温病体用贯穿/` |
| 6 | 内科杂病辨证分类 | 待定 | `01-中医/02-辨证方法/` |

---

> **用法**：AI 助手读取此索引后，可按需加载对应 JSON 文件到工作内存中，作为中医辨证的知识底座直接参与推理。
