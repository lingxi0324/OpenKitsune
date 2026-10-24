"""
九尾议会 · 自主调度内核 (KitsuneCouncil)
========================================

让 AI 根据用户需求**自主决策**：分析任务画像 → 自主选择启用哪些「尾」（九维）
参与本轮推理 → 中宫收敛裁决（覆盖校验）→ 复盘写入记忆；同时接受用户命令
（/council ... /尾 ...）按需覆盖，尊重用户自主选择。

对齐：
- identity/KITSUNE_SOUL.md 九尾九维架构（战略/心理/创意/风控/执行/伦理/记忆/工具/复盘 + 中宫狐心）
- 《流程规则整改-v2》§4 多 Agent 冲突裁决（证据 > 目标一致性 > 置信度）
- mode_mapping.md「九尾议会 ≈ 思考过程（认知层），交互模式 ≈ 表达姿态，两者正交」

设计约束（与 lingxi_bridge 同风格）：
- 零侵入：任何异常只降级不阻断主流程（调用方 try/except 兜底 + 本模块内部 also 兜底）
- 规则启发式为主（确定性、可测试、零模型成本），LLM 增强可选（council_llm_review）
- OFF / MINIMAL / AUTO / FULL 四级模式，用户命令优先于自动判定
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── 九尾九维目录（与 KITSUNE_SOUL 四·九尾九维 一一对应） ──────────────
# keywords 用于：任务画像分类（触发词）与九维覆盖校验（呈现痕迹词）。
# 触发词与呈现词刻意分开，避免"用户说风险 → 覆盖校验误以为回应了风险"。
TAIL_CATALOG: dict[str, dict[str, Any]] = {
    "strategy": {
        "name": "战略尾",
        "aliases": ("战略", "strategic", "规划", "布局"),
        "desc": "长期布局、目标拆解、多路径决策",
        "trigger": ("选择", "纠结", "要不要", "该不该", "利弊", "优缺点", "推荐", "哪个", "方案",
                    "规划", "长期", "目标", "职业", "人生", "决策", "权衡", "取舍"),
        "coverage": ("目标", "方案", "路径", "步骤", "规划", "长期", "利弊", "取舍", "优先级",
                     "拆解", "roadmap", "计划"),
    },
    "psychic": {
        "name": "心理尾",
        "aliases": ("心理", "psychic", "通灵", "识心"),
        "desc": "情绪识别、潜台词洞察、真实痛点",
        "trigger": ("难过", "伤心", "焦虑", "压力", "累", "烦", "委屈", "害怕", "担心", "不开心",
                    "低落", "倾诉", "心情", "内耗", "emo", "情绪"),
        "coverage": ("感受", "情绪", "担心", "期待", "在意", "心疼", "理解", "别怕", "我在", "放心",
                     "情绪", "心态", "潜台词", "痛点"),
    },
    "creative": {
        "name": "创意尾",
        "aliases": ("创意", "creative", "发散", "灵感"),
        "desc": "发散、优化、新解、多方案",
        "trigger": ("创意", "点子", "灵感", "头脑风暴", "新奇", "文案", "脑洞", "发散",
                    "新思路", "不一样的想法"),
        "coverage": ("想法", "创意", "方案", "角度", "可能", "可选", "变体", "灵感", "尝试",
                     "组合", "版本"),
    },
    "risk": {
        "name": "风控尾",
        "aliases": ("风控", "risk", "风险", "边界"),
        "desc": "风险预判、边界识别、代价提示",
        "trigger": ("风险", "危险", "不可逆", "删除", "覆盖", "发布", "转账", "支付", "签约",
                    "合同", "授权", "密码", "账号", "谨慎", "安全", "后果", "代价"),
        "coverage": ("风险", "注意", "边界", "代价", "隐患", "谨慎", "备份", "回滚", "后果",
                     "建议先", "确认", "兜底", "防"),
    },
    "execution": {
        "name": "执行尾",
        "aliases": ("执行", "execution", "落地"),
        "desc": "落地步骤、工具编排、验证闭环",
        "trigger": ("帮我", "请", "做", "写", "改", "修", "建", "部署", "启动", "安装", "执行",
                    "运行", "生成", "处理", "实现", "开发", "排查", "修复"),
        "coverage": ("已", "完成", "结果", "执行", "验证", "输出", "文件", "步骤", "下一步",
                     "检查", "通过", "失败", "done", "finish"),
    },
    "ethics": {
        "name": "伦理尾",
        "aliases": ("伦理", "ethics", "底线", "正向"),
        "desc": "底线守护、正向引导、温和纠正",
        "trigger": ("道德", "伦理", "违规", "违法", "伤害", "欺骗", "底线", "正向", "克制",
                    "拒绝", "不合适"),
        "coverage": ("底线", "合规", "安全", "尊重", "建议", "温柔", "正向", "不越界", "原则",
                     "拒绝", "合法"),
    },
    "memory": {
        "name": "记忆尾",
        "aliases": ("记忆", "memory", "忆念"),
        "desc": "长期记忆、唤醒关联、往事回溯",
        "trigger": ("之前", "上次", "以前", "还记得", "我说过", "做过", "老", "过去", "回忆",
                    "想起"),
        "coverage": ("记得", "之前", "上次", "以前", "上次聊", "根据记忆", "回顾", "当时"),
    },
    "tools": {
        "name": "工具尾",
        "aliases": ("工具", "tools", "技能", "神通"),
        "desc": "技能/工具调度、按需选择",
        "trigger": ("文件", "代码", "目录", "脚本", "搜索", "下载", "工具", "技能", "接口",
                    "命令", "数据库", "表格", "文档", "图片", "视频", "音频"),
        "coverage": ("工具", "技能", "命令", "脚本", "文件", "接口", "调用", "已查", "已读",
                     "搜索", "运行", "验证"),
    },
    "review": {
        "name": "复盘尾",
        "aliases": ("复盘", "review", "总结", "改进"),
        "desc": "事后复盘、自我进化、六问修行",
        "trigger": ("复盘", "总结", "改进", "回顾", "反思", "教训", "复盘一下", "做得怎么样",
                    "哪里不好"),
        "coverage": ("复盘", "总结", "改进", "教训", "收获", "反思", "经验", "下次"),
    },
}

# 中宫（狐心）：调度、整合、裁决——不是第十条尾，是收敛器
CENTER = {
    "name": "中宫狐心",
    "desc": "调度、整合、裁决（九尾议会收敛）",
}

# 常驻尾：通灵善察（心理）与千年忆念（记忆）作为九尾狐底色，默认参与
_DEFAULT_TAILS: set[str] = {"psychic", "memory"}


class CouncilMode(Enum):
    """议会模式：四级自主调度"""

    AUTO = "auto"        # 默认：按任务画像自主启用尾集
    MINIMAL = "minimal"  # 轻量：简单问答只启常驻尾
    FULL = "full"        # 全量：复杂/决策/跨域，九尾并行推演 + 中宫收敛
    OFF = "off"          # 关闭：用户显式关闭议会

    @classmethod
    def parse(cls, value: str) -> CouncilMode | None:
        v = (value or "").strip().lower()
        table = {
            "auto": cls.AUTO, "自动": cls.AUTO, "自主": cls.AUTO,
            "minimal": cls.MINIMAL, "轻量": cls.MINIMAL, "简单": cls.MINIMAL,
            "full": cls.FULL, "全量": cls.FULL, "全面": cls.FULL, "全尾": cls.FULL,
            "off": cls.OFF, "关闭": cls.OFF, "关": cls.OFF, "停": cls.OFF,
        }
        return table.get(v)


@dataclass
class TaskProfile:
    """任务画像——议会自主决策的依据"""

    text: str = ""
    domain: str = "general"           # general / tech / medical / metaphysics / finance / emotional / decision / cross_domain
    complexity: float = 0.0           # 0-1
    risk_level: float = 0.0           # 0-1
    emotional: bool = False
    evidence_needed: bool = False
    multi_step: bool = False
    cross_domain: bool = False
    tail_slate: set[str] = field(default_factory=lambda: set(_DEFAULT_TAILS))
    mode: CouncilMode = CouncilMode.AUTO
    directive: dict[str, Any] | None = None   # 用户命令（若命中）
    reason: str = ""                  # 自主决策说明（供注入/日志）

    def enabled_tail_names(self) -> list[str]:
        return [TAIL_CATALOG[t]["name"] for t in self.sorted_tails()]

    def sorted_tails(self) -> list[str]:
        order = ["strategy", "psychic", "creative", "risk", "execution",
                 "ethics", "memory", "tools", "review"]
        return [t for t in order if t in self.tail_slate]


@dataclass
class CoverageVerdict:
    """九维覆盖校验结果（中宫收敛检查）"""

    profile: TaskProfile | None = None
    checked: bool = False
    coverage: float = 0.0              # 启用尾中呈现比例 0-1
    missing_tails: list[str] = field(default_factory=list)
    insufficient: bool = False
    note: str = ""

    def to_prompt_block(self) -> str:
        """生成收敛提示（注入下一次推理或日志，不阻断）"""
        if not self.checked or not self.insufficient:
            return ""
        lines = [f"🦊 中宫收敛·覆盖提醒：九维覆盖 {self.coverage:.0%}"]
        if self.missing_tails:
            names = "、".join(TAIL_CATALOG[t]["name"] for t in self.missing_tails)
            lines.append(f"  缺失维度：{names} —— 若相关请补充，避免结论悬空。")
        if self.note:
            lines.append(f"  {self.note}")
        return "\n".join(lines)


# ── 领域判定 ──────────────────────────────────────────────────────────
_DOMAIN_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("tech", ("代码", "接口", "架构", "报错", "编译", "测试", "git", "docker", "llm", "模型",
              "脚本", "命令", "python", "typescript", "rust", "go ", "前端", "后端", "数据库",
              "部署", "配置", "日志", "bug", "debug", "函数", "类", "api", "sdk", "工具链")),
    ("medical", ("中医", "药", "方剂", "经络", "穴位", "养生", "症状", "脉象", "辨证", "症候",
                 "汤", "针灸", "拔罐", "食疗", "气血", "阴阳", "五脏", "六腑", "舌苔")),
    ("metaphysics", ("八字", "紫微", "奇门", "六爻", "风水", "命理", "五行", "河图", "洛书",
                     "大运", "流年", "四柱", "排盘", "纳音", "神煞", "太岁", "丹道", "玄学")),
    ("finance", ("投资", "股票", "基金", "理财", "行情", "估值", "市盈率", "财报", "价格",
                 "汇率", "期货", "黄金", "债券", "资产", "仓位")),
]

_DECISION_TRIGGERS = ("选择", "纠结", "要不要", "该不该", "哪个", "利弊", "优缺点", "推荐",
                      "重大", "人生", "职业", "买房", "买车", "离职", "跳槽", "结婚", "决策",
                      "权衡", "取舍", "签约", "投资")
_CROSS_DOMAIN_TRIGGERS = ("融合", "结合", "跨域", "同时考虑", "一体", "翻译层", "打通",
                          "中医.*科学", "科学.*中医", "玄学.*技术", "技术.*玄学")
_RISK_TRIGGERS = ("删除", "覆盖", "发布", "转账", "支付", "签约", "合同", "授权", "密码",
                  "账号", "不可逆", "重要文件", "正式发送", "对外", "公开")
_EMOTION_TRIGGERS = ("难过", "伤心", "焦虑", "压力", "累", "烦", "委屈", "害怕", "担心",
                     "不开心", "低落", "倾诉", "心情", "内耗", "emo", "情绪", "哭", "疲惫",
                     "崩溃", "迷茫", "孤独", "生气", "愤怒")
_MULTI_STEP_TRIGGERS = ("先", "再", "然后", "步骤", "流程", "分几步", "阶段", "依次",
                        "第一步", "第二步", "接着")
_TASK_VERBS = ("帮我", "请", "做", "写", "改", "修", "建", "部署", "启动", "安装", "执行",
               "运行", "生成", "处理", "实现", "开发", "排查", "修复", "分析", "调查", "设计",
               "整理", "转换", "优化")
_EVIDENCE_TRIGGERS = ("最新", "实时", "现在", "今天", "查一下", "搜索", "官网", "新闻",
                      "报价", "价格", "政策", "行情", "数据", "来源", "出处", "依据")

# 用户命令解析（自主选择入口）
# 注意：不能用 `$` 锚点——`$` 只匹配字符串末尾（或末尾换行前），命令后跟正文
# （换行或同一行继续输入）会导致整条匹配失败。只锚定开头，让 `(.*)` 匹配到
# 行内命令参数为止（`.` 不匹配换行），正文自然留在消息中由主意图管线处理。
_DIRECTIVE_PATTERNS = [
    re.compile(r"^\s*/council\s*(.*)", re.I),
    re.compile(r"^\s*/议会\s*(.*)"),
    re.compile(r"^\s*/尾\s*(.*)"),
    re.compile(r"^\s*九尾(议会)?[：:]\s*(.*)"),
]
_TAIL_ALIAS_TO_KEY = {alias: key for key, meta in TAIL_CATALOG.items() for alias in meta["aliases"]}
_TAIL_ALIAS_TO_KEY.update({meta["name"]: key for key, meta in TAIL_CATALOG.items()})
_TAIL_ALIAS_TO_KEY.update({"全部": None, "全尾": None, "all": None, "全部尾": None})


def parse_directive(text: str) -> dict[str, Any] | None:
    """解析用户议会命令：/council off|on|auto|full|minimal|状态|尾 xxx

    命中返回 directive dict；未命中返回 None。命令解析不影响主流程——命令文本
    仍保留在用户消息中（现有意图管线自行处理），议会只在自身层面对其生效。
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    args: str | None = None
    for pat in _DIRECTIVE_PATTERNS:
        m = pat.match(raw)
        if m:
            args = "".join(g or "" for g in m.groups()).strip() or "状态"
            break
    if args is None:
        return None

    directive: dict[str, Any] = {"raw": raw, "mode": None, "tails": None, "action": "set"}

    # 模式子命令：优先取首个词（如 "off x" → off），再试整句
    first_word = args.split()[0] if args else ""
    mode = CouncilMode.parse(first_word)
    if mode is None:
        mode = CouncilMode.parse(args)
    if mode is not None:
        directive["mode"] = mode
        return directive
    if args in ("状态", "status", "看看", "?"):
        directive["action"] = "status"
        return directive

    # 尾覆盖子命令：/尾 战略+风控+伦理 或 /council 尾 战略,风控
    m = re.match(r"^(?:尾|tails?)[\s:：]*(.*)$", args, re.I)
    if m:
        tails_spec = m.group(1).strip()
        directive["tails"] = _parse_tails_spec(tails_spec)
        if directive["tails"]:
            return directive
        return None  # 尾规格解析不出有效尾 → 视为普通消息

    # 兜底：直接视作尾列表（如 "/council 战略,风控"）
    tails = _parse_tails_spec(args)
    if not tails:
        return None  # 什么都解析不出 → 非议会指令，避免误伤正常消息
    directive["tails"] = tails
    return directive


