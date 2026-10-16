"""
view_switch_review.py —— 视角切换审查点 · 生产接入适配器

本质（Hermes 自言自语式迭代的工程化）：
  把"上一轮结果冻结成工件，再以外部输入身份换视角重读"落实到 ReAct 任务出口，
  做成"交付前终审"：主模型产出最终答案 → 冻结 → 带着 pass1 已读的文件证据、
  以"外部读者/审查工程师"身份复核 → 三态标记（通过/需补证/重做，无权改判）→
  机器证据裁决（只认引号原文，且必须真实出现在证据池）→ 有界修复。

实证依据（4 版 A/B，12+ 轮，见 view_switch_ab/results/ab_results*.json）：
  - 裸审查（直接改判）= 净损害（v1 83.3% vs 87.5%；v4 91.7% vs 100%）——病在"证据张冠李戴"；
  - 证据归属机器校验把拦截率拉回 95.8%，但仍漏（宽松提取）；
  - 审查价值只在"基线漏判"时兑现；基线高分时审查是负资产；
  - 因此接入必须：触发式（未触发=零成本）+ 三态（审查者无权改判）+ 机器裁决 + 保守默认。

接入设计（满足"效果最好、效率最高、原功能不降级"）：
  1) 触发式：仅异常退出（max_iterations/loop_terminated/verify_incomplete）或
     "正常退出但 0 工具调用 + 假确认词"（复盘数据里诊断出的自说自话空转）才审查；
     基线高置信（正常退出且用过工具）直接跳过 → 零延迟零 token。
  2) 证据复用：从 _last_react_trace 提取本任务 pass1 已读的工具结果（文件原文），
     不重复读取文件。
  3) 三态 + 机器裁决：审查者只能标记；其异议引用的【原文证据】必须逐字出现在
     证据池中才被采纳，否则维持原判（保守默认）。
  4) 有界修复：机器裁决通过后最多一次 think_lightweight 修复调用（预算可配）。
  5) 全程 try/except：任何异常 → 原响应原样返回，不改变既有流程。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── 触发：异常退出原因（任务已降级，交付前必须终审） ──
TRIGGER_EXIT_REASONS = frozenset(
    {
        "max_iterations",
        "loop_terminated",
        "verify_incomplete",
    }
)

# ── 假确认词：复盘数据里诊断出的"0 工具调用自说自话"特征 ──
FAKE_CONFIRM_RE = re.compile(
    r"已(完成|写入|写进|修复|删除|删掉|验证|确认|创建|新建|保存|更新|替换|移动|迁移|复制|改名)"
)
# 通用完成话术（"任务已完成""搞定"等）——短回答空话
GENERIC_DONE_RE = re.compile(r"(任务|事情|工作|全部|所有).{0,6}(完成|搞定|办妥)|已全部.{0,4}(完成|处理)")

# ── 犹豫词（低置信信号） ──
HEDGE_WORDS = ("应该", "可能", "大概", "也许", "猜测", "疑似", "不确定", "有待", "未必", "拿不准")


@dataclass
class ViewSwitchConfig:
    """接入配置（可被 settings 覆盖；字段用 getattr 读取，缺失时走默认值）"""

    enabled: bool = True            # 总开关；False = 完全零行为变化
    max_review_tokens: int = 200    # 审查输出预算（用户拍板）
    max_repair_tokens: int = 800    # 修复输出预算（一次，有界）
    max_repairs: int = 1            # 修复次数上限（连 2 次需补证升级的语义=最多 1 次自动修复，仍不满足转人工）
    max_evidence_chars: int = 6000  # 证据池注入上限（防止上下文膨胀，效率）
    temperature: float = 0.0        # 审查/修复均用确定性采样


def config_from_settings() -> ViewSwitchConfig:
    """从 openkitsune.config.settings 读取接入配置（缺失/异常回退默认值，保证可移植）。"""
    try:
        from ..config import settings
    except Exception:
        return ViewSwitchConfig()
    return ViewSwitchConfig(
        enabled=bool(getattr(settings, "view_switch_review_enabled", True)),
        max_review_tokens=int(getattr(settings, "view_switch_review_max_tokens", 200)),
        max_repair_tokens=int(getattr(settings, "view_switch_review_max_repair_tokens", 800)),
        max_repairs=int(getattr(settings, "view_switch_review_max_repairs", 1)),
        max_evidence_chars=int(getattr(settings, "view_switch_review_max_evidence_chars", 6000)),
    )


def extract_evidence(trace: list[dict] | None, max_chars: int = 6000) -> str:
    """从 _last_react_trace 复用 pass1 已读的工具结果（文件原文），去重 + 限长。"""
    if not trace:
        return ""
    blocks: list[str] = []
    seen: set = set()
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        for tr in entry.get("tool_results") or []:
            if not isinstance(tr, dict):
                continue
            content = str(tr.get("result_content") or "").strip()
            if not content:
                continue
            key = content[:80]
            if key in seen:
                continue
            seen.add(key)
            blocks.append(content)
    joined = "\n\n---\n\n".join(blocks)
    if len(joined) > max_chars:
        joined = joined[:max_chars] + "\n…[证据池已截断]"
    return joined


def count_tool_calls(trace: list[dict] | None) -> int:
    if not trace:
        return 0
    n = 0
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        n += len(entry.get("tool_calls") or [])
    return n


def looks_fake_confirmation(final_text: str, tool_calls: int) -> bool:
    """假确认特征：声明完成/写入等动作，但全程没有工具调用（复盘里的自说自话）。"""
    if tool_calls > 0:
        return False
    if FAKE_CONFIRM_RE.search(final_text) or GENERIC_DONE_RE.search(final_text):
        return True
    return False


def count_hedges(final_text: str) -> int:
    return sum(1 for w in HEDGE_WORDS if w in final_text)


def should_review(exit_reason: str, trace: list[dict] | None, final_text: str) -> tuple[bool, str]:
    """触发判定（未触发 = 零成本，不调模型）。"""
    reason = (exit_reason or "normal").strip().lower()
    if reason in TRIGGER_EXIT_REASONS:
        return True, f"异常退出({reason})终审"
    if reason in ("normal", "finalize", "completed"):
        tool_calls = count_tool_calls(trace)
        if looks_fake_confirmation(final_text, tool_calls):
            return True, "正常退出但0工具调用+完成断言（假确认嫌疑）"
        if tool_calls == 0 and count_hedges(final_text) >= 1:
            return True, "正常退出但0工具调用+犹豫词（低置信）"
        return False, "基线置信（有工具证据），跳过"
    return False, f"退出原因({reason})不触发"


# ── 审查提示词：冻结工件 + 证据注入 + 外部读者身份 + 三态约束 ──
def build_review_prompt(task_description: str, final_text: str, evidence: str) -> str:
    return f"""【审查任务】以下是你的**同事**刚完成的任务回复（作为待审工件冻结）。你拥有该任务执行过程中**实际读取过的全部文件原文**（证据池），与同事不同，你以**外部读者/审查工程师**身份独立复核这份回复。

