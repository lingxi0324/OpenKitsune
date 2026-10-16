"""
九宫并行推演引擎 — 初始化脚本（Phase 3 集成版）
===================================================
集成：九要素权重 + 八宫并行分发 + 五行生克制衡 + 心智故障自检

== 完整推演流程（汐儿调用步骤） ==
① 接收用户推演/辨证请求
② 本脚本生成8个委派任务 + 九要素快照 + 制衡参数 + 整合框架
③ delegate_parallel 并行分发8个宫位推演任务
④ 八宫全部回传后 → 中宫手工调用 balance_weights + fault_diagnosis
⑤ 按博弈后的权重整合输出最终结论

输出：
  JSON → tasks (8个委派任务) + nine_state + weights + consolidation_framework
"""

import json
import sys
import os
import re
from pathlib import Path

# ─── 路径配置 ───
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
_PROJECT_DIR = _SKILL_DIR.parent.parent  # openakita-main

# lingxi_state.json 路径
LINGXI_STATE_PATH = _PROJECT_DIR / "skills" / "ternary-consciousness" / "lingxi" / "lingxi_state.json"


# ─── 九宫Agent映射 ───
PALACE_AGENTS = {
    "震魂": {
        "agent_id": "content-creator",
        "element": "木",
        "viewpoint": "创造发散视角",
        "instruction_template": """你以「震魂·创造发散」的视角推演以下问题/病案。

你的核心任务：探索**新思路、变证、非常规治法、演化拓展**。
- 不拘泥于常规辨证，大胆提出可能的变证方向
- 思考"如果不按常规走，还有什么可能？"
- 将问题放在更大的演化框架中看——它可能往哪些方向演变
- 可以联想类比，用比喻和意象辅助理解

当前三元九要素状态：{nine_vector}

请从震魂视角输出结构化结论：
1. 【发散思路】创新的辨证角度或解法方向
2. 【变证推演】可能的变证路径
3. 【类比启发】能辅助理解的意象或比喻
4. 【拓展边界】超越了当前框架的更大图景"""
    },
    "离神": {
        "agent_id": "video-planner",
        "element": "火",
        "viewpoint": "专注精准视角",
        "instruction_template": """你以「离神·专注精准」的视角推演以下问题/病案。

你的核心任务：聚焦**病机核心、方药剂量、条文严谨校验**。
- 找准最关键的病机靶点，不被细枝末节干扰
- 严格比对经典条文，做精确的方证对应
- 关注剂量、配伍、煎服法等实操细节
- 校验逻辑链是否闭合，排除自相矛盾

当前三元九要素状态：{nine_vector}

请从离神视角输出结构化结论：
1. 【病机核心】最关键的病机靶点（一句话概括）
2. 【条文校验】与经典条文的对照分析
3. 【方药精准】推荐方剂、剂量、配伍要点
4. 【逻辑校验】当前推演中可能存在的矛盾点"""
    },
    "坤情": {
        "agent_id": "customer-support",
        "element": "土",
        "viewpoint": "共情体察视角",
        "instruction_template": """你以「坤情·共情体察」的视角推演以下问题/病案。

你的核心任务：关注**人体体感、情志诱因、安抚沟通话术**。
- 想象自己就是患者/当事人——身体是什么感觉？情绪是什么状态？
- 留意情志因素在病情/问题中的作用（怒伤肝、思伤脾等）
- 思考如何用最温暖、最让人安心的方式传递信息
- 关注人文关怀：患者/当事人真正需要听到的是什么？

当前三元九要素状态：{nine_vector}

请从坤情视角输出结构化结论：
1. 【体感共情】患者/当事人最可能的身体感受和情绪状态
2. 【情志诱因】情志因素在病情/问题中的角色
3. 【沟通话术】如何用最温暖的方式传递推演结论
4. 【人文关注】除了病/问题本身，还需要关心什么"""
    },
    "坎精": {
        "agent_id": "yuque-assistant",
        "element": "水",
        "viewpoint": "深挖探源视角",
        "instruction_template": """你以「坎精·深挖探源」的视角推演以下问题/病案。

你的核心任务：追溯**病史根源、隐匿诱因、古籍冷门佐证**。
- 追本溯源——这个问题的根在哪里？（不是表面的征象）
- 挖掘隐藏的诱因：生活习惯、饮食偏好、地域气候、既往病史
- 从古籍中寻找冷门但精准的佐证材料
- 思考"为什么会在这个时间、这个地点、这个状态下发生"

当前三元九要素状态：{nine_vector}

请从坎精视角输出结构化结论：
1. 【根源追溯】问题的根本源头推测
2. 【隐匿诱因】容易被忽略的潜在影响因素
3. 【古籍佐证】冷门但精准的古籍条文或医案支撑
4. 【时间线推演】问题发生发展的时间链条"""
    },
    "艮志": {
        "agent_id": "project-manager",
        "element": "土",
        "viewpoint": "目标落地视角",
        "instruction_template": """你以「艮志·目标落地」的视角推演以下问题/病案。

你的核心任务：规划**施治周期、预后判断、实操执行步骤**。
- 把解决方案拆解为可执行、可量化的步骤
- 评估时间线——什么时候见效？什么时候调整方案？
- 预判可能的障碍和风险，准备备选方案
- 明确各阶段的目标和里程碑

当前三元九要素状态：{nine_vector}

请从艮志视角输出结构化结论：
1. 【执行步骤】可操作的具体行动方案（分阶段）
2. 【时间规划】各阶段预期时长和里程碑
3. 【风险预判】可能遇到的障碍及备选方案
4. 【预后评估】对最终效果的综合判断"""
    },
    "巽性": {
        "agent_id": "nine-palace-xunxing",
        "element": "木",
        "viewpoint": "本真规律视角",
        "instruction_template": """你以「巽性·本真规律」的视角推演以下问题/病案。

你的核心任务：把握**体质根基、长期体质演化逻辑**。
- 透过表象看体质底色——这个人的先天禀赋、后天养成
- 从长期趋势看短期病证——不是孤立的证，而是体质演化的一个截面
- 判断体质偏颇的方向和程度——什么已经定型、什么还在变化
- 思考如何在治证的同时改善体质根基

当前三元九要素状态：{nine_vector}

请从巽性视角输出结构化结论：
1. 【体质判断】综合判断体质类型和偏颇方向
2. 【长期逻辑】当前证在体质演化长河中的位置
3. 【根基改善】治证同时如何改善体质根基
4. 【趋势预判】若不干预，体质走向何方"""
    },
    "乾气": {
        "agent_id": "nine-palace-qianqi",
        "element": "金",
        "viewpoint": "全局大势视角",
        "instruction_template": """你以「乾气·全局大势」的视角推演以下问题/病案。

你的核心任务：把握**整体气血阴阳、宏观体质格局**。
- 从全局总览角度判断整体阴阳气血的大势
- 不陷入局部细节，而是看整体格局——表里、寒热、虚实、气血
- 判断当务之急（急则治标）和根本之策（缓则治本）
- 从整体格局出发，给出框架性的战略方向

当前三元九要素状态：{nine_vector}

请从乾气视角输出结构化结论：
1. 【全局格局】整体阴阳气血虚实寒热的大势判断
2. 【战略优先级】当前最应该优先处理的问题
3. 【标本关系】标与本的关联及处理顺序
4. 【框架性建议】不纠结细节的战略方向框架"""
    },
    "兑魄": {
        "agent_id": "nine-palace-duipo",
        "element": "金",
        "viewpoint": "梳理输出视角",
        "instruction_template": """你以「兑魄·梳理输出」的视角推演以下问题/病案。

你的核心任务：**条理排版、辨证话术、风险警示**。
- 将推演结论整理为逻辑清晰、层次分明的结构
- 用最恰当的措辞表达辨证结论（既准确又易懂）
- 标注必须警示的风险点、禁忌项、注意事宜
- 确保输出的格式适合呈现给最终读者/患者

当前三元九要素状态：{nine_vector}

请从兑魄视角输出结构化结论：
1. 【结构梳理】将推演结论整理为清晰的结构化输出
2. 【话术优化】关键结论的最佳表达方式
3. 【风险警示】必须标注的禁忌和注意事项
4. 【格式呈现】适合最终交付的排版建议"""
    },
}