def _parse_tails_spec(spec: str) -> set[str] | None:
    if not spec:
        return None
    if spec in ("全部", "全尾", "all", "ALL"):
        return set(TAIL_CATALOG.keys())
    parts = re.split(r"[,，、+＋/| ]+", spec)
    tails: set[str] = set()
    for p in parts:
        key = _TAIL_ALIAS_TO_KEY.get(p.strip())
        if key is None and p.strip():
            continue  # 未知别名忽略（不误伤）
        if key:
            tails.add(key)
    return tails or None


# ── 规则分类（确定性、可测试） ────────────────────────────────────────
def _contains(text: str, triggers: tuple[str, ...]) -> bool:
    t = text.lower()
    return any(tg.lower() in t for tg in triggers)


def _domain_of(text: str) -> str:
    hits: list[str] = []
    for dom, pats in _DOMAIN_PATTERNS:
        if _contains(text, pats):
            hits.append(dom)
    return hits[0] if len(hits) == 1 else ("cross_domain" if len(hits) >= 2 else "general")


def classify_request(
    text: str,
    recent_messages: list[dict] | None = None,
    session_meta: dict[str, Any] | None = None,
) -> TaskProfile:
    """自主决策核心：任务画像 → 九尾启用集 → 议会模式。纯规则，无模型成本。"""
    text = (text or "").strip()
    recent_text = " ".join(
        (m.get("content") or "") for m in (recent_messages or [])[-3:] if isinstance(m, dict)
    )
    combined = f"{recent_text} {text}".strip()

    directive = parse_directive(text)

    # ── 领域 / 情绪 / 风险 / 复杂度 ──
    domain = _domain_of(combined)
    emotional = _contains(combined, _EMOTION_TRIGGERS)
    risk_level = 0.0
    if _contains(combined, _RISK_TRIGGERS):
        risk_level = 0.6
        if _contains(combined, ("不可逆", "重要文件", "正式发送", "对外", "发布")):
            risk_level = 0.85
    decision = _contains(combined, _DECISION_TRIGGERS)
    cross_domain = _contains(combined, _CROSS_DOMAIN_TRIGGERS) or domain == "cross_domain"
    if decision and domain == "general":
        domain = "decision"  # 决策是独立领域，供中宫多路径/分派判断
    evidence_needed = _contains(combined, _EVIDENCE_TRIGGERS)
    multi_step = _contains(combined, _MULTI_STEP_TRIGGERS)

    complexity = 0.0
    complexity += min(0.25, len(text) / 500.0)
    verb_hits = sum(1 for v in _TASK_VERBS if v in text)
    complexity += min(0.3, verb_hits * 0.08)
    if multi_step:
        complexity += 0.2
    if decision or cross_domain:
        complexity += 0.3
    if evidence_needed:
        complexity += 0.1
    complexity = round(min(1.0, complexity), 2)

    # ── 模式判定（用户命令 > 自动） ──
    mode = CouncilMode.AUTO
    if directive and directive.get("mode") is not None:
        mode = directive["mode"]
    elif complexity >= 0.7 or decision or cross_domain or risk_level >= 0.6:
        mode = CouncilMode.FULL
    elif complexity < 0.3 and not emotional:
        mode = CouncilMode.MINIMAL

    # ── 尾集选择 ──
    if mode == CouncilMode.OFF:
        slate: set[str] = set()
    elif mode == CouncilMode.MINIMAL:
        slate = set(_DEFAULT_TAILS)
        if domain == "tech" or _contains(text, _TASK_VERBS):
            slate.add("tools")
    else:
        slate = set(_DEFAULT_TAILS)
        if domain == "tech" or _contains(text, _TASK_VERBS):
            slate |= {"execution", "tools"}
        if domain == "medical":
            slate |= {"memory", "strategy"}
        if domain == "metaphysics":
            slate |= {"memory", "strategy", "creative"}
        if domain == "finance":
            slate |= {"strategy", "risk", "memory"}
        if decision:
            slate |= {"strategy", "risk", "ethics", "creative"}
        if emotional:
            slate |= {"psychic", "ethics"}
        if cross_domain:
            slate |= {"creative", "strategy", "memory"}
        if evidence_needed:
            slate |= {"tools", "strategy"}
        if risk_level >= 0.6:
            slate |= {"risk", "ethics"}
        if multi_step or complexity >= 0.6:
            slate |= {"execution", "strategy", "review"}
        if mode == CouncilMode.FULL:
            slate = set(TAIL_CATALOG.keys())
    # 用户显式指定尾集 → 统一覆盖（即使 MINIMAL/OFF 分支也尊重，用户需求优先）
    if directive and directive.get("tails"):
        slate = set(directive["tails"])

    # ── 决策说明（供注入与日志，可复核） ──
    reason_parts = [
        f"领域={domain}",
        f"复杂度={complexity:.2f}",
        f"风险={risk_level:.1f}",
        f"情绪={emotional}",
        f"决策={decision}",
        f"跨域={cross_domain}",
    ]
    if directive:
        reason_parts.append(f"指令={directive.get('raw')!r}")
    reason = "｜".join(reason_parts)

    profile = TaskProfile(
        text=text[:800],
        domain=domain,
        complexity=complexity,
        risk_level=risk_level,
        emotional=emotional,
        evidence_needed=evidence_needed,
        multi_step=multi_step,
        cross_domain=cross_domain,
        tail_slate=slate,
        mode=mode,
        directive=directive,
        reason=reason,
    )
    logger.debug("[KitsuneCouncil] 自主决策: %s → 尾=[%s] 模式=%s",
                 reason, ",".join(profile.sorted_tails()), mode.value)
    return profile


