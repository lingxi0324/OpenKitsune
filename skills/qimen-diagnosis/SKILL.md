---
name: openkitsune/skills@qimen-diagnosis
description: 奇门遁甲病机诊断工具 — 时空即病机，九宫即脏腑，天芮定病灶。六步推演法 + 九重辩证法 + 内伤外感双规 + 五运六气加权 + 格局旺衰，输出结构化诊断报告
category: 中医玄学
exposure_level: core
when-to-use: 需要按就诊时间起奇门盘、以天芮/八门/八神定病位病性、做内伤外感双规判断或格局旺衰分析时使用。
keywords: [奇门遁甲, 病机诊断, 天芮, 九宫, 八门, 八神, 内伤外感, 格局, 旺衰, 反吟伏吟]
argument-hint: "--year 2026 --month 5 --day 7 --hour 8 --pretty 头痛口苦"
arguments:
  - name: symptoms
    type: string
    required: true
    description: 症状描述
  - name: --year/--month/--day/--hour
    type: int
    required: false
    description: 就诊时间；缺省为当前
  - name: --tongue
    type: string
    required: false
    description: 舌象
  - name: --pulse
    type: string
    required: false
    description: 脉象
  - name: --pretty
    type: bool
    required: false
    description: 可读输出
metadata:
  author: OpenKitsune
  version: "2.1.0"
  openkitsune:
    python:
      dependencies:
        - lunar-python
---

# 奇门遁甲病机诊断工具

> **核心公式**：时空即病机，九宫即脏腑，天芮定病灶
> **临床次序**：起盘→天芮定位→病位定性→病性定量→五运六气加权→出方案
> **统合层次**：六步推演外层 + 九重辩证内层 + 多科室适配

基于游兄独创的奇门遁甲病机诊断法体系，融合六步推演法、九重辩证法、内伤外感双规辩证、多科室辨证、五运六气加权，实现临床快速诊断。

**输入时间+症状 → 自动排盘 → 六步法分析 → 输出结构化诊断报告**

## 核心特色

| 特色 | 说明 |
|:----|:------|
| 精准排盘 | `qimen_paipan.py` 时家拆补转盘：定局、地盘三奇六仪、天盘九星/天盘干、八门、八神、值符值使、空亡驿马 |
| 多科室适配 | 内科/妇科/儿科/外科/精神科 五科奇门诊疗体系 |
| 内伤外感双规 | 外感看天盘天芮+五运六气；内伤看地盘九宫+八门 |
| 九重辩证内层 | 九重辩证法的奇门映射（空间：上下表里深浅） |
| 太玄经拆解 | 病机从证型层→个体层→时空层的穿透分析 |
| 格局与旺衰 | 十干克应、八门旺相、九星旺衰、门迫/门制、反吟/伏吟 |
| 四柱角色 | 年干（环境）/月干（同辈）/日干（患者）/时干（病气）落宫与生克 |
| 天芮+八神 | 八种情志病因组合，直接落到心理与行为层 |

## 六步推演法（核心诊断流程）

### 第1步：起盘定局
四柱干支 + 节气定位 → 阴阳遁判定 + 局数 → 九宫完整排布（星/门/神） → 值符/值使定位 + 用神落宫

### 第2步：天芮定位
查天芮病星落宫 + 所临八门八神：
- 天芮落宫 → 病灶所在脏腑
- 天芮+八门 → 病势吉凶（伤门=筋损、死门=脏衰、杜门=痰瘀）
- 天芮+八神 → 情志病因（腾蛇=怪异、白虎=血证、玄武=幻觉）

### 第3步：病位定性
| 九宫 | 脏腑/区域 | 九宫 | 脏腑/区域 |
|:----:|:---------|:----:|:---------|
| 坎1 | 肾、腰、耳、骨 | 离9 | 心、目、血、热 |
| 坤2 | 脾、腹、肉、湿 | 艮8 | 胃、鼻、关节 |
| 震3 | 肝、胁、筋、风 | 兑7 | 肺、口、咽、皮毛 |
| 巽4 | 胆、风 | 乾6 | 肺/大肠、头、骨 |
| 中5 | 脾（中焦枢纽） | | |

### 第4步：病性定量
八门断吉凶：休门(虚) / 生门(新病) / 伤门(炎症) / 杜门(慢性) / 景门(热证) / 死门(器质性) / 惊门(紊乱) / 开门(正气存)

### 第5步：五运六气加权
司天/在泉 + 主气/客气 + 节气叠加盘面。年运定格局（丙午=少阳相火→郁火重），月气定病机倾向。

### 第6步：出方案
- **针法**：五门十变化合配穴 + 九宫配穴
- **方药**：辅行诀体用五味 + 五脏补泻
- **时机**：空亡填实日、反吟伏吟刺法禁忌

## 九重辩证法在奇门中的映射

| 重 | 核心问题 | 要点 |
|:--:|:---------|:-----|
| 1·三才定性 | 天盘/人盘/地盘哪部？ | 天=外感六淫，人=病势情志，地=脏腑经络 |
| 2·五步推演 | 证→机→因→治→效闭环 | 审盘→辨证→审因→立法→随访 |
| 3·五运加权 | 年运/司天/在泉如何加权？ | 同证异运不同方 |
| 4·内伤外感 | 先辨内外再辨证 | 外感天芮+天盘，内伤八门+地盘 |
| 5·时空穿变 | 病机如何在干支/节气间传变 | 丁日心经旺→丙日小肠旺 |
| 6·方证对应 | 辅行诀哪张方？ | 脏腑补泻与五味体用 |
| 7·多科室 | 归哪个科室？ | 立极点宫位+症状性质判定 |
| 8·剂量法度 | 药量/针数/疗程？ | 河图生成数定用量 |
| 9·疗程预后 | 病势走向？ | 天芮+时令旺衰 + 八门生克 |