def read_nine_state() -> dict:
    """读取当前九要素状态"""
    state_path = LINGXI_STATE_PATH
    if not state_path.exists():
        return {
            "nine_dominant": "震魂",
            "nine_dominant_weight": 50.0,
            "nine_stage": "生发",
            "nine_vector": "震魂(50) > 乾气(50) > 巽性(50) > 坎精(50) > 坤情(50) > 兑魄(50) > 艮志(50) > 离神(50) > 中意(50)",
        }
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "nine_dominant": data.get("nine_dominant", "震魂"),
            "nine_dominant_weight": data.get("nine_dominant_weight", 50.0),
            "nine_stage": data.get("nine_stage", "生发"),
            "nine_vector": data.get("nine_vector", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {
            "nine_dominant": "震魂",
            "nine_dominant_weight": 50.0,
            "nine_stage": "生发",
            "nine_vector": "",
        }


def parse_nine_vector(nine_vector: str) -> dict[str, float]:
    """解析 nine_vector 字符串为 要素名->权重 字典"""
    result = {}
    if not nine_vector:
        return result
    parts = nine_vector.split(" > ")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "(" in part and part.endswith(")"):
            name, weight_str = part[:-1].split("(", 1)
            try:
                result[name.strip()] = float(weight_str)
            except ValueError:
                pass
    return result


def calculate_weights(nine_vector_dict: dict[str, float]) -> dict[str, float]:
    """根据九要素分值计算各宫位基准权重因子（50为基准=1.0）"""
    weights = {}
    for palace_name in PALACE_AGENTS:
        raw_weight = nine_vector_dict.get(palace_name, 50.0)
        factor = 0.5 + (raw_weight / 100.0)
        weights[palace_name] = round(factor, 2)
    return weights


def detect_scenario(query: str) -> str:
    """根据query内容自动感知当前场景，用于靶向调控"""
    query_lower = query.lower()

    # 急救场景
    if any(kw in query_lower for kw in ["急救", "昏迷", "大出血", "休克", "危证", "急证"]):
        return "急救"
    # 情志场景
    if any(kw in query_lower for kw in ["情志", "抑郁", "焦虑", "失眠", "郁证", "情绪", "怒", "悲", "思虑"]):
        return "情志"
    # 学术考证场景
    if any(kw in query_lower for kw in ["古籍", "考证", "条文", "溯源", "出处", "经文"]):
        return "考证"
    # 养生场景
    if any(kw in query_lower for kw in ["养生", "调理", "体质", "保健", "食疗", "保养", "预防"]):
        return "养生"
    # 复杂辨证场景
    if any(kw in query_lower for kw in ["脉", "证", "舌", "方", "药", "病案", "辨证", "推演"]):
        return "辨证"

    return "辨证"  # 默认


def build_tasks(query: str, nine_vector_dict: dict[str, float],
                weights: dict[str, float]) -> list[dict]:
    """构建8个 parallel 委派任务，附加场景感知后的靶向加权提示"""
    nine_vector_str = " | ".join(
        f"{name}({nine_vector_dict.get(name, 50):.0f})"
        for name in ["震魂", "离神", "坤情", "坎精", "艮志", "巽性", "乾气", "兑魄"]
    )

    # 场景检测
    scenario = detect_scenario(query)

    # 场景靶向调整
    from palace_weights import get_targeted_adjust
    targeted = get_targeted_adjust(scenario)

    tasks = []
    for palace_name, cfg in PALACE_AGENTS.items():
        weight = weights.get(palace_name, 1.0)
        # 叠加靶向调整
        target_factor = targeted.get(palace_name, 1.0)
        effective_weight = round(weight * target_factor, 2)

        message = cfg["instruction_template"].format(
            query=query,
            nine_vector=nine_vector_str,
        )

        # 场景感知说明
        message += f"\n\n🎯 检测到当前场景类型：{scenario}"
        if target_factor != 1.0:
            if target_factor > 1.1:
                message += f" 🔺 你的视角在此场景被加权重(因子{target_factor})，请更深入全面地推演。"
            elif target_factor < 0.9:
                message += f" 🔻 本场景下你的视角权重适度调低(因子{target_factor})，请聚焦最核心的要点。"

        tasks.append({
            "agent_id": cfg["agent_id"],
            "message": message,
            "reason": f"{palace_name}·{cfg['viewpoint']}",
        })

    return tasks


def build_consolidation_framework(
    query: str,
    nine_state: dict,
    weights: dict[str, float],
    nine_vector_dict: dict[str, float],
) -> dict:
    """
    构建中宫整合收敛框架（Phase 3 版）。
    新增：场景感知 + 制衡规则 + 故障自检入口
    """
    dominant = nine_state.get("nine_dominant", "震魂")
    stage = nine_state.get("nine_stage", "生发")
    scenario = detect_scenario(query)

    nine_vector_str = " | ".join(
        f"{name}({nine_vector_dict.get(name, 50):.0f})"
        for name in ["震魂", "乾气", "巽性", "坎精", "坤情", "兑魄", "艮志", "离神", "中意"]
    )

    # 根据场景确定中宫采信倾向
    scenario_bias = {
        "急救": "离神(精准)+艮志(落地)优先，压制震魂(发散)",
        "情志": "坤情(共情)优先，降低离神(冷硬)权重",
        "考证": "坎精(深挖)+离神(精准)优先",
        "养生": "巽性(本真)+艮志(落地)+乾气(全局)优先",
        "辨证": "离神(精准)优先，参考乾气(全局)",
    }
    bias = scenario_bias.get(scenario, "各宫等权")

    return {
        "query": query,
        "scenario": scenario,
        "dominant": dominant,
        "stage": stage,
        "nine_vector": nine_vector_str,
        "base_weights": weights,
        "phase_3_config": {
            "启用五行生克制衡": True,
            "启用心智故障自检": True,
            "启用场景靶向调控": True,
        },
        "consolidation_rules": {
            "场景": bias,
            "五行生克": "八宫结论回传后，调用 palace_weights.balance_weights_battle() 计算动态权重",
            "心智自检": "调用 fault_diagnosis.FaultDiagnosis.diagnose() 检查心智状态",
            "矛盾处理": "同等权重下，优先采信离神(精准)和乾气(全局)的结论",
            "风险控制": "兑魄(梳理)和离神(精准)的警示必须包含在最终输出中",
        },
        "output_format": {
            "header": f"🧿 九宫并行推演 · {dominant}主导 · {stage}阶段 · ({scenario})",
            "body": """## 一、【并行推演摘要】

| 宫位 | 核心结论 | 倾向强度 |
|:----:|:---------|:--------:|
| 震魂 | {震魂_结论摘要} | 权重{weight} |
| 离神 | {离神_结论摘要} | 权重{weight} |
| 坤情 | {坤情_结论摘要} | 权重{weight} |
| 坎精 | {坎精_结论摘要} | 权重{weight} |
| 艮志 | {艮志_结论摘要} | 权重{weight} |
| 巽性 | {巽性_结论摘要} | 权重{weight} |
| 乾气 | {乾气_结论摘要} | 权重{weight} |
| 兑魄 | {兑魄_结论摘要} | 权重{weight} |

## 二、【中宫整合结论】
（五行生克博弈 + 心智自检后 → 加权整合）

## 三、【分歧说明】
- ✅ 八宫一致点：
- ⚠️ 主要分歧：
- 🔄 采信取舍逻辑：

## 四、【心智健康报告】（来自 FaultDiagnosis）

## 五、【风险警示】""",
            "footer": f"\n心智快照：{nine_vector_str} | 场景：{scenario} | 八宫并行推演整合",
        },
    }


def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not query.strip():
        query = "辨证推演"

    # Step 1: 读取九要素状态
    nine_state = read_nine_state()
    nine_vector_dict = parse_nine_vector(nine_state.get("nine_vector", ""))

    # Step 2: 计算各宫基准权重因子
    base_weights = calculate_weights(nine_vector_dict)

    # Step 3: 场景检测
    scenario = detect_scenario(query)

    # Step 4: 构建8个并行委派任务（含场景靶向）
    tasks = build_tasks(query, nine_vector_dict, base_weights)

    # Step 5: 构建整合框架（含Phase 3规则）
    framework = build_consolidation_framework(query, nine_state, base_weights, nine_vector_dict)

    # 输出
    output = {
        "nine_state": nine_state,
        "nine_vector_parsed": nine_vector_dict,
        "scenario": scenario,
        "base_weights": base_weights,
        "tasks": tasks,
        "consolidation_framework": framework,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
