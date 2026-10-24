# 🏥 _engines/ — AI 辨证推演引擎套件

> 从 openakita-main 迁徙融合的核心能力。
> 将结构化知识库（data/）转化为可直接调用的推演工具。

---

## 📦 引擎列表

| 引擎 | 文件 | 功能 | 来源 |
|:----|:----|:-----|:-----|
| **PDEEngine** | `pde_engine.py` | 加权评分辨证推演（症状→病机→方剂） | openakita PDE 引擎 |
| **KnowledgeEngine** | `knowledge_engine.py` | 双路检索+TF-IDF+RRF融合 | openakita knowledge_engine |
| **CLI** | `cli.py` | 命令行交互工具 | openakita CLI 模式 |

## 🚀 快速使用

### 1. PDE 辨证推演

```python
from _engines.pde_engine import PDEEngine

engine = PDEEngine()
report = engine.deduce(
    symptoms=["恶寒", "发热", "头痛", "项强"],
    pulse="浮"
)
print(engine.format_report(report))
```

### 2. CLI 命令行

```bash
# 交互模式
python _engines/cli.py

# 单次推演
python _engines/cli.py -s "恶寒,发热,头痛,项强" -p "浮"

# JSON 输出
python _engines/cli.py -s "乏力,纳差,便溏,腹胀" --json

# 知识检索
python _engines/cli.py --search "百合病"

# 按方剂找证型
python _engines/cli.py --find-formula "小柴胡"

# 列出所有证型
python _engines/cli.py --list-syndromes
```

### 3. 知识检索

```python
from _engines.knowledge_engine import KnowledgeEngine

ke = KnowledgeEngine()
ke.build_index()
results = ke.search("百合病 心肺阴虚 百合地黄汤")
for r in results[:5]:
    print(f"[{r['score']:.3f}] {r['title']} → {r['section']}")
```

## 🧠 引擎架构

```
输入症状 ──→ PDEEngine ──→ 六经63证推演 ─┐
                              ├──→ 综合判决 ──→ 诊断报告
                              │      ↓
                              │  金匮五脏推演 ─┘
                              │      ↓
                              │  体用荐药
                              │
输入查询 ──→ KnowledgeEngine ──→ 关键词检索 ─┐
                                   ├──→ RRF融合 ──→ 排序结果
                                TF-IDF语义检索 ─┘
```

## 📋 数据依赖

所有引擎依赖 `data/` 目录下的结构化JSON：

- `data/six_channels/six_channels_63.json` — 六经63证
- `data/jingui_organs/jingui_organs_deduction.json` — 金匮五脏病机
- `data/tiyong_encoding/herb_tiyong_encoding.json` — 本草体用编码

## 🔄 迁移融合说明

| openakita 能力 | 状态 | 说明 |
|:---------------|:----:|:-----|
| PDE 加权推演 | ✅ 完成 | 适配丹道玄医录3个JSON数据 |
| CLI 工具 | ✅ 完成 | 交互+单次+JSON输出 |
| TF-IDF 知识检索 | ✅ 完成 | 扫描所有Markdown，双路+RRT融合 |
| 反馈学习器 | 📅 Phase2 | 捕捉修正反馈，沉淀经验 |
| 五行因果引擎 | 📅 Phase2 | 事件因果图推演病机传变 |
| 经方数据库结构化 | 📅 Phase2 | 180方Markdown→JSON |
| 九宫多Agent推理 | 📅 Phase3 | 多视角协同辨证 |
| 自进化闭环 | 📅 Phase3 | 六阶自动演循环 |

---

> 创建: 2026-07-21 | 版本: 1.0.0