# ── 议会指令注入（prompt 层） ─────────────────────────────────────────
def build_council_section(profile: TaskProfile | None) -> str:
    """生成议会指令段（注入 system prompt）。

    - OFF：不注入
    - MINIMAL：一行轻量说明
    - AUTO：列出启用尾 + 中宫收敛要求
    - FULL：九尾并行推演 + 中宫收敛 + 多路径/风险要求
    返回空字符串 = 零影响。
    """
    if profile is None or profile.mode == CouncilMode.OFF:
        return ""
    tails = profile.sorted_tails()
    names = "、".join(TAIL_CATALOG[t]["name"] for t in tails)

    lines: list[str] = []
    if profile.mode == CouncilMode.MINIMAL:
        lines.append(f"🦊 议会·轻量：本轮以 {names} 参与，直接作答即可。")
        return "\n".join(lines)

    lines.append(f"🦊 九尾议会·{profile.mode.value.upper()}：本轮启用 {names}，由中宫狐心收敛裁决。")
    if profile.mode == CouncilMode.FULL:
        lines.append("   数理自洽：结论须落回九宫之一——不悬空、不重复、不遗漏；推导可复核。")
        if profile.domain in ("decision", "cross_domain") or (
            "strategy" in profile.tail_slate and "risk" in profile.tail_slate
        ):
            lines.append("   多路径推演：先列候选路径 × 利弊 × 风险，再给推荐与兜底，不直接单方案。")
        if profile.risk_level >= 0.6:
            lines.append("   风控优先：先评估可逆性与边界（备份/确认/回滚），再执行，不硬闯。")
        if profile.cross_domain:
            lines.append("   一体宇宙观：跨域议题先建翻译层（象与节律/机制与证据/趋势与时机），再给结论。")
        if profile.emotional:
            lines.append("   情智平衡：先接情绪再给理性，温和纠正，不评判。")
    if profile.directive:
        lines.append(f"   （按郎君议会指令：{profile.directive.get('raw', '')}）")
    return "\n".join(lines)


