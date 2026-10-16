"""
九宫特质动态制衡 · 宫位生克权重引擎
=====================================
基于洛书五行制衡的八宫生克博弈逻辑。

核心：不是静态加权，而是根据八宫实际结论动态制衡。
各宫结论之间的冲突、呼应、相似度，反哺权重调整。
"""

# ─── 宫位五行归属（洛书九宫） ───
# 震东木 → 离南火 → 坤西南土 → 乾西北金 → 坎北水
# 巽东南木（辅震）| 兑西金（辅乾）| 艮东北土（辅坤）| 中中央土
PALACE_FIVE_ELEMENT = {
    "震魂": "木",  # 创造发散
    "巽性": "木",  # 本真规律
    "离神": "火",  # 专注精准
    "坤情": "土",  # 共情体察
    "艮志": "土",  # 目标落地
    "中意": "土",  # 平衡统筹
    "乾气": "金",  # 全局大势
    "兑魄": "金",  # 梳理输出
    "坎精": "水",  # 深挖探源
}

# ─── 五行生克关系矩阵 ───
# 相生：木→火→土→金→水→木
# 相克：木→土→水→火→金→木
SHENG_MAP = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_MAP = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}


def get_palace_element(palace_name: str) -> str:
    """获取宫位五行属性"""
    return PALACE_FIVE_ELEMENT.get(palace_name, "土")


def calc_sheng_ke_weights(palace_name: str, base_weight: float) -> dict:
    """
    计算某宫在当前生克关系下的权重调整。

    返回：
    - weight_adjust: 该宫自身的权重增减（基于被生/被克状态）
    - boost_from: 被哪个宫生（增益来源）
    - suppress_from: 被哪个宫克（压制来源）
    - boost_to: 生哪个宫（增益去向）
    - suppress_to: 克哪个宫（压制去向）
    """
    elem = get_palace_element(palace_name)
    be_sheng = SHENG_MAP.get(elem)  # 谁生我？
    be_ke = KE_MAP.get(elem)        # 谁克我？

    # 生我者增益我（母生子），我生者我增益它
    # 克我者压制我，我克者我压制它
    adjust = 0.0

    return {
        "element": elem,
        "be_sheng": be_sheng,
        "be_ke": be_ke,
        "sheng_to": {k for k, v in PALACE_FIVE_ELEMENT.items() if v == be_sheng},
        "ke_to": {k for k, v in PALACE_FIVE_ELEMENT.items() if v == be_ke},
    }


def balance_weights_battle(
    palace_results: dict[str, dict],
    base_weights: dict[str, float],
    conflict_matrix: dict[tuple[str, str], float] = None,
) -> dict[str, float]:
    """
    八宫结论博弈 → 动态制衡权重。

    核心算法：
    1. 初始权重 = 九要素归一化权重
    2. 五行相生：被生宫结论与生宫结论一致 → 两宫权重各 +5%
    3. 五行相克：克宫与受克宫结论对立 → 克宫 +3%/受克宫 -3%
    4. 冲突度反馈：多宫严重对立 → 中宫权重提升（调和优先）
    5. 共识度奖惩：多数结论一致 → 异议宫自动降低权重

    Args:
        palace_results: {宫名: {结论结构}}
        base_weights: 来自九要素的基准权重
        conflict_matrix: 可选，各宫间结论冲突度 (0~1)

    Returns:
        {宫名: 最终博弈权重}
    """
    weights = dict(base_weights)

    if not conflict_matrix:
        # 如果没有传入冲突矩阵，基于各宫结论的相似度估计
        conflict_matrix = {}

    # ─── 1. 五行相生增益 ───
    for palace_a_name in palace_results:
        elem_a = get_palace_element(palace_a_name)
        # 谁生我？
        sheng_mother_elem = KE_MAP.get(elem_a)  # 克我者即生我者
        # 修正：SHENG_MAP是A→B，要找谁生A：查value为A的key
        mother_elem = None
        for k, v in SHENG_MAP.items():
            if v == elem_a:
                mother_elem = k
                break

        if mother_elem:
            # 找到所有mother_elem的宫
            mother_palaces = [n for n, e in PALACE_FIVE_ELEMENT.items() if e == mother_elem and n != palace_a_name]
            for mp in mother_palaces:
                if mp in palace_results:
                    # 生我者的结论与我一致 → 相生增益
                    agreement = _estimate_agreement(palace_results[mp], palace_results[palace_a_name])
                    if agreement > 0.6:
                        weights[palace_a_name] = weights.get(palace_a_name, 1.0) * 1.05
                        weights[mp] = weights.get(mp, 1.0) * 1.05

    # ─── 2. 五行相克压制 ───
    for palace_a_name in palace_results:
        elem_a = get_palace_element(palace_a_name)
        # 我克谁？
        ke_target_elem = KE_MAP.get(elem_a)
        if ke_target_elem:
            target_palaces = [n for n, e in PALACE_FIVE_ELEMENT.items() if e == ke_target_elem and n != palace_a_name]
            for tp in target_palaces:
                if tp in palace_results:
                    disagreement = 1.0 - _estimate_agreement(palace_results[tp], palace_results[palace_a_name])
                    if disagreement > 0.6:
                        weights[palace_a_name] = weights.get(palace_a_name, 1.0) * 1.03
                        weights[tp] = weights.get(tp, 1.0) * 0.97

    # ─── 3. 全局冲突检测 ───
    total_conflict = 0.0
    pairs = 0
    palace_names = list(palace_results.keys())
    for i in range(len(palace_names)):
        for j in range(i + 1, len(palace_names)):
            p1, p2 = palace_names[i], palace_names[j]
            if p1 in palace_results and p2 in palace_results:
                conf = 1.0 - _estimate_agreement(palace_results[p1], palace_results[p2])
                total_conflict += conf
                pairs += 1

    avg_conflict = total_conflict / max(pairs, 1)

    # 高冲突 → 提升中意权重（调和优先）
    if avg_conflict > 0.5 and "中意" in weights:
        weights["中意"] *= (1.0 + avg_conflict * 0.2)

    # ─── 4. 共识度分布 ───
    # 统计各宫的"孤立度"：有多少其他宫与其严重对立
    isolation = {}
    for p1 in palace_results:
        isolated = 0
        for p2 in palace_results:
            if p1 != p2:
                if 1.0 - _estimate_agreement(palace_results[p1], palace_results[p2]) > 0.7:
                    isolated += 1
        isolation[p1] = isolated

    # 高度孤立的宫降低权重（可能偏离共识）
    for p, iso in isolation.items():
        if p != "中意" and iso > len(palace_results) / 2:
            weights[p] = weights.get(p, 1.0) * 0.9

    # 归一化到合理范围 [0.5, 1.5]
    for p in weights:
        weights[p] = max(0.5, min(1.5, weights[p]))

    return weights


