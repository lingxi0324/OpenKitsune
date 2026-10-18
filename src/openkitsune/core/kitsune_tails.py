"""
九尾内核 · 运行态九尾（kitsune_tails）

把 V2.0 九尾映射从「文档 / 提示词资产」提升为「运行态协调模块」：

  九尾并行推演（各自 try/except 隔离，任何尾异常不影响主流程）
    → 中宫狐心冲突裁决（风控一票否决 / 伦理拒绝优先 / 情绪决定模式）
    → 九宫收敛为 HeartVerdict（单一结构化心判）
    → 对话前注入 prompt（prompt/kitsune_section.py 渲染）
    → 对话后复盘闭环（ReviewTail 六问落盘 + 改进项回写 MEMORY.md）

数据落点：data/kitsune/（goals.json / growth.md / evolution_notes.md / metrics.json）
设计约束：全部确定性优先、可降级；无 LLM 硬依赖；导入全部惰性化，import 本模块零副作用。

对应整改方案：《OpenKitsune_九尾内核整改方案V3_20261016.md》
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 路径与工具
# ═══════════════════════════════════════════════════════════════════


def _resolve_root() -> Path:
    """解析 OpenKitsune 仓库根目录（identity/MEMORY.md 与 data/ 的基准）。"""
    try:
        from openkitsune.config import settings

        pr = getattr(settings, "project_root", None)
        if pr is not None:
            return Path(pr)
    except Exception:
        pass
    return Path(__file__).resolve().parents[3]


def _kitsune_dir() -> Path:
    d = _resolve_root() / "data" / "kitsune"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Kitsune] mkdir failed: %s", e)
    return d


_file_lock = threading.Lock()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.debug("[Kitsune] read json failed %s: %s", path, e)
    return default


def _write_json(path: Path, data: Any) -> bool:
    try:
        with _file_lock:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("[Kitsune] write json failed %s: %s", path, e)
        return False


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _bigrams(text: str) -> set[str]:
    """中文友好的轻量词元（双字窗口），用于确定性相关度。"""
    text = re.sub(r"[\s，。、；：？！,.!?;:\"'“”‘’（）()【】\[\]<>《》\-_—]+", "", text or "")
    return {text[i : i + 2] for i in range(max(0, len(text) - 1))}


def _overlap(a: str, b: str) -> int:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0
    return len(ba & bb)


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TailResult:
    """单尾输出（统一外壳，保证互不污染）。"""

    tail: str
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    priority: int = 5

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error}


# ═══════════════════════════════════════════════════════════════════
# 1 · 战略尾 — 长期布局、目标拆解、跨会话
# ═══════════════════════════════════════════════════════════════════


class StrategyTail:
    """战略尾：跨会话长期目标（目标+关键结果）存储、召回、进度回写。"""

    name = "战略尾"

    def __init__(self, data_dir: Path | None = None):
        self._dir = Path(data_dir) if data_dir is not None else _kitsune_dir()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("[战略尾] mkdir failed: %s", e)
        self._goals_file = self._dir / "goals.json"

    # ── 存储 ──────────────────────────────────────────────

    def _load(self) -> list[dict]:
        goals = _read_json(self._goals_file, [])
        return goals if isinstance(goals, list) else []

    def _save(self, goals: list[dict]) -> bool:
        return _write_json(self._goals_file, goals)

    def add_goal(self, goal: str, why: str = "", krs: list[str] | None = None) -> str:
        """新增长期目标。返回 goal_id。"""
        goal = (goal or "").strip()
        if not goal:
            return ""
        goals = self._load()
        gid = f"g{int(datetime.now().timestamp() * 1000)}"
        goals.append(
            {
                "id": gid,
                "goal": goal,
                "why": why,
                "krs": [{"kr": kr, "status": "open", "updated": ""} for kr in (krs or [])],
                "status": "active",
                "created_at": _iso_now(),
                "updated_at": _iso_now(),
                "progress_notes": [],
            }
        )
        self._save(goals)
        return gid

    def touch_goal(self, goal_id: str, note: str = "") -> bool:
        """记录一次目标进展（收尾时调用）。"""
        goals = self._load()
        for g in goals:
            if g.get("id") == goal_id:
                g["updated_at"] = _iso_now()
                if note:
                    notes = g.setdefault("progress_notes", [])
                    notes.append(f"[{_iso_now()}] {note}")
                    notes[:] = notes[-20:]
                return self._save(goals)
        return False

    def complete_kr(self, goal_id: str, kr_text: str) -> bool:
        """把一条关键结果标记为完成。"""
        goals = self._load()
        for g in goals:
            if g.get("id") == goal_id:
                for kr in g.get("krs", []):
                    if kr.get("kr") == kr_text:
                        kr["status"] = "done"
                        kr["updated"] = _iso_now()
                g["updated_at"] = _iso_now()
                return self._save(goals)
        return False

    # ── 召回 ──────────────────────────────────────────────

    def recall_relevant(self, message: str, top_k: int = 3) -> list[dict]:
        """按相关度召回当前对话相关的在途目标（active 且未全完成）。"""
        message = (message or "").strip()
        goals = [g for g in self._load() if g.get("status") == "active"]
        if not goals:
            return []
        scored = []
        for g in goals:
            text = f"{g.get('goal','')} {g.get('why','')} " + " ".join(
                kr.get("kr", "") for kr in g.get("krs", [])
            )
            scored.append((_overlap(message, text), g))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": g.get("id"),
                "goal": g.get("goal"),
                "why": g.get("why"),
                "kr_done": sum(1 for kr in g.get("krs", []) if kr.get("status") == "done"),
                "kr_total": len(g.get("krs", [])),
                "updated_at": g.get("updated_at"),
            }
            for s, g in scored[:top_k]
            if s > 0
        ]


# ═══════════════════════════════════════════════════════════════════
# 2 · 心理尾 — 情绪识别 + 潜台词洞察 + 隐性需求 + 交互模式
# ═══════════════════════════════════════════════════════════════════

# 场景规则（确定性潜台词层，补词典匹配之不足）。
# 结构：(正则, 场景名, 潜台词列表, 隐性需求列表, 交互模式)
_SUBTEXT_RULES: list[tuple[re.Pattern, str, list[str], list[str], str]] = [
    (
        re.compile(r"方案被[否毙]|被否|被拒|又没通过|又被拒|又没中"),
        "价值否定",
        ["力气被否定", "渴望被认可"],
        ["被认可", "重整方案"],
        "温柔共情",
    ),
    (
        re.compile(r"加班到深夜|熬夜|又加班|凌晨才|加班到"),
        "疲惫透支",
        ["疲惫", "需要被体谅"],
        ["被理解", "收尾休息"],
        "温柔共情",
    ),
    (
        re.compile(r"算了|随它吧|无所谓了|就这样吧|不搞了"),
        "无力放弃",
        ["回避决策", "心力不足"],
        ["被托住", "帮做决定"],
        "情绪疏导",
    ),
    (
        re.compile(r"又出问题|又失败了|还是不行|又错了|又翻车"),
        "反复挫败",
        ["自责", "怕再失败"],
        ["被肯定", "可行小步"],
        "温柔共情",
    ),
    (
        re.compile(r"好烦|烦死|受不了|忍不了|太气人|气死我了"),
        "烦躁积压",
        ["情绪积压", "想被倾听"],
        ["倾听", "梳理出口"],
        "情绪疏导",
    ),
    (
        re.compile(r"不会|不懂|没学过|想学|怎么入门|教教我|求带"),
        "求知上进",
        ["怕露怯", "要方法"],
        ["指导", "清晰路径"],
        "教学引导",
    ),
    (
        re.compile(r"帮我看看|你确认下|帮我检查|帮我审|帮我核对"),
        "需要确认",
        ["不确定", "要第三方校验"],
        ["确认", "校验"],
        "简洁高效",
    ),
    (
        re.compile(r"纠结|拿不准|哪个好|要不要|选哪个|怎么办"),
        "选择困难",
        ["怕选错", "要多路径"],
        ["推演", "明确建议"],
        "决策推演",
    ),
    (
        re.compile(r"随便|都行|你看着办"),
        "回避决策",
        ["不想担责", "信任你"],
        ["被代劳", "明确建议"],
        "兜底容错",
    ),
]

_NEGATIVE_EMOTIONS = {"anger", "grief", "fear"}


class PsychologicalTail:
    """心理尾：词典层（EmotionPerceiver，快而稳）＋ 场景潜台词层。"""

    name = "心理尾"

    def perceive(self, message: str) -> dict:
        """输出结构化感知：情绪 / 强度 / 潜台词 / 隐性需求 / 交互模式。"""
        message = (message or "").strip()
        emotion: dict[str, Any] = {
            "dominant": "calm",
            "label": "平静",
            "intensity": "none",
            "confidence": 0.0,
            "negative": False,
        }
        # 1. 词典层（保留 EmotionPerceiver）
        try:
            from .emotion_perceiver import perceive as _perceive

            p = _perceive(message)
            if p is not None and p.is_active():
                emotion = {
                    "dominant": p.dominant,
                    "label": p.dominant_label,
                    "intensity": p.intensity_level,
                    "confidence": round(p.confidence, 3),
                    "negative": p.dominant in _NEGATIVE_EMOTIONS,
                }
        except Exception as e:  # noqa: BLE001
            logger.debug("[心理尾] emotion_perceiver: %s", e)

        # 2. 潜台词层（场景规则）
        subtext: list[str] = []
        needs: list[str] = []
        mode = ""
        for pattern, scene, sub, nd, m in _SUBTEXT_RULES:
            if pattern.search(message):
                if scene not in subtext:
                    subtext.append(scene)
                for s in sub:
                    if s not in subtext:
                        subtext.append(s)
                for n in nd:
                    if n not in needs:
                        needs.append(n)
                mode = m
                break  # 首个命中的场景优先，避免多规则叠加噪音

        # 3. 模式兜底（未命中场景时按情绪极性）
        if not mode:
            if emotion["negative"]:
                mode = "温柔共情"
            elif emotion["dominant"] == "worry":
                mode = "决策推演"
            elif emotion["confidence"] > 0.3 and emotion["dominant"] == "joy":
                mode = "简洁高效"
            else:
                mode = "兜底容错"

        return {
            "emotion": emotion,
            "subtext": subtext[:4],
            "needs": needs[:4],
            "mode": mode,
        }


# ═══════════════════════════════════════════════════════════════════
# 3 · 创意尾 — 发散 → 收敛（狐心裁决入口）
# ═══════════════════════════════════════════════════════════════════

_CREATIVE_ANGLES = [
    ("用户视角", "先站用户立场，把「{m}」拆成他最在意的一个结果，倒推达成路径"),
    ("反方视角", "先假设「{m}」不可行，找出最大阻力，再逐个击破"),
    ("最小可行", "把「{m}」切成 15 分钟能完成的最小一步"),
    ("长期视角", "想「{m}」三个月后希望成为的样子，反推今天该做什么"),
    ("资源约束", "用现有工具/时间/精力最省地完成「{m}」"),
    ("风险规避", "列出「{m}」最可能翻车的 3 个点，逐一设计兜底"),
]


class CreativeTail:
    """创意尾：六视角发散 → 确定性收敛打分 → 交狐心裁决。"""

    name = "创意尾"

    def diverge(self, message: str) -> list[dict]:
        message = (message or "").strip()[:60]
        if not message:
            return []
        return [
            {"angle": angle, "idea": tmpl.format(m=message)}
            for angle, tmpl in _CREATIVE_ANGLES
        ]

    def converge(
        self, options: list[dict], *, risk_level: str = "low", top_k: int = 3
    ) -> list[dict]:
        """收敛：新颖性（视角差异）+ 展开度 + 风控惩罚，确定性打分。"""
        scored = []
        for i, opt in enumerate(options):
            idea = opt.get("idea", "")
            angle = opt.get("angle", "")
            novelty = 0.08 * (i % 3)  # 视角轮换的新颖度微差
            depth = min(len(idea) / 45.0, 0.35)
            risk_penalty = 0.25 if risk_level in ("high", "critical") else (
                0.1 if risk_level == "medium" else 0.0
            )
            score = round(min(0.95, 0.45 + novelty + depth - risk_penalty), 3)
            scored.append({"angle": angle, "idea": idea, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


# ═══════════════════════════════════════════════════════════════════
# 4 · 风控尾 — 风险预判、边界识别（prompt 面向汇总；强制层仍在 policy_v2）
# ═══════════════════════════════════════════════════════════════════

_CRITICAL_RISK = [
    re.compile(r"rm\s+-rf|格式化.*盘|清空.*盘|删除.*系统|销毁.*数据"),
    re.compile(r"删库|清库|drop\s+table|truncate"),
]
_HIGH_RISK = [
    re.compile(r"删除|删掉|删了|覆盖|清空|清掉|移除|卸载|重置|格式化|清盘"),
    re.compile(r"转账|付款|打款|汇款|充值"),
    re.compile(r"发布|上线|部署到生产|公网|对外发布"),
]
_SENSITIVE = [
    re.compile(r"密码|密钥|token|cookie|session|验证码"),
    re.compile(r"翻墙|破解|入侵|攻击|爆破|撞库"),
]


class RiskControlTail:
    """风控尾：确定性风险分级（low/medium/high/critical）+ 提示给模型。"""

    name = "风控尾"

    def assess(self, message: str) -> dict:
        message = (message or "").strip()
        flags: list[str] = []
        level = "low"
        for p in _CRITICAL_RISK:
            if p.search(message):
                flags.append("不可逆破坏性操作")
                level = "critical"
                break
        if level != "critical":
            for p in _HIGH_RISK:
                if p.search(message):
                    flags.append("删除/覆盖/资金/发布类高影响操作")
                    level = "high"
                    break
        if level == "low":
            for p in _SENSITIVE:
                if p.search(message):
                    flags.append("敏感信息或越权行为")
                    level = "medium"
                    break
        return {
            "level": level,
            "flags": flags,
            "blocked": level in ("high", "critical"),
            "note": "风控强制层（policy_v2/confirmation）不受本判定影响，此处仅供 prompt 提示与裁决参考",
        }


# ═══════════════════════════════════════════════════════════════════
# 5 · 执行尾 — 落地步骤、工具编排提示（真正执行仍在 tools/orchestrator）
# ═══════════════════════════════════════════════════════════════════

_EXEC_TOOL_HINTS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"搜索|查一下|找找|搜一下|查资料|看看.*消息", re.IGNORECASE), ["general_search / web_search", "baidu-search"]),
    (re.compile(r"写|生成|创建|新建|起草"), ["write_file", "edit_file"]),
    (re.compile(r"python|脚本|代码|程序|函数|接口", re.IGNORECASE), ["run_shell(python)", "write_file"]),
    (re.compile(r"表格|excel|sheet|csv|数据表", re.IGNORECASE), ["sheet / xlsx"]),
    (re.compile(r"ppt|幻灯片|演示|汇报", re.IGNORECASE), ["ppt"]),
    (re.compile(r"文档|docx|word|报告", re.IGNORECASE), ["docx / word"]),
    (re.compile(r"图片|海报|logo|头像|插画|封面", re.IGNORECASE), ["image 生成/设计"]),
    (re.compile(r"视频|剪辑|短片|宣传片", re.IGNORECASE), ["视频生成/编辑"]),
    (re.compile(r"邮件|发送.*邮件", re.IGNORECASE), ["email"]),
    (re.compile(r"翻译|中译|英译", re.IGNORECASE), ["translate"]),
    (re.compile(r"会议|日程|日历|邀约"), ["calendar / meeting"]),
]

_EXEC_STEPS = [
    "澄清目标与边界（必要时一句确认）",
    "检索/取数（记忆、搜索、附件）",
    "生成主干方案或产物",
    "验证（语法/回读/抽样）",
    "交付并说明验证方式",
]


class ExecutionTail:
    """执行尾：步骤骨架 + 工具提示（确定性）。"""

    name = "执行尾"

    def plan_steps(self, message: str) -> dict:
        message = (message or "").strip()
        hints: list[str] = []
        for pattern, tools in _EXEC_TOOL_HINTS:
            if pattern.search(message):
                for t in tools:
                    if t not in hints:
                        hints.append(t)
        return {
            "steps": list(_EXEC_STEPS),
            "tool_hints": hints[:6],
            "apply": True,  # 狐心裁决后可改为 False（需确认/拒绝）
        }


# ═══════════════════════════════════════════════════════════════════
# 6 · 伦理尾 — 底线守护 + 正向引导 + 成长本能
# ═══════════════════════════════════════════════════════════════════

_ETHICS_REFUSE = [
    re.compile(r"炸弹|炸药|毒[品物]|冰毒|海洛因|制毒"),
    re.compile(r"儿童.*(色情|裸|性)|恋童"),
    re.compile(r"人肉搜索|开盒|社工库"),
    re.compile(r"钓鱼链接|诈骗话术|杀猪盘|洗钱"),
    re.compile(r"攻击.*(政府|关键基础设施)|入侵.*(系统|服务器)|破解.*(密码|账号)"),
]

_ETHICS_WARN = [
    re.compile(r"骂|诅咒|诋毁|造谣|抹黑"),
    re.compile(r"泄露|窃取|盗用"),
]

_GUIDANCE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"累|疲惫|熬|加班"), "先接住情绪：确实辛苦了，先歇口气；需要的话我帮你把这件事拆小或归档。"),
    (re.compile(r"失败|被否|被拒|没做好|又错"), "温和纠正：一次结果不代表能力，从最小一步重新来即可。"),
    (re.compile(r"烦|生气|气死|受不了"), "先共情再疏导：这份烦是正常的，先说出来，我们再一起理。"),
    (re.compile(r"纠结|选|拿不准|怎么办"), "给可选项而非替 TA 决定：列两三条路径与利弊，让 TA 保有掌控感。"),
    (re.compile(r"想学|不会|怎么入门|求带"), "给成长路径：最小入门步骤 + 可查资料 + 一句鼓励。"),
]

_GROWTH_PATTERNS = [
    re.compile(r"(想学|想了解|想掌握|不会|没学过|不知道怎么)([^，。！？]{2,30})"),
]


class EthicalTail:
    """伦理尾：边界判定（refuse/warn/ok）+ 正向引导话术 + 成长本能记录。"""

    name = "伦理尾"

    def __init__(self, data_dir: Path | None = None):
        self._dir = Path(data_dir) if data_dir is not None else _kitsune_dir()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("[伦理尾] mkdir failed: %s", e)
        self._growth_file = self._dir / "growth.md"

    def check(self, message: str) -> dict:
        message = (message or "").strip()
        for p in _ETHICS_REFUSE:
            if p.search(message):
                return {
                    "verdict": "refuse",
                    "reasons": ["触及安全底线（拒绝类）"],
                    "matched": p.pattern,
                }
        for p in _ETHICS_WARN:
            if p.search(message):
                return {
                    "verdict": "warn",
                    "reasons": ["涉低俗/攻击/隐私风险，需温和纠正"],
                    "matched": p.pattern,
                }
        return {"verdict": "ok", "reasons": [], "matched": ""}

    def guidance(self, message: str) -> str:
        message = (message or "").strip()
        for pattern, g in _GUIDANCE_RULES:
            if pattern.search(message):
                return g
        return ""

    # ── 成长本能：记录「想学会 X」 ────────────────────────

    def growth_hints(self, message: str) -> list[str]:
        message = (message or "").strip()
        hits: list[str] = []
        for p in _GROWTH_PATTERNS:
            for m in p.finditer(message):
                topic = (m.group(2) or "").strip()
                if topic and topic not in hits:
                    hits.append(f"想学/想了解：{topic}")
        if hits:
            self._append_growth(hits)
        return hits

    def _append_growth(self, hits: list[str]) -> None:
        try:
            with _file_lock:
                lines: list[str] = []
                if self._growth_file.exists():
                    lines = self._growth_file.read_text(encoding="utf-8").splitlines()
                for h in hits:
                    line = f"- [{_iso_now()[:10]}] {h}"
                    if line not in lines:
                        lines.append(line)
                lines[:] = lines[-200:]
                self._growth_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.debug("[伦理尾] growth append failed: %s", e)


# ═══════════════════════════════════════════════════════════════════
# 7 · 记忆尾 — 长期记忆召回 + 召回埋点
# ═══════════════════════════════════════════════════════════════════


class MemoryTail:
    """记忆尾：惰性调用记忆检索，输出 Top-k 事实 + 召回统计埋点。"""

    name = "记忆尾"

    def __init__(self, data_dir: Path | None = None, retriever: Callable[[str], list[str]] | None = None):
        self._dir = Path(data_dir) if data_dir is not None else _kitsune_dir()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("[记忆尾] mkdir failed: %s", e)
        self._retriever = retriever
        self._metrics_file = self._dir / "metrics.json"

    def set_retriever(self, retriever: Callable[[str], list[str]]) -> None:
        self._retriever = retriever

    def recall(self, message: str, top_k: int = 3) -> list[str]:
        message = (message or "").strip()
        self._bump("memory_recall_calls")
        # 短消息/寒暄不触发向量检索（避免闲聊路径的无谓延迟）
        if len(message) < 4 or self._retriever is None:
            return []
        try:
            facts = self._retriever(message)[:top_k]
            if facts:
                self._bump("memory_recall_hits")
            return facts
        except Exception as e:  # noqa: BLE001
            logger.debug("[记忆尾] recall failed: %s", e)
            return []

    def _bump(self, key: str) -> None:
        metrics = _read_json(self._metrics_file, {})
        metrics[key] = int(metrics.get(key, 0)) + 1
        _write_json(self._metrics_file, metrics)


# ═══════════════════════════════════════════════════════════════════
# 8 · 工具尾 — 技能/工具调度建议（独立于执行尾）
# ═══════════════════════════════════════════════════════════════════

_TOOL_TAIL_MAP: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"搜索|查一下|找找|搜一下|热点|新闻", re.IGNORECASE), ["通用搜索/联网检索", "baidu-search"]),
    (re.compile(r"ppt|幻灯片|汇报|演示", re.IGNORECASE), ["ppt（飞书幻灯片）", "ppt-creator"]),
    (re.compile(r"表格|excel|sheet|csv|记账|统计", re.IGNORECASE), ["sheet/xlsx", "数据可视化"]),
    (re.compile(r"文档|docx|word|报告|纪要|复盘", re.IGNORECASE), ["docx/word", "飞书文档"]),
    (re.compile(r"图片|海报|logo|头像|插画|封面|壁纸", re.IGNORECASE), ["图像生成/设计", "图片理解"]),
    (re.compile(r"视频|剪辑|短片|宣传片|直播", re.IGNORECASE), ["视频生成/编辑", "视频解析"]),
    (re.compile(r"音频|录音|语音|配音"), ["音频处理", "录音转写"]),
    (re.compile(r"翻译|中译|英译|多语言"), ["翻译"]),
    (re.compile(r"代码|python|脚本|程序|接口|测试", re.IGNORECASE), ["代码/脚本执行", "代码检索"]),
    (re.compile(r"邮件|发信|收件箱", re.IGNORECASE), ["邮件"]),
    (re.compile(r"日历|会议|日程|邀约"), ["日历/会议"]),
    (re.compile(r"任务|待办|todo|清单", re.IGNORECASE), ["任务/清单"]),
]


class ToolTail:
    """工具尾：按意图建议技能/工具（静态映射 + catalog 扫描，独立于执行）。"""

    name = "工具尾"

    def __init__(self, root: Path | None = None):
        self._root = Path(root) if root is not None else _resolve_root()

    def suggest_tools(self, message: str) -> list[str]:
        message = (message or "").strip()
        hits: list[str] = []
        for pattern, tools in _TOOL_TAIL_MAP:
            if pattern.search(message):
                for t in tools:
                    if t not in hits:
                        hits.append(t)
        if not hits:
            return []
        return hits[:6]

    def list_categories(self, limit: int = 8) -> list[str]:
        """扫描 skills/catalog.json 的分类（尽力而为，失败返回空）。"""
        try:
            catalog = self._root / "skills" / "catalog.json"
            if not catalog.exists():
                return []
            data = json.loads(catalog.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("skills", data.get("items", []))
            cats: list[str] = []
            for it in items if isinstance(items, list) else []:
                c = it.get("category") or it.get("group") or ""
                if c and c not in cats:
                    cats.append(c)
            return cats[:limit]
        except Exception as e:  # noqa: BLE001
            logger.debug("[工具尾] catalog scan failed: %s", e)
            return []


# ═══════════════════════════════════════════════════════════════════
# 9 · 复盘尾 — 六问复盘 + 闭环回写（MEMORY.md / evolution_notes）
# ═══════════════════════════════════════════════════════════════════

_REVIEW_KEYS = [
    "intent_ok",
    "nine_tail_coverage",
    "emotion_ok",
    "plan_ok",
    "persona_ok",
    "satisfaction",
]


class ReviewTail:
    """复盘尾：回合级六问自评 → retrospects 落盘 → 改进项回写 MEMORY.md。"""

    name = "复盘尾"

    def __init__(self, root: Path | None = None, data_dir: Path | None = None):
        self._root = Path(root) if root is not None else _resolve_root()
        self._data_dir = Path(data_dir) if data_dir is not None else _kitsune_dir()
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.debug("[复盘尾] mkdir failed: %s", e)
        self._notes_file = self._data_dir / "evolution_notes.md"
        self._memory_md = self._root / "identity" / "MEMORY.md"

    # ── 六问自评 ──────────────────────────────────────────

    def self_review(
        self,
        *,
        message: str,
        reply: str = "",
        verdict: dict | None = None,
        session_id: str = "",
    ) -> dict:
        """确定性六问打分 + 改进项；真正调用 record_turn_review 落盘。"""
        verdict = verdict or {}
        risk_level = (verdict.get("risk") or {}).get("level", "low")
        emotion = (verdict.get("emotion") or {})
        mode = verdict.get("mode", "")
        tails = verdict.get("tails", {})

        intent_ok = 0.85 if risk_level in ("low", "medium") else 0.6
        nine_tail_coverage = round(sum(1 for v in tails.values() if v.get("ok")) / max(len(tails), 1), 3)
        emotion_ok = 0.9 if emotion.get("confidence", 0) > 0.3 else 0.7
        plan_ok = 0.85 if reply.strip() else 0.5
        persona_ok = 0.9  # 确定性：心判注入后模式一致
        satisfaction = 0.8 if reply.strip() else 0.4

        improvement_bits: list[str] = []
        guidance = (verdict.get("ethics") or {}).get("guidance", "")
        if guidance:
            improvement_bits.append(f"正向引导：{guidance}")
        if risk_level in ("high", "critical"):
            improvement_bits.append(f"风控拦截：{risk_level}级操作需确认后执行")
        if not (verdict.get("memory")):
            improvement_bits.append("记忆召回为空：可主动沉淀本轮事实")
        if verdict.get("creative"):
            improvement_bits.append("创意已收敛：保留 Top 创意供后续迭代")
        improvement = "；".join(improvement_bits) or "常规回合，无需专项改进"

        review = {
            "task_id": f"kitsune-{(session_id or 'anon')[:24]}-{int(datetime.now().timestamp() * 1000)}",
            "session_id": session_id,
            "description": (message or "")[:200],
            "six_questions": {k: locals().get(k, 0.0) for k in _REVIEW_KEYS},
            "improvement": improvement,
            "mode": mode,
            "timestamp": _iso_now(),
        }

        # 真正接线：六问写 retrospects（修复「record_turn_review 零调用」）
        try:
            from openkitsune.evolution.turn_review import record_turn_review

            record_turn_review(
                task_id=review["task_id"],
                session_id=session_id or None,
                description=review["description"],
                intent_ok=review["six_questions"]["intent_ok"],
                nine_tail_coverage=review["six_questions"]["nine_tail_coverage"],
                emotion_ok=review["six_questions"]["emotion_ok"],
                plan_ok=review["six_questions"]["plan_ok"],
                persona_ok=review["six_questions"]["persona_ok"],
                satisfaction=review["six_questions"]["satisfaction"],
                improvement=improvement,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("[复盘尾] record_turn_review failed: %s", e)
        return review

    # ── 闭环：改进项回写 ──────────────────────────────────

    def apply_review(self, review: dict) -> bool:
        if not review or not review.get("improvement"):
            return False
        ok_notes = self._append_notes(review)
        ok_memory = self._append_memory_md(review)
        return ok_notes or ok_memory

    def _append_notes(self, review: dict) -> bool:
        try:
            line = f"- [{review.get('timestamp', _iso_now())[:19]}] {review.get('improvement','')}"
            with _file_lock:
                lines: list[str] = []
                if self._notes_file.exists():
                    lines = self._notes_file.read_text(encoding="utf-8").splitlines()
                if line not in lines:
                    lines.append(line)
                lines[:] = lines[-200:]
                self._notes_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[复盘尾] notes append failed: %s", e)
            return False

    def _append_memory_md(self, review: dict) -> bool:
        """改进项合并进 identity/MEMORY.md（追加「## 进化复盘」区，幂等）。"""
        try:
            if not self._memory_md.exists():
                return False
            with _file_lock:
                text = self._memory_md.read_text(encoding="utf-8")
                line = f"- [{review.get('timestamp', _iso_now())[:10]}] {review.get('improvement','')}"
                if line in text:
                    return False
                header = "## 进化复盘"
                if header not in text:
                    if not text.endswith("\n"):
                        text += "\n"
                    text += f"\n{header}\n"
                # 在「## 进化复盘」区末尾追加，并限制该区最近 50 条
                idx = text.index(header)
                tail = text[idx:]
                head = text[:idx]
                if "\n## " in tail[3:]:
                    # 区后有其他区块：在下一区块前插入
                    rest_idx = tail.index("\n## ", 4)
                    section, rest = tail[:rest_idx], tail[rest_idx:]
                else:
                    section, rest = tail, ""
                bullets = [
                    l for l in section.splitlines() if l.startswith("- [")
                ]
                bullets.append(line)
                bullets = bullets[-50:]
                section = header + "\n" + "\n".join(bullets) + "\n"
                self._memory_md.write_text(head + section + rest, encoding="utf-8")
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[复盘尾] MEMORY.md append failed: %s", e)
            return False

    def adaptive_optimization(self, n: int = 10) -> list[dict]:
        """聚合最近 N 条改进项（进化建议）。"""
        try:
            if not self._notes_file.exists():
                return []
            lines = self._notes_file.read_text(encoding="utf-8").splitlines()
            out = []
            for l in lines[-n:]:
                if l.startswith("- [") and "：" in l:
                    out.append({"source": "evolution_notes", "text": l[2:]})
            return out
        except Exception as e:  # noqa: BLE001
            logger.debug("[复盘尾] adaptive_optimization failed: %s", e)
            return []