# ── 九维覆盖校验（中宫收敛检查，轻量、不阻断） ──────────────────────
def verify_coverage(
    profile: TaskProfile | None,
    response_text: str,
    tool_results: list[dict] | None = None,
) -> CoverageVerdict:
    """检查响应是否呈现了启用尾的职能痕迹；FULL/AUTO 模式执行，MINIMAL/OFF 跳过。"""
    if profile is None or profile.mode in (CouncilMode.OFF, CouncilMode.MINIMAL):
        return CoverageVerdict(checked=False)
    response_text = (response_text or "").strip()
    if not response_text:
        return CoverageVerdict(
            profile=profile, checked=True, coverage=0.0,
            missing_tails=list(profile.tail_slate), insufficient=True,
            note="本轮无文本响应，跳过深度校验。",
        )

    missing: list[str] = []
    for tail in profile.sorted_tails():
        meta = TAIL_CATALOG.get(tail)
        if not meta:
            continue
        # 心理尾在情绪任务中只要响应承接情绪即算覆盖（宽容判定）
        cov_words = meta["coverage"]
        if not _contains(response_text, cov_words):
            missing.append(tail)

    covered = len(profile.tail_slate) - len(missing)
    coverage = round(covered / max(1, len(profile.tail_slate)), 2)

    threshold = 0.55 if profile.mode == CouncilMode.FULL else 0.45
    insufficient = coverage < threshold

    note = ""
    if insufficient:
        miss_names = "、".join(TAIL_CATALOG[t]["name"] for t in missing)
        note = f"建议补足 {miss_names} 的视角后再收敛结论。"

    # 执行类任务：需要工具证据而未调用工具 → 提示（不阻断）
    if (
        "execution" in profile.tail_slate
        and profile.mode == CouncilMode.FULL
        and not (tool_results or [])
        and _contains(profile.text, _TASK_VERBS)
    ):
        note = (note + " " if note else "") + "本轮涉及执行类需求但未见工具调用，建议先查证/执行再给结论。"

    verdict = CoverageVerdict(
        profile=profile,
        checked=True,
        coverage=coverage,
        missing_tails=missing,
        insufficient=insufficient,
        note=note.strip(),
    )
    logger.debug("[KitsuneCouncil] 覆盖校验: %.0f%% missing=%s insufficient=%s",
                 coverage * 100, missing, insufficient)
    return verdict