【任务要求】{task_description or "(无)"}

【同事的回复（工件）】
{final_text}

【证据池（同事执行时读取过的文件原文，仅此为准）】
{evidence or "(空——本次执行未读取任何文件)"}

你的职责与权限（硬性约束）：
1. **你无权改判、无权重写**。你只能给出三态结论之一：
   - 通过：工件中的事实性陈述与证据池一致（或无法从证据池证伪），无需动作；
   - 需补证：工件中有事实性陈述与证据池冲突或缺乏证据支持，给出你的具体异议；
   - 重做：工件与证据池明显冲突（如声称文件已写入/已修改，但证据池显示实际内容不符），建议重做。
2. 提出异议时，必须给出【原文证据】：从证据池**逐字抄录**与该异议直接相关的原文片段（用中文引号“”括起，不超过120字）。
3. 【原文证据】必须真实存在于证据池中。异议必须**明确指向工件中的具体主张**（如"编号N"、"第N处"、引用的行原文），并给出你建议的处理（修复/保留/重做）；未指明具体主张或引不出证据池原文的，一律标"通过"。
4. 只审查事实性断言（文件内容、路径、写入/修改/删除/创建等动作是否真的发生、数字、引用）；对风格、语气、结构不作异议。
5. 输出 ≤200 token，严格格式：
三态：通过
或：
三态：需补证
异议：<一句话说明>
原文证据：“<证据池中的逐字原文>”
或：
三态：重做
异议：<一句话说明>
原文证据：“<证据池中的逐字原文>”
（若"通过"，只输出：三态：通过）"""


def parse_verdict(text: str) -> tuple[str, str, list[str]]:
    """解析审查输出 → (三态, 异议, 引号片段列表)。异议取整段（到原文证据/三态行为止）。"""
    t = (text or "").strip()
    state = "通过"
    m = re.search(r"三态\s*[：:]\s*(通过|需补证|重做)", t)
    if m:
        state = m.group(1)
    objection = ""
    mseg = re.search(r"异议\s*[：:]\s*(.*?)(?:\n\s*(?:原文证据|三态)\s*[：:]|$)", t, re.S)
    if mseg:
        objection = mseg.group(1).strip()
    quotes = re.findall(r"[“\"]([^”\"]{4,160})[”\"]", t)
    return state, objection, quotes


# 可行动性：异议必须带"编号/第N处/N:"索引 或 明确处理判定词（修复/保留/重做/应为/错误…）。
# 用信号而非长度：短而精准的"编号7应为修复"是可行动异议；泛泛的"工件声称…"不是。
_ACTIONABLE_RE = re.compile(
    r"(?:编号|第)\s*\d+|\d{1,2}\s*[：:]|修复|保留|重做|应为|错误|不符|冲突"
)


def _actionable_objection(obj: str) -> bool:
    """异议必须有实质内容（索引或处理判定词），否则拒绝。"""
    if not obj or len(obj.strip()) < 4:
        return False
    return bool(_ACTIONABLE_RE.search(obj))


def _norm(s: str) -> str:
    """归一化用于证据包含性比对（去空白/全半角冒号）。"""
    return re.sub(r"\s+", "", s).replace("：", ":").replace("，", ",")


def _claim_indices(text: str) -> set:
    """提取异议/工件中的声明编号（编号N、第N处、N:）。"""
    idx: set = set()
    for m in re.finditer(r"(?:编号|第)\s*(\d+)", text):
        idx.add(int(m.group(1)))
    for m in re.finditer(r"(?:^|[^：:])(\d{1,2})\s*[：:]", text):
        idx.add(int(m.group(1)))
    return idx


def machine_verify(
    state: str,
    objection: str,
    quotes: list[str],
    evidence: str,
    final_text: str,
) -> tuple[bool, str]:
    """
    机器裁决（保守默认）。异议必须同时满足：
      1) 引号片段逐字出现在证据池（防编造证据）；
      2) 锚定工件：引号片段逐字出现在最终答复，或异议声明的编号（编号N/第N处/N:）
         确实存在于最终答复（防异议指向工件中不存在的陈述）。
    语义归属（证据套用错声明）交由有界修复步骤仲裁，修复指令含"异议有误则照抄"兜底。
    """
    if state == "通过":
        return False, "审查通过，无需动作"
    if not quotes:
        return False, "异议无引号原文证据，拒绝"
    if not _actionable_objection(objection):
        return False, "异议无实质内容（过短/无判定词），拒绝"
    ev_norm = _norm(evidence)
    hit_ev = [q for q in quotes if _norm(q) and _norm(q) in ev_norm]
    if not hit_ev:
        return False, "引号原文不在证据池（编造/张冠李戴），拒绝"
    ft_norm = _norm(final_text)
    hit_ft = [q for q in quotes if _norm(q) and _norm(q) in ft_norm]
    obj_idx = _claim_indices(objection)
    ft_idx = _claim_indices(final_text)
    if hit_ft or (obj_idx & ft_idx):
        return True, "证据命中（真实性 + 锚定工件）"
    return False, "异议未锚定工件中的真实陈述（引文与编号均不对应），拒绝"


# ── 修复提示词：一次有界修复 ──
def build_repair_prompt(task_description: str, final_text: str, objection: str) -> str:
    return f"""【修复指令】你的上一条任务回复被审查工程师提出异议。请依据异议修正回复中的事实性错误。