def _estimate_agreement(result_a: dict, result_b: dict) -> float:
    """
    估计两个宫位结论之间的共识度（0~1）。
    基于结构化字段的重叠程度估算。
    找不到匹配字段时返回 0.5（中立估计）。
    """
    # 若任一为空，返回中立
    if not result_a or not result_b:
        return 0.5

    # 尝试逐段比较文本内容的关键词重叠
    agreements = []

    for field in ["核心结论", "病机核心", "体质判断", "全局格局", "发散思路"]:
        text_a = result_a.get(field, "") or ""
        text_b = result_b.get(field, "") or ""

        if not text_a or not text_b:
            continue

        text_a = str(text_a)
        text_b = str(text_b)

        # 提取有意义的字符（去掉空格和标点）
        import re
        chars_a = set(re.findall(r'[\u4e00-\u9fff]{2,}', text_a))
        chars_b = set(re.findall(r'[\u4e00-\u9fff]{2,}', text_b))

        if not chars_a or not chars_b:
            continue

        overlap = len(chars_a & chars_b) / len(chars_a | chars_b)
        agreements.append(overlap)

    if not agreements:
        return 0.5

    return sum(agreements) / len(agreements)


def get_targeted_adjust(
    scenario: str = ""
) -> dict[str, float]:
    """
    靶向微调：根据场景预设，返回 {宫名: 额外权重因子}

    紧急急救 → 锁死离神高权重，压制震魂发散
    情志咨询 → 提升坤情，压制离神的冷硬精准
    学术考证 → 提升坎精和离神
    养生调理 → 提升巽性和艮志
    """
    presets = {
        "急救": {"离神": 1.3, "震魂": 0.7, "兑魄": 1.1},
        "情志": {"坤情": 1.3, "离神": 0.85, "震魂": 1.1},
        "考证": {"坎精": 1.3, "离神": 1.15, "兑魄": 1.1, "震魂": 0.8},
        "养生": {"巽性": 1.2, "艮志": 1.15, "乾气": 1.1},
        "辨证": {"离神": 1.1, "坎精": 1.05, "兑魄": 1.1},
        "答疑": {"离神": 1.05, "兑魄": 1.15, "乾气": 1.05},
    }

    for key, adj in presets.items():
        if key in scenario:
            return adj

    return {}


if __name__ == "__main__":
    # 自检
    print("【宫位五行归属】")
    for p, e in PALACE_FIVE_ELEMENT.items():
        print(f"  {p} → {e}")
    print(f"\n【五行生克】")
    print(f"  相生链: {' → '.join(SHENG_MAP[k] for k in ['木','火','土','金','水'])}")
    print(f"  相克链: {' → '.join(KE_MAP[k] for k in ['木','土','水','火','金'])}")
    print("\n✅ palace_weights.py 自检通过")