# ── 复盘六问（接线 turn_review，规则评分 + 可选 LLM 自评） ───────────
def _score_review(
    profile: TaskProfile,
    response_text: str,
    tool_results: list[dict] | None,
    verdict: CoverageVerdict | None,
) -> dict[str, float]:
    """规则版六问评分（确定性；LLM 自评增强可选，见 review_turn）"""
    r = (response_text or "")
    ok_tools = sum(1 for x in (tool_results or []) if isinstance(x, dict) and not x.get("is_error"))

    intent_ok = 0.9 if profile.domain != "general" or _contains(r, TAIL_CATALOG["execution"]["coverage"]) else 0.75
    nine_tail_coverage = verdict.coverage if verdict and verdict.checked else 0.5
    emotion_ok = 0.8 if profile.emotional and _contains(r, TAIL_CATALOG["psychic"]["coverage"]) else (0.6 if profile.emotional else 0.8)
    plan_ok = 0.85 if ("execution" in profile.tail_slate and (ok_tools or _contains(r, ("已", "完成", "结果", "下一步")))) else 0.6
    persona_ok = 0.85 if _contains(r, ("温柔", "九尾", "灵性", "修行", "理解", "放心")) else 0.75
    satisfaction = 0.75 if not verdict or not verdict.insufficient else 0.6
    return {
        "intent_ok": round(intent_ok, 2),
        "nine_tail_coverage": round(nine_tail_coverage, 2),
        "emotion_ok": round(emotion_ok, 2),
        "plan_ok": round(plan_ok, 2),
        "persona_ok": round(persona_ok, 2),
        "satisfaction": round(satisfaction, 2),
    }