# ═══════════════════════════════════════════════════════════════════
# 中宫 · 狐心 — 并行推演 → 冲突裁决 → 九宫收敛
# ═══════════════════════════════════════════════════════════════════


class KitsuneHeart:
    """中宫狐心：九尾调度、整合、裁决（替代「按优先级排序」）。"""

    name = "狐心"

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else _resolve_root()
        self._data_dir = self.root / "data" / "kitsune"
        self.strategy_tail = StrategyTail(data_dir=self._data_dir)
        self.psychological_tail = PsychologicalTail()
        self.creative_tail = CreativeTail()
        self.risk_tail = RiskControlTail()
        self.execution_tail = ExecutionTail()
        self.ethical_tail = EthicalTail(data_dir=self._data_dir)
        self.memory_tail = MemoryTail(data_dir=self._data_dir)
        self.tool_tail = ToolTail(root=self.root)
        self.review_tail = ReviewTail(root=self.root, data_dir=self._data_dir)

    # ── 协调主入口 ────────────────────────────────────────

    def coordinate(self, message: str, *, context: dict | None = None) -> dict:
        """九尾并行推演 → 冲突裁决 → 收敛为 HeartVerdict。"""
        message = (message or "").strip()
        tails: dict[str, TailResult] = {}

        # 1. 记忆尾（先召回，供其他尾参考）
        tails["memory"] = self._run("memory", self.memory_tail.recall, message)
        # 2. 战略尾（长期目标召回）
        tails["strategy"] = self._run("strategy", self.strategy_tail.recall_relevant, message)
        # 3. 心理尾
        tails["psychology"] = self._run("psychology", self.psychological_tail.perceive, message)
        # 4. 风控尾
        tails["risk"] = self._run("risk", self.risk_tail.assess, message)
        # 5. 伦理尾
        tails["ethics"] = self._run("ethics", self.ethical_tail.check, message)
        # 6. 工具尾
        tails["tool"] = self._run("tool", self.tool_tail.suggest_tools, message)
        # 7. 执行尾
        tails["execution"] = self._run("execution", self.execution_tail.plan_steps, message)

        psych = tails["psychology"].data if tails["psychology"].ok else {}
        risk = tails["risk"].data if tails["risk"].ok else {}
        ethics = tails["ethics"].data if tails["ethics"].ok else {}
        mode = psych.get("mode", "兜底容错")

        # 8. 创意尾（仅创意/决策模式启用，且风控与伦理放行）
        creative: list[dict] = []
        if mode in ("创意发散", "决策推演") and not risk.get("blocked") and ethics.get("verdict") != "refuse":
            opts = self.creative_tail.diverge(message)
            creative = self.creative_tail.converge(opts, risk_level=risk.get("level", "low"))

        # 成长本能（伦理尾）
        if tails["ethics"].ok:
            try:
                self.ethical_tail.growth_hints(message)
            except Exception as e:  # noqa: BLE001
                logger.debug("[狐心] growth_hints failed: %s", e)

        # ── 冲突裁决 ──────────────────────────────────────
        action = "proceed"
        exec_plan = dict(tails["execution"].data) if tails["execution"].ok else {}
        if ethics.get("verdict") == "refuse":
            action = "refuse"
            creative = []
            exec_plan["apply"] = False
            mode = "兜底容错"
        elif risk.get("blocked"):
            action = "confirm"
            creative = []  # 风控一票否决：创意与自动执行让位于确认
            exec_plan["apply"] = False
        elif risk.get("level") in ("high", "critical"):
            action = "confirm"

        # 情绪调整：负面情绪强制温柔共情（除非已拒绝）
        emotion = psych.get("emotion", {})
        if action != "refuse" and emotion.get("negative") and mode not in ("温柔共情", "情绪疏导"):
            mode = "温柔共情"

        guidance = ""
        if tails["ethics"].ok and action != "refuse":
            try:
                guidance = self.ethical_tail.guidance(message)
            except Exception as e:  # noqa: BLE001
                logger.debug("[狐心] guidance failed: %s", e)

        _mem = _unwrap_items(tails["memory"])
        _goals = _unwrap_items(tails["strategy"])
        _tools = _unwrap_items(tails["tool"])

        # ── 九宫收敛 ──────────────────────────────────────
        return {
            "ts": _iso_now(),
            "message": message[:120],
            "mode": mode,
            "action": action,
            "emotion": emotion,
            "subtext": psych.get("subtext", []),
            "needs": psych.get("needs", []),
            "risk": risk,
            "ethics": {
                "verdict": ethics.get("verdict", "ok"),
                "reasons": ethics.get("reasons", []),
                "guidance": guidance,
            },
            "memory": _mem,
            "memory_hit": bool(_mem),
            "goals": _goals,
            "tools": _tools,
            "creative": creative,
            "execution": exec_plan,
            "tails": {k: v.to_dict() for k, v in tails.items()},
        }

    def _run(self, name: str, fn: Callable, message: str) -> TailResult:
        try:
            data = fn(message)
            return TailResult(tail=name, ok=True, data=data if isinstance(data, dict) else {"items": data})
        except Exception as e:  # noqa: BLE001
            logger.debug("[狐心] tail %s failed: %s", name, e)
            return TailResult(tail=name, ok=False, error=str(e)[:200])