## 直接调用（无需写代码）

```text
run_skill_script(
  skill_name="qimen-diagnosis",
  script_name="scripts/qimen_diagnosis.py",
  args=["--year", "2026", "--month", "5", "--day", "7",
        "--hour", "8", "--pretty", "头痛两侧口苦"]
)
```

只排盘、不做诊断：

```text
run_skill_script(
  skill_name="qimen-diagnosis",
  script_name="scripts/qimen_paipan.py",
  args=["--year", "2026", "--month", "5", "--day", "7", "--hour", "8"]
)
```

## 用法

```bash
# 指定时间症状
python scripts/qimen_diagnosis.py --year 2026 --month 5 --day 7 --hour 8 --pretty "头痛两侧口苦"
# 当前时间+症状
python scripts/qimen_diagnosis.py --pretty "腰酸痛，双腿乏力，怕冷"
# 带四诊
python scripts/qimen_diagnosis.py --tongue "舌淡苔白腻" --pulse "脉沉弦" "失眠多梦"
```

**参数**：`--year/--month/--day/--hour` 就诊时间（默认当前），`--pretty` 可读输出，`--tongue/--pulse` 四诊，`-o` 输出文件。

## 完整推演（九维引擎）

```python
from nine_dim_engine import NineDimEngine
engine = NineDimEngine()

# 静态推演
result = engine.deduce_3d(year=2026, month=6, day=2, hour=13,
    multi_dim_bind={"person": "问事人", "event": "求职面试"},
    spatial_hints={"person_zone": "震宫", "event_zone": "离宫"})

# 空间剖面
profile = engine.calc_spatial_profile(meta)      # L1~L6穿透
# 因果穿透
causal = engine.calc_causal_penetration(meta)     # 三层因果
# 时间趋势
trend = engine.calc_time_rolling(meta, direction="forward", steps=6)

# 全穿透
full = engine.deduce_full_penetration(meta, direction="forward")
```

## 格局与旺衰分析（v2.1.0 新增）

`scripts/qimen_patterns.py` 提供轻量分析库，已接入 `qimen_diagnosis.py` 的输出：

| 能力 | 函数 | 输出 |
|:----|:----|:-----|
| 十干克应 | `detect_geju()` | 青龙返首、飞鸟跌穴、青龙逃走、白虎猖狂、腾蛇夭矫、朱雀投江、大格、刑格等 |
| 反吟/伏吟 | `detect_fuyin_fanyin()` | 星门归本宫/对宫比例与急慢病判定 |
| 八门旺相 | `gate_wangshuai()` | 按八节判旺/相/休/囚/死 |
| 九星旺衰 | `star_wangshuai()` | 按月令判旺/相/休/囚/死 |
| 门迫/门制 | `men_po()` | 门克宫/宫克门与病势进退 |
| 天芮+八神 | `tianrui_shen_combo()` | 八种情志病因组合 |
| 四柱角色 | `ganzhi_role_analysis()` | 年/月/日/时干落宫与生克 |

诊断输出新增 `pattern_analysis` 字段；`--pretty` 会直接打印「格局与旺衰」区块。

## 技能协同

| 下游技能 | 衔接方式 |
|:--------|:--------|
| `tcm-dual-track` | 奇门定病位与病势，三观四证定六经开路/五脏填补 |
| `zhenfa-jiugong` | 奇门病宫 → 九宫配穴；时干化合 → 五门十变针法 |
| `nongli-paipan` | 统一节气、四柱、黄历口径，避免各技能各算一套 |
| `taiyi-shenshu` | 年运/主客格局与奇门年盘交叉验证 |

## 依赖

- Python 3.10+, `lunar-python`, llama-server :18099
- 内置知识库：`reference/knowledge/`（奇门遁甲病机诊断法、实战推演规律、奇门应期、九维推演方法）
- 外部知识库（可选）：`丹道玄医录/02-临床辨证/` 下的六经三才论、双规辩证、五脏九宫矩阵、辅行诀体用辨等

## 参考文档（外置，按需读取）

> SKILL.md 仅含核心框架。详细参考已外移至 `reference/` 目录：

| 文件 | 内容 | 适用场景 |
|:----|:-----|:---------|
| `reference/科室分类表.md` | 立极点→科室全映射 | 分科室诊断时 |
| `reference/九维立体推演引擎.md` | 九维引擎完整API | 使用九维穿透时 |
| `reference/暗干应期演卦.md` | 暗干穿透+应期三法+演卦 | 应期判定/奇门演卦 |
| `reference/六大升级模块.md` | L1~L6穿透+因果+时间滚 | 深度推演时 |
| `reference/案例库示例.md` | 完整诊断JSON输出示例 | 参考输出格式 |

## 环境变量

| 变量 | 说明 | 默认 |
|:----|:-----|:----:|
| `LLM_API_URL` | LLM API 地址 | `http://127.0.0.1:18099/v1/chat/completions` |
| `LLM_MODEL` | 模型名称 | `qwen2.5` |
| `KNOWLEDGE_BASE` | 外部知识库根目录（可选；内置 `reference/knowledge` 始终加载） | 空 |