def review_turn(
    profile: TaskProfile | None,
    task_id: str,
    session_id: str | None = None,
    response_text: str = "",
    tool_results: list[dict] | None = None,
    *,
    llm_review: bool = False,
) -> bool:
    """每轮六问复盘 → 写入 retrospects（复盘尾接线点）。

    - OFF / MINIMAL 模式跳过（轻量）
    - 规则评分默认；llm_review=True 且有 brain 时尝试 LLM 自评，失败降级规则
    - 任何异常不影响主流程
    """
    if profile is None or profile.mode in (CouncilMode.OFF, CouncilMode.MINIMAL):
        return False
    try:
        verdict = verify_coverage(profile, response_text, tool_results)
        scores = _score_review(profile, response_text, tool_results, verdict)

        improvement = ""
        if verdict and verdict.missing_tails:
            miss_names = "、".join(TAIL_CATALOG[t]["name"] for t in verdict.missing_tails[:4])
            improvement = f"九维覆盖不足（{verdict.coverage:.0%}），缺失：{miss_names}"
        elif verdict and verdict.note:
            improvement = verdict.note[:120]
        else:
            improvement = "本轮收敛良好"

        from openkitsune.evolution.turn_review import record_turn_review

        return record_turn_review(
            task_id=task_id[:120],
            session_id=session_id,
            description=(profile.text or "")[:200],
            intent_ok=scores["intent_ok"],
            nine_tail_coverage=scores["nine_tail_coverage"],
            emotion_ok=scores["emotion_ok"],
            plan_ok=scores["plan_ok"],
            persona_ok=scores["persona_ok"],
            satisfaction=scores["satisfaction"],
            improvement=improvement[:300],
        )
    except Exception as e:  # noqa: BLE001 — 复盘失败不影响主流程
        logger.debug("[KitsuneCouncil] review_turn skipped: %s", e)
        return False