def _unwrap_items(r: TailResult) -> Any:
    """还原 _run 对列表尾的 {"items": [...]} 包装；dict 尾原样返回。"""
    if not r.ok:
        return []
    d = r.data
    if isinstance(d, dict) and set(d.keys()) == {"items"}:
        return d.get("items", [])
    return d


# ═══════════════════════════════════════════════════════════════════
# 桥接器 — 挂到 Agent 运行时（仿 LingxiBridge，最小侵入）
# ═══════════════════════════════════════════════════════════════════


class KitsuneHeartBridge:
    """九尾内核桥接器：对话前注入心判 + 对话后复盘闭环。"""

    def __init__(self, agent: Any):
        self._agent = agent
        self._heart = KitsuneHeart()
        self._last_verdict: dict | None = None
        self._last_message_hash: int = 0

        # 记忆尾接线：用 agent.memory_manager.recall_facts（惰性、尽力而为）
        def _retriever(msg: str) -> list[str]:
            mgr = getattr(agent, "memory_manager", None)
            if mgr is None or not hasattr(mgr, "recall_facts"):
                return []
            try:
                payload = mgr.recall_facts(msg, budget_tokens=400)
                facts = payload.get("facts", []) if isinstance(payload, dict) else []
                out: list[str] = []
                for f in facts:
                    if isinstance(f, dict):
                        t = f.get("text") or f.get("content") or ""
                    else:
                        t = str(f)
                    t = (t or "").strip()
                    if t and t not in out:
                        out.append(t[:200])
                return out[:3]
            except Exception as e:  # noqa: BLE001
                logger.debug("[狐心桥] memory recall failed: %s", e)
                return []

        self._heart.memory_tail.set_retriever(_retriever)

    @property
    def heart(self) -> KitsuneHeart:
        return self._heart

    # ── 对话前注入 ────────────────────────────────────────

    def get_session_context(self, message: str = "") -> dict:
        """返回狐心心判（供 prompt 组装）。空消息返回空 dict，不注入。"""
        message = (message or "").strip()
        if not message:
            return {}
        h = hash(message)
        if h == self._last_message_hash and self._last_verdict is not None:
            verdict = self._last_verdict
        else:
            verdict = self._heart.coordinate(message)
            self._last_verdict = verdict
            self._last_message_hash = h
        return {
            "verdict": verdict,
            "mode": verdict.get("mode"),
            "action": verdict.get("action"),
        }

    # ── 对话后复盘闭环 ────────────────────────────────────

    def after_turn(self, message: str = "", reply: str = "", session_id: str = "") -> dict:
        """复盘六问落盘 + 改进项回写 MEMORY.md（闭环）。"""
        message = (message or "").strip()
        if not message:
            return {}
        review = self._heart.review_tail.self_review(
            message=message,
            reply=reply or "",
            verdict=self._last_verdict,
            session_id=session_id or "",
        )
        self._heart.review_tail.apply_review(review)
        # 清缓存，避免下一轮复用旧心判
        self._last_verdict = None
        self._last_message_hash = 0
        return review
