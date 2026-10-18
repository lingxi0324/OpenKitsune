"""决策路由推导模块（纯技术语义，无领域名词）。

把 `agent/reasoning.py` 中逐条手写的 `_DECISION_TO_LABEL` 路由表，
替换为『决策意图签名 + 处置规则』的内在推导：

- 词汇表只声明每个决策的**意图**（执行动作 / 产出结果 / 等待用户 /
  继续推理 / 异常终止 / 验证未过）；
- 路由由意图的**处置语义**推导，而不是逐条写“某词 → 某节点”；
- 推导结果与既有字面表**严格等价**（测试锁定，行为零变化）。

设计同构于 `agent/state.py` 的阶段迁移推导（职能签名 + 递生/收敛规则）：
事实源是语义签名，行为关系由规则生成。
"""

from __future__ import annotations

from enum import Enum

# ═══════════════════════════════════════════════════════════════
# 决策词汇（与既有 _DECISION_TO_LABEL 键集对齐；字符串常量，
# 不依赖 openkitsune 枚举，模块可独立导入与测试）
# ═══════════════════════════════════════════════════════════════

TOOL_CALLS = "tool_calls"
FINAL_ANSWER = "final_answer"
TOOL_USE = "tool_use"
ASK_USER = "ask_user"
CONTINUE = "continue"
ERROR = "error"
MAX_ITERATIONS = "max_iterations"
VERIFY_INCOMPLETE = "verify_incomplete"

# 既有字面路由表（行为基线，仅用于等价断言；替换后不再被运行时使用）
LEGACY_DECISION_TO_LABEL: dict[str, str] = {
    TOOL_CALLS: "act",
    FINAL_ANSWER: "verify",
    TOOL_USE: "act",
    ASK_USER: "finalize",
    CONTINUE: "reason",
    ERROR: "finalize",
    MAX_ITERATIONS: "finalize",
    VERIFY_INCOMPLETE: "reason",
}

# 推理图节点（与原 build_reasoning_graph 的标签一致）
ACT = "act"
VERIFY = "verify"
FINALIZE = "finalize"
REASON = "reason"


# ═══════════════════════════════════════════════════════════════
# 意图签名：决策的内在性质（唯一事实源，替换手写路由）
# ═══════════════════════════════════════════════════════════════

class DecisionIntent(Enum):
    """决策意图签名（技术语义）。

    - EXECUTE        需要执行外部动作（工具调用）
    - PRODUCE_RESULT 产出最终结果（须先过验证门再进终态）
    - WAIT_USER      需要用户介入（挂起，走收尾）
    - CONTINUE       需要继续推理
    - ABORT          异常 / 资源耗尽（走收尾）
    - VERIFY_PENDING 验证未通过（回推理，唯一回退路径）
    """

    EXECUTE = "execute"
    PRODUCE_RESULT = "produce_result"
    WAIT_USER = "wait_user"
    CONTINUE = "continue"
    ABORT = "abort"
    VERIFY_PENDING = "verify_pending"


# 词汇 → 意图（事实源：新决策只需在这里声明意图，不改路由）
_DECISION_INTENT: dict[str, DecisionIntent] = {
    TOOL_CALLS: DecisionIntent.EXECUTE,
    TOOL_USE: DecisionIntent.EXECUTE,
    FINAL_ANSWER: DecisionIntent.PRODUCE_RESULT,
    ASK_USER: DecisionIntent.WAIT_USER,
    CONTINUE: DecisionIntent.CONTINUE,
    ERROR: DecisionIntent.ABORT,
    MAX_ITERATIONS: DecisionIntent.ABORT,
    VERIFY_INCOMPLETE: DecisionIntent.VERIFY_PENDING,
}


# ═══════════════════════════════════════════════════════════════
# 处置规则：意图 → 推理图节点（推导而非逐条路由）
# ═══════════════════════════════════════════════════════════════

_INTENT_TO_LABEL: dict[DecisionIntent, str] = {
    DecisionIntent.EXECUTE: ACT,  # 有外部副作用 → 进入执行节点
    DecisionIntent.PRODUCE_RESULT: VERIFY,  # 结论必过验证门
    DecisionIntent.WAIT_USER: FINALIZE,  # 等待外部输入 → 挂起收尾
    DecisionIntent.CONTINUE: REASON,  # 需更多推理 → 推理节点
    DecisionIntent.ABORT: FINALIZE,  # 异常终止 → 收尾
    DecisionIntent.VERIFY_PENDING: REASON,  # 验证未过 → 回推理
}


def derive_decision_to_label(
    intent_map: dict[str, DecisionIntent] | None = None,
) -> dict[str, str]:
    """由决策意图推导路由表（不逐条硬编码路由）。

    Args:
        intent_map: 词汇→意图 映射；默认使用模块词表。传入自定义映射
            可用于验证扩展性（新增词汇只需声明意图）。

    Returns:
        词汇 → 推理图节点 的完整路由表。
    """
    source = intent_map if intent_map is not None else _DECISION_INTENT
    return {word: _INTENT_TO_LABEL[intent] for word, intent in source.items()}


def derive_label_for_word(word: str) -> str | None:
    """单词路由查询（运行时使用；未声明意图返回 None）。"""
    intent = _DECISION_INTENT.get(word)
    if intent is None:
        return None
    return _INTENT_TO_LABEL[intent]


# ═══════════════════════════════════════════════════════════════
# 自检（等价 + 完备 + 函数性），供测试与构建期复用
# ═══════════════════════════════════════════════════════════════

def assert_derivation_equivalent(
    legacy: dict[str, str] | None = None,
) -> dict[str, str]:
    """断言推导表与既有字面表逐项等价，并满足完备/函数性。

    Returns:
        推导出的路由表（替换后的运行时事实源）。

    Raises:
        AssertionError: 推导结果偏离既有行为，或路由表不完备 / 不函数。
    """
    derived = derive_decision_to_label()
    baseline = legacy if legacy is not None else LEGACY_DECISION_TO_LABEL

    # 行为等价：键集一致 + 逐项路由一致
    assert set(derived) == set(baseline), (
        f"键集漂移：derived-only={set(derived) - set(baseline)} "
        f"legacy-only={set(baseline) - set(derived)}"
    )
    for word in baseline:
        assert derived[word] == baseline[word], (
            f"路由漂移 {word}: derived={derived[word]} legacy={baseline[word]}"
        )

    # 完备性：每个词汇都有目标节点
    assert all(label in {ACT, VERIFY, FINALIZE, REASON} for label in derived.values())
    # 函数性：每个节点都有词汇可达（无悬空节点）
    reachable = set(derived.values())
    assert reachable == {ACT, VERIFY, FINALIZE, REASON}, (
        f"存在不可达节点：{ {ACT, VERIFY, FINALIZE, REASON} - reachable }"
    )
    return derived