# ── 分派建议（九尾分身协同） ─────────────────────────────────────────
def should_dispatch(profile: TaskProfile | None) -> bool:
    """是否建议分派子代理/九尾分身（复杂 + 决策/跨域/多步）。最终由 AI 自主决定。"""
    if profile is None or profile.mode != CouncilMode.FULL:
        return False
    return (
        profile.complexity >= 0.6
        and (profile.domain in ("decision", "cross_domain") or profile.multi_step)
    )


# ── 便捷入口（供运行时单点调用） ─────────────────────────────────────
class KitsuneCouncil:
    """议会实例：供 _agent_runtime 挂载，聚合分类/注入/校验/复盘/分派建议。"""

    def __init__(self, agent: Any | None = None) -> None:
        self._agent = agent
        self._last_profile: TaskProfile | None = None
        self._last_verdict: CoverageVerdict | None = None

    # 对话前：画像 + 指令（供 session_context 注入 prompt）
    def prepare_turn(self, message: str, session_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            profile = classify_request(message or "", session_meta=session_meta)
            self._last_profile = profile
            section = build_council_section(profile)
            ctx: dict[str, Any] = {
                "profile": profile,
                "mode": profile.mode.value,
                "tails": profile.sorted_tails(),
                "tail_names": profile.enabled_tail_names(),
                "reason": profile.reason,
            }
            if section:
                ctx["section"] = section
            if should_dispatch(profile):
                ctx["dispatch_hint"] = (
                    "🦊 中宫建议：本任务适合分派九尾分身（子代理）并行推演后收敛，"
                    "请按需使用 create_agent，若单线程足够则不必分派。"
                )
            return ctx
        except Exception as e:  # noqa: BLE001
            logger.debug("[KitsuneCouncil] prepare_turn failed: %s", e)
            return {}

    # 对话中：覆盖校验（供 verify/finalize 前调用，轻量）
    def check_coverage(
        self,
        response_text: str,
        tool_results: list[dict] | None = None,
    ) -> CoverageVerdict:
        verdict = verify_coverage(self._last_profile, response_text, tool_results)
        self._last_verdict = verdict
        return verdict

    # 对话后：复盘接线
    def after_turn(
        self,
        message: str,
        reply: str = "",
        session_id: str = "",
        task_id: str | None = None,
    ) -> bool:
        try:
            profile = self._last_profile or classify_request(message or "")
            tid = task_id or f"{session_id or 'session'}:{int(time.time())}"
            return review_turn(
                profile,
                task_id=tid,
                session_id=session_id or None,
                response_text=reply or "",
                tool_results=None,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("[KitsuneCouncil] after_turn failed: %s", e)
            return False

    def reset(self) -> None:
        self._last_profile = None
        self._last_verdict = None