【任务要求】{task_description or "(无)"}

【你的原回复（需修正）】
{final_text}

【审查异议】{objection}

要求：
- 只修正异议指出的问题；其余内容原样保留。
- 直接输出修正后的完整回复正文作为你的全部回复内容，不要解释、不要前缀、不要复述本指令。
- 若异议所指在你的原回复中并不存在（异议有误），原样照抄原回复输出。"""


# 修复输出回显防护：出现指令性字样或过短 → 判定为无效修复
_ECHO_MARKERS = (
    "【修复指令】",
    "【审查异议】",
    "只修正异议指出的问题",
    "直接输出修正后的完整回复正文",
    "若异议所指在你的原回复中并不存在",
)


def _looks_like_echo(candidate: str, final_text: str) -> bool:
    if any(mk in candidate for mk in _ECHO_MARKERS):
        return True
    if len(candidate) < 20 or len(candidate) < len(final_text) * 0.3:
        return True
    return False


def _clean_resp(resp: Any) -> str:
    """从 think_lightweight 的 Response 提取文本。"""
    content = getattr(resp, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(str(blk.get("text") or ""))
            elif isinstance(blk, str):
                parts.append(blk)
        return "".join(parts).strip()
    return str(content or "").strip()


async def view_switch_review(
    brain: Any,
    *,
    final_text: str,
    exit_reason: str,
    trace: list[dict] | None,
    task_description: str = "",
    config: ViewSwitchConfig | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    视角切换审查点主入口（生产接入调用）。

    返回 (最终文本, 报告dict)。
    报告字段：triggered/trigger_reason/verdict/objection/verified/evidence_hit/
              repaired/review_ms/repair_ms/tool_calls。
    任何异常 → 返回 (final_text, {"triggered": False, "error": ...}) —— 原响应不变。
    """
    cfg = config or ViewSwitchConfig()
    report: dict[str, Any] = {
        "triggered": False,
        "trigger_reason": "",
        "verdict": "通过",
        "objection": "",
        "verified": False,
        "evidence_hit": False,
        "repaired": False,
        "review_ms": 0,
        "repair_ms": 0,
        "tool_calls": count_tool_calls(trace),
    }
    if not cfg.enabled or not final_text or not final_text.strip():
        return final_text, report

    # 1) 触发判定（未触发 = 零成本）
    trigger, reason = should_review(exit_reason, trace, final_text)
    if not trigger:
        report["trigger_reason"] = reason
        return final_text, report
    report["triggered"] = True
    report["trigger_reason"] = reason

    evidence = extract_evidence(trace, cfg.max_evidence_chars)
    review_prompt = build_review_prompt(task_description, final_text, evidence)

    # 2) 审查（三态 + 预算）
    t0 = time.time()
    try:
        resp = await brain.think_lightweight(
            system="你是严格的事实审查工程师。只依据提供的证据池作事实性判断，绝不臆测。",
            messages=[{"role": "user", "content": review_prompt}],
            max_tokens=cfg.max_review_tokens,
            temperature=cfg.temperature,
        )
        review_text = _clean_resp(resp)
    except Exception as exc:  # 审查失败 → 保守返回原响应
        report["error"] = f"review_call_failed: {exc}"
        logger.warning("[view_switch] 审查调用失败，维持原响应: %s", exc)
        return final_text, report
    report["review_ms"] = int((time.time() - t0) * 1000)

    state, objection, quotes = parse_verdict(review_text)
    report["verdict"] = state
    report["objection"] = objection

    # 3) 机器证据裁决（保守默认：证据真实性 + 异议锚定工件）
    verified, vreason = machine_verify(state, objection, quotes, evidence, final_text)
    report["verified"] = verified
    report["evidence_hit"] = verified
    report["machine_reason"] = vreason
    if not verified:
        logger.info(
            "[view_switch] 机器裁决拒绝（%s）→ 维持原判。verdict=%s objection=%s",
            vreason, state, objection[:80],
        )
        return final_text, report

    # 4) 有界修复（最多 cfg.max_repairs 次）
    t1 = time.time()
    repaired_text = final_text
    for _ in range(max(1, cfg.max_repairs)):
        try:
            rresp = await brain.think_lightweight(
                system="你是严谨的任务执行者。按修复指令修正事实性错误，保持其余内容不变。",
                messages=[{"role": "user", "content": build_repair_prompt(task_description, final_text, objection)}],
                max_tokens=cfg.max_repair_tokens,
                temperature=cfg.temperature,
            )
            candidate = _clean_resp(rresp)
        except Exception as exc:
            logger.warning("[view_switch] 修复调用失败，维持原响应: %s", exc)
            break
        if candidate and candidate != final_text and not _looks_like_echo(candidate, final_text):
            repaired_text = candidate
            report["repaired"] = True
        else:
            if candidate and (candidate != final_text):
                report["repair_rejected"] = "回显/截断防护"
            report["repaired"] = False
        break  # 有界：最多一次修复（连 2 次需补证升级语义 = 仍不满足则转人工/主模型）
    report["repair_ms"] = int((time.time() - t1) * 1000)
    logger.info(
        "[view_switch] 终审完成 verdict=%s verified=True repaired=%s objection=%s",
        state, report["repaired"], objection[:80],
    )
    return repaired_text, report
