"""
记忆语义方法逻辑（多层记忆 / 去重 / 接替 / 核心预算）

将已验证的记忆方法学（core-memory / memory-boundaries / time-aware-recall /
memory-trust），以及已在 `lcs-fusion-memory`（Rust crate，本机部署 HTTP 4014）
落地并验证的语义，移植进 OpenKitsune 自带的记忆系统。
纯逻辑模块，无 IO。

与 Rust 侧记忆引擎（`lcs-fusion-memory`）逐项对齐：

- **声明指纹** ``claim_fingerprint``：归一化文本指纹，用于精确去重、
  ``forget``/``purge`` 墓碑与后续同声明写入拒绝（Rust ``fact_fingerprint``）。
- **TTL 解析** ``parse_ttl``：时长简写（``30d``/``12h``/``45m``/``7w``/``1y``）
  或裸秒数 → ``valid_until`` epoch 秒（Rust ``remember.ttl``）。
- **问题相关性** ``term_share`` / ``is_dated_fact`` / ``score_question``：
  整词共享比 + 0.1 日期加成（Rust ``scoreFactCandidates``）。
- **准入规则** ``admitted_facts_arm``：实体命中 或 余弦 ≥ 0.6 或 词共享 ≥ 0.34
  （Rust ``QUESTION_ADMISSION_RULES.facts_arm``）。
- **核心记忆预算** ``CoreBudget``：always-load 块渲染 + 超预算裁剪
  （Rust ``memory.core.max_chars``，默认 4000 字符）。
- **去重/接替决策** ``dedup_decision``：精确指纹重复 / 余弦近重复 /
  同实体同类型语义接替（Rust ``remember`` 的 duplicate / superseded 状态机）。
- **5 层记忆** ``LAYER_ORDER``：core / working / short_term / long_term / facts。
- **信任层级** ``trust_for_origin`` / ``trust_label``（Rust ``memory-trust``）。

所有函数为纯函数（除 tokenize 的 jieba 可选缓存外无副作用），
可直接单测，与 Rust 端测试用例一一对应。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

__all__ = [
    "TERM_STUFFING_RATIO",
    "DATED_MIN_SECS",
    "DEDUP_COSINE",
    "SUPERSEDE_COSINE",
    "ADMISSION_COSINE",
    "ADMISSION_TERM_SHARE",
    "DATED_BONUS",
    "CORE_MAX_CHARS",
    "LAYER_ORDER",
    "KIND_WHITELIST",
    "STATUS_ACTIVE",
    "STATUS_SUPERSEDED",
    "STATUS_EXPIRED",
    "STATUS_FORGOTTEN",
    "STATUS_PURGED",
    "tokenize_mixed",
    "claim_fingerprint",
    "normalize_claim",
    "parse_ttl",
    "term_share",
    "is_dated_fact",
    "score_question",
    "admitted_facts_arm",
    "DedupDecision",
    "SupersedeTarget",
    "DedupCandidate",
    "dedup_decision",
    "CoreBudget",
    "CoreRow",
    "core_title",
    "looks_like_instruction",
    "is_fact_kind",
    "trust_label",
    "trust_for_origin",
]

# ---------------------------------------------------------------------------
# 常量（与 Rust 侧 config.rs / 记忆引擎默认值一致）
# ---------------------------------------------------------------------------

TERM_STUFFING_RATIO = 3.0
"""词堆砌防护比率（事实词数 / 3 参与分母，防止长文本堆砌刷分）。"""

DATED_MIN_SECS = 24 * 60 * 60
"""带日期事实判定阈值（valid_from 与 created_at 相差超过 24h 视为「写者给定日期」）。"""

DEDUP_COSINE = 0.95
"""余弦 ≥ 0.95 → 近重复，跳过写入。"""

SUPERSEDE_COSINE = 0.85
"""同实体同类型 + 文本不同 + 余弦 ≥ 0.85 → 新事实接替旧事实。"""

ADMISSION_COSINE = 0.60
"""事实臂准入：余弦 ≥ 0.60。"""

ADMISSION_TERM_SHARE = 0.34
"""事实臂准入：词共享 ≥ 0.34。"""

DATED_BONUS = 0.10
"""带日期事实的相关性加成。"""

CORE_MAX_CHARS = 4000
"""核心记忆预算（Rust memory.core.max_chars 默认）。"""

LAYER_ORDER = ["core", "working", "short_term", "long_term", "facts"]
"""5 层记忆显示顺序（对应 Rust types.rs LAYER_CORE/…/LAYER_FACTS）。"""

KIND_WHITELIST = frozenset({"event", "preference", "commitment", "belief", "fact"})
"""事实层 kind 白名单（Rust is_fact_kind 对应集合）。"""

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_EXPIRED = "expired"
STATUS_FORGOTTEN = "forgotten"
STATUS_PURGED = "purged"

# ---------------------------------------------------------------------------
# 中英文混合分词（与 Rust bm25.rs 逐字对齐）
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_SEPARATOR_CHARS = frozenset("_-.，； \t\n\r")


def _is_separator(ch: str) -> bool:
    return ch in _SEPARATOR_CHARS


def tokenize_mixed(text: str) -> list[str]:
    """中英文混合分词：英文/数字按分隔符切词（≥2 字符），中文 CJK 2-char 滑窗。"""
    if not text:
        return []

    tokens: list[str] = []

    # 英文/数字段：分隔符 → 空格 → 单词
    normalized = "".join(" " if _is_separator(ch) else ch for ch in text)
    for word in normalized.split():
        cleaned = "".join(ch for ch in word if ch.isascii() and ch.isalnum()).lower()
        if len(cleaned) >= 2:
            tokens.append(cleaned)

    # 中文 CJK 2-char 滑窗
    chars = list(text)
    i = 0
    while i + 1 < len(chars):
        if _CJK_RE.match(chars[i]) and _CJK_RE.match(chars[i + 1]):
            tokens.append(chars[i] + chars[i + 1])
            i += 1
        else:
            i += 1

    return tokens


# ---------------------------------------------------------------------------
# 声明指纹（Rust fact_fingerprint）
# ---------------------------------------------------------------------------

def normalize_claim(text: str) -> str:
    """归一化声明文本：去首尾空白、折叠内部空白、转小写（保留标点）。"""
    out: list[str] = []
    prev_space = False
    for ch in text:
        if ch.isspace():
            if not prev_space and out:
                out.append(" ")
            prev_space = True
        else:
            out.append(ch.lower())
            prev_space = False
    result = "".join(out)
    if result.endswith(" "):
        result = result[:-1]
    return result


def claim_fingerprint(text: str) -> str:
    """归一化后 sha256 前 16 字节（32 hex）。用于精确去重与墓碑。"""
    normalized = normalize_claim(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return digest[:16].hex()


# ---------------------------------------------------------------------------
# TTL 解析
# ---------------------------------------------------------------------------

def parse_ttl(ttl: str | None, now: int | None = None) -> int | None:
    """解析 TTL：时长简写（``45m``/``12h``/``30d``/``7w``/``1y``，也支持裸秒数）。

    返回 ``valid_until`` epoch 秒；无法解析返回 None。
    """
    if ttl is None:
        return None
    ttl = ttl.strip()
    if not ttl:
        return None
    now = int(now) if now is not None else _epoch_now()

    # 裸整数（秒）
    if ttl.isdigit() or (ttl.startswith("-") and ttl[1:].isdigit()):
        try:
            return now + int(ttl)
        except ValueError:
            return None

    unit = ttl[-1]
    num_str = ttl[:-1].strip()
    if not num_str:
        return None
    try:
        num = int(num_str)
    except ValueError:
        return None
    if num < 0:
        return None
    secs = {
        "s": num,
        "m": num * 60,
        "h": num * 3600,
        "d": num * 86400,
        "w": num * 7 * 86400,
        "y": num * 365 * 86400,
    }.get(unit)
    if secs is None:
        return None
    return now + secs


def _epoch_now() -> int:
    import time

    return int(time.time())


# ---------------------------------------------------------------------------
# 问题相关性（Rust scoreFactCandidates）
# ---------------------------------------------------------------------------

def term_share(question: str, fact: str) -> float:
    """问题与事实的整词共享比。

    ``matched / max(question_terms, ceil(fact_terms / TERM_STUFFING_RATIO))``；
    问题无词时返回 0。
    """
    q_terms = tokenize_mixed(question)
    if not q_terms:
        return 0.0
    f_terms = tokenize_mixed(fact)
    q_set = set(q_terms)
    f_set = set(f_terms)
    matched = len(q_set & f_set)
    denominator = max(len(q_set), len(f_set) / TERM_STUFFING_RATIO, 1.0)
    return matched / denominator


def is_dated_fact(valid_from: int | None, created_at: int) -> bool:
    """是否「写者给定日期」：valid_from 与创建时间相差超过 24h。"""
    if valid_from is None:
        return False
    return abs(valid_from - created_at) > DATED_MIN_SECS


def score_question(cosine: float, share: float, dated: bool, dated_bonus: float = DATED_BONUS) -> float:
    """问题相关性总分：cosine + term_share + （dated ? 0.1 : 0）。"""
    return cosine + share + (dated_bonus if dated else 0.0)


def admitted_facts_arm(
    has_entity: bool,
    cosine: float,
    share: float,
    admission_cosine: float = ADMISSION_COSINE,
    admission_term_share: float = ADMISSION_TERM_SHARE,
) -> bool:
    """事实臂准入（Rust ``facts_arm`` 规则）：实体命中 → 通过；否则 余弦 ≥ 0.60 或 词共享 ≥ 0.34。"""
    return has_entity or cosine >= admission_cosine or share >= admission_term_share


# ---------------------------------------------------------------------------
# 去重/接替决策（Rust remember 状态机）
# ---------------------------------------------------------------------------

class DedupDecision(Enum):
    """去重/接替决策结果。"""

    INSERT = "inserted"
    """唯一新写入。"""

    DUPLICATE = "duplicate"
    """与活跃事实重复（精确指纹 或 余弦 ≥ dedup_cosine）。"""

    SUPERSEDE = "superseded"
    """同实体同类型且语义近接（余弦 ≥ supersede_cosine 且文本不同）→ 新事实接替旧事实。"""


class SupersedeTarget:
    """接替决策结果（携带被接替的旧事实 id）。

    与 Rust 侧 ``DedupDecision::Supersede { old_id }`` 对应；当
    ``dedup_decision`` 判定为接替时返回本对象（而不是裸枚举值），
    调用方通过 ``.old_id`` 拿到旧 id 做状态迁移。
    """

    name = "SUPERSEDE"

    def __init__(self, old_id: str) -> None:
        self.old_id = old_id

    def __repr__(self) -> str:
        return f"SupersedeTarget(old_id={self.old_id!r})"


@dataclass(frozen=True)
class DedupCandidate:
    """去重候选（store 层查出的同 scope 活跃事实）。"""

    id: str
    fingerprint: str
    text: str
    entity: str
    kind: str
    cosine: float


def dedup_decision(
    fingerprint: str,
    text: str,
    entity: str,
    kind: str,
    candidates: Iterable[DedupCandidate],
    dedup_cosine: float = DEDUP_COSINE,
    supersede_cosine: float = SUPERSEDE_COSINE,
) -> DedupDecision | str:
    """基于候选旧事实做去重/接替决策。

    返回 ``DedupDecision.INSERT`` / ``DedupDecision.DUPLICATE`` / ``DedupDecision.SUPERSEDE``；
    为向后兼容也接受字符串，接替时旧 id 在 ``superseded_old_id`` 字段由调用方保存。
    """
    best_supersede: tuple[DedupCandidate, float] | None = None
    for c in candidates:
        if c.fingerprint == fingerprint:
            return DedupDecision.DUPLICATE
        if c.cosine >= dedup_cosine:
            return DedupDecision.DUPLICATE
        same_entity = bool(c.entity) and c.entity == entity
        same_kind = bool(c.kind) and c.kind == kind
        diff_text = c.text != text
        if same_entity and same_kind and diff_text and c.cosine >= supersede_cosine:
            if best_supersede is None or c.cosine > best_supersede[1]:
                best_supersede = (c, c.cosine)
    if best_supersede is not None:
        return SupersedeTarget(best_supersede[0].id)
    return DedupDecision.INSERT

# ---------------------------------------------------------------------------
# 核心记忆预算（Rust memory.core.max_chars）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CoreRow:
    """核心记忆块行。"""

    id: str
    text: str
    source: str
    core_priority: int = 0


@dataclass
class CoreBudget:
    """核心记忆块预算渲染。按 ``core_priority`` 升序再按 id 排序拼接；超预算停止。"""

    max_chars: int = CORE_MAX_CHARS

    def render(self, rows: Iterable[CoreRow]) -> tuple[str, int, bool]:
        """返回 (rendered, used_chars, truncated)。"""
        sorted_rows = sorted(rows, key=lambda r: (r.core_priority, r.id))
        out_parts: list[str] = []
        used = 0
        truncated = False
        for r in sorted_rows:
            block = f"## {r.id} — {r.source}\n{r.text}\n\n"
            if used + len(block) > self.max_chars and out_parts:
                truncated = True
                break
            out_parts.append(block)
            used += len(block)
        return "".join(out_parts), used, truncated


def core_title(text: str) -> str:
    """从记忆文本中提取核心记忆条目标题（首行非空行，截断 40 字符）。"""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:40]
    return "记忆"


_INSTRUCTION_MARKERS = (
    "以后",
    "从现在起",
    "请记住",
    "你必须",
    "忽略之前的指令",
    "ignore your previous",
    "from now on",
    "always recommend",
    "always answer",
)


def looks_like_instruction(text: str) -> bool:
    """判断文本是否像「对 agent 的指令」（写门控的确定性检测，保守规则）。"""
    t = text.strip().lower()
    return any(marker in t for marker in _INSTRUCTION_MARKERS)


# ---------------------------------------------------------------------------
# 事实层 / 信任层级
# ---------------------------------------------------------------------------

def is_fact_kind(kind: str) -> bool:
    """记忆条目是否属于事实层（kind 白名单）。"""
    return kind in KIND_WHITELIST


TRUST_USER_CONFIRMED = "user_confirmed"
TRUST_OPERATOR_CURATED = "operator_curated"
TRUST_TOOL_OBSERVED = "tool_observed"
TRUST_AGENT_WRITTEN = "agent_written"
TRUST_EXTERNAL_UNTRUSTED = "external_untrusted"


def trust_label(tier: str) -> str:
    """信任层级中文标签。"""
    return {
        TRUST_USER_CONFIRMED: "你确认的",
        TRUST_OPERATOR_CURATED: "你的笔记",
        TRUST_TOOL_OBSERVED: "工具数据",
        TRUST_AGENT_WRITTEN: "agent 写入",
        TRUST_EXTERNAL_UNTRUSTED: "外部未信任",
    }.get(tier, "未验证来源")


def trust_for_origin(content_origin: str) -> str:
    """``content_origin`` → 信任层级（对应 Rust ``remember.content_origin``）。"""
    origin = content_origin.strip()
    if origin == "tool_output":
        return TRUST_EXTERNAL_UNTRUSTED
    return TRUST_AGENT_WRITTEN
