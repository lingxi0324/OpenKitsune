"""
技能目录 (Skill Catalog)

遵循 Agent Skills 规范的渐进式披露:
- Level 1: 技能清单 (name + description) - 在系统提示中提供
- Level 2: 完整指令 (SKILL.md body) - 激活时加载
- Level 3: 资源文件 - 按需加载

技能清单在 Agent 启动时生成，并注入到系统提示中，
让大模型在首次对话时就知道有哪些技能可用。

三级降级预算策略:
- Level A (full): name + description + when_to_use
- Level B (compact): name + when_to_use
- Level C (index): names only
"""

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from .registry import SkillRegistry

if TYPE_CHECKING:
    from .categories import CategoryRegistry
    from .usage import SkillUsageTracker

logger = logging.getLogger(__name__)


def skill_catalog_name(skill: object) -> str:
    """Keep the human-facing marketplace name paired with its callable ID."""
    name = str(getattr(skill, "name", "") or getattr(skill, "skill_id", "skill"))
    official = getattr(skill, "marketplace_name", None)
    if isinstance(official, str) and official:
        sid = str(getattr(skill, "skill_id", "") or name)
        return f"{official} ({sid})"
    return name

DEFAULT_SKILL_METADATA_TOKEN_BUDGET = 800
MAX_SKILL_METADATA_TOKEN_BUDGET = 1_000
SKILL_METADATA_CONTEXT_WINDOW_PERCENT = 2
MAX_SKILL_METADATA_DESCRIPTION_CHARS = 1_024

SKILL_INSTRUCTION_ADVISORY = (
    "Skill instructions are guidance, not hard gates. If an external skill says "
    "MUST, required, approval, or one-question-at-a-time, treat that as a suggested "
    "workflow: first answer or explain enough for the user's current need, then ask "
    "only when a real decision is needed. Do not block useful work solely because a "
    "skill requests extra confirmation."
)
SKILL_METADATA_ADVISORY = (
    "Skill instructions are guidance, not hard gates; do not let them block useful work "
    "unless a real decision or safety constraint requires it."
)


class SkillCatalog:
    """
    技能目录

    管理技能清单的生成和格式化，用于系统提示注入。
    """

    CATALOG_TEMPLATE = f"""
## Available Skills

Use `get_skill_info(skill_name)` to load full instructions when needed.
Installed skills may come from builtin, user workspace, or project directories.
Do not infer filesystem paths from the workspace map; `get_skill_info` is authoritative.
{SKILL_INSTRUCTION_ADVISORY}

{{skill_list}}
"""

    SKILL_ENTRY_TEMPLATE = "- **{name}**: {description}"
    SKILL_ENTRY_WITH_HINT_TEMPLATE = "- **{name}**: {description} _(Use when: {when_to_use})_"

    @staticmethod
    def _safe_format(template: str, **kwargs: str) -> str:
        """str.format that won't crash on {/} in values."""
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError, IndexError) as e:
            logger.warning(
                "[SkillCatalog] str.format failed (template=%r, keys=%s): %s",
                template[:60],
                list(kwargs.keys()),
                e,
            )
            return template + " " + " | ".join(f"{k}={v}" for k, v in kwargs.items())

    def __init__(
        self,
        registry: SkillRegistry,
        usage_tracker: "SkillUsageTracker | None" = None,
        category_registry: "CategoryRegistry | None" = None,
    ):
        self.registry = registry
        # 注：usage_tracker 仍保留供 list_skills 工具与 UI 排序使用，
        # 但 **不再** 影响系统提示中技能清单的展示顺序，
        # 否则新技能（score=0）总被排到末尾，配合截断会被剔除（参考 OpenKitsune 范式）
        self._usage_tracker = usage_tracker
        self._category_registry = category_registry
        self._lock = threading.Lock()
        self._cached_catalog: str | None = None
        self._cached_index: str | None = None
        self._cached_compact: str | None = None
        self._cached_grouped: dict[tuple, str] = {}
        self._cached_metadata: dict[tuple, str] = {}
        self._snapshot_loaded: bool = False  # 单次进程启动只尝试加载一次

    def _list_model_visible(self, exposure_filter: str | None = None) -> list:
        """Return enabled skills that are also visible to the model.

        排序：先按 ``category`` 字典序、再按 ``name`` 字典序（确定性），
        刻意 **不** 按 usage_tracker 倒排，避免新技能因 score=0 永远排末尾
        从而在 prompt 截断时被剔除（参考 OpenKitsune 范式）。

        Args:
            exposure_filter: If provided, only return skills with exposure_level
                in the specified set. Use "core" to get only core skills,
                "core+recommended" to get core and recommended skills.
                None returns all non-hidden skills (backward compatible).
        """
        _allowed_levels = None
        if exposure_filter == "core":
            _allowed_levels = {"core"}
        elif exposure_filter == "core+recommended":
            _allowed_levels = {"core", "recommended"}

        skills = []
        for s in self.registry.list_enabled():
            if s.disable_model_invocation or s.catalog_hidden:
                continue
            if (
                _allowed_levels
                and getattr(s, "exposure_level", "recommended") not in _allowed_levels
            ):
                continue
            skills.append(s)

        skills.sort(
            key=lambda s: (
                (s.category or "Uncategorized").lower(),
                (s.name or "").lower(),
            )
        )
        return skills

    def generate_catalog(self, *, exposure_filter: str | None = None) -> str:
        """
        生成已启用技能目录。

        这是旧接口，仍被启动预热、技能安装/重载和若干 CLI/debug 路径调用。
        默认必须保持目录式输出，避免这些旁路重新生成 name + description +
        when_to_use 的长清单并进入缓存或提示词。需要按任务展开摘要时使用
        get_grouped_compact_catalog()；需要完整说明时使用 get_skill_info。

        Args:
            exposure_filter: "core" | "core+recommended" | None
                控制按 exposure_level 过滤。CONSUMER_CHAT 场景传 "core"，
                IM_ASSISTANT 传 "core+recommended"，LOCAL_AGENT 传 None。
        """
        catalog = self.get_index_catalog(exposure_filter=exposure_filter)
        if exposure_filter is None:
            self._cached_catalog = catalog
        return catalog

    def get_catalog(self, refresh: bool = False) -> str:
        """
        获取技能清单

        Args:
            refresh: 是否强制刷新
        """
        if refresh or self._cached_catalog is None:
            return self.generate_catalog()
        return self._cached_catalog

    def get_compact_catalog(self) -> str:
        """获取紧凑版技能清单 (仅名称列表)，用于 token 受限场景。"""
        with self._lock:
            skills = self._list_model_visible()
            if not skills:
                result = "No skills installed."
            else:
                names = [skill_catalog_name(s) for s in skills]
                result = f"Available skills: {', '.join(names)}"
            self._cached_compact = result
            return result

    @staticmethod
    def _estimate_metadata_tokens(text: str) -> int:
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        other_chars = len(text) - chinese_chars
        return max(int(chinese_chars / 1.5 + other_chars / 4), 1)

    @staticmethod
    def _metadata_source_locator(skill: object) -> str:
        skill_id = str(getattr(skill, "skill_id", "") or getattr(skill, "name", "skill"))
        plugin_source = str(getattr(skill, "plugin_source", "") or "").removeprefix("plugin:")
        if plugin_source:
            return f"plugin://{plugin_source}/{skill_id}"
        if getattr(skill, "system", False):
            return f"builtin://{skill_id}"
        return f"skill://{skill_id}"

    def get_metadata_catalog(
        self,
        *,
        context_window: int | None = None,
        max_tokens: int | None = None,
        exposure_filter: str | None = None,
        priority_categories: tuple[str, ...] | None = None,
    ) -> str:
        """Return the bounded, model-visible skill catalog.

        Only discovery metadata is exposed here. Full ``SKILL.md`` instructions
        remain behind ``get_skill_info``. The complete rendered catalog is capped
        at the lower of 2% of a known model context window and an explicit
        absolute ceiling. Descriptions are shortened before lower-priority
        skills are omitted.
        """
        normalized_window = int(context_window or 0)
        requested_budget = int(max_tokens or MAX_SKILL_METADATA_TOKEN_BUDGET)
        requested_budget = max(1, min(requested_budget, MAX_SKILL_METADATA_TOKEN_BUDGET))
        priority = tuple(category.lower() for category in (priority_categories or ()))
        cache_key = (
            exposure_filter,
            normalized_window,
            requested_budget,
            tuple(sorted(priority)),
        )

        with self._lock:
            cached = self._cached_metadata.get(cache_key)
            if cached is not None:
                return cached

            skills = self._list_model_visible(exposure_filter=exposure_filter)
            if not skills:
                result = "## Available Skills\n\nNo skills available for model invocation."
                self._cached_metadata[cache_key] = result
                return result

            priority_set = set(priority)
            exposure_rank = {"core": 0, "recommended": 1, "optional": 2}
            skills.sort(
                key=lambda skill: (
                    0 if str(getattr(skill, "category", "")).lower() in priority_set else 1,
                    exposure_rank.get(str(getattr(skill, "exposure_level", "recommended")), 1),
                    0 if getattr(skill, "system", False) else 1,
                    str(getattr(skill, "category", "") or "uncategorized").lower(),
                    str(getattr(skill, "name", "")).lower(),
                )
            )

            if normalized_window > 0:
                token_budget = min(
                    requested_budget,
                    max(
                        1,
                        normalized_window * SKILL_METADATA_CONTEXT_WINDOW_PERCENT // 100,
                    ),
                )
            else:
                token_budget = min(requested_budget, DEFAULT_SKILL_METADATA_TOKEN_BUDGET)

            def fits(value: str) -> bool:
                return self._estimate_metadata_tokens(value) <= token_budget

            header = [
                "## Available Skills",
                "",
                "Entries below are discovery metadata only. Use `get_skill_info(skill_name)` "
                "to load the complete `SKILL.md` instructions before applying a skill.",
                SKILL_METADATA_ADVISORY,
                "",
            ]

            def render_entry(skill: object, description_limit: int) -> str:
                name = skill_catalog_name(skill)
                description = " ".join(str(getattr(skill, "description", "") or "").split())
                if description_limit <= 0:
                    description = ""
                elif len(description) > description_limit:
                    description = description[: max(1, description_limit - 3)].rstrip() + "..."
                locator = self._metadata_source_locator(skill)
                detail = f": {description}" if description else ""
                return f"- **{name}**{detail} _(source: {locator})_"

            for description_limit in (
                MAX_SKILL_METADATA_DESCRIPTION_CHARS,
                512,
                256,
                128,
                64,
                0,
            ):
                candidate = "\n".join(
                    header + [render_entry(skill, description_limit) for skill in skills]
                )
                if fits(candidate):
                    self._cached_metadata[cache_key] = candidate
                    return candidate

            included = list(skills)
            while included:
                omitted = len(skills) - len(included)
                warning = (
                    f"_Exceeded the skills metadata budget; {omitted} additional skill(s) "
                    "were omitted. Use `list_skills` to discover them._"
                )
                candidate = "\n".join(
                    header + [render_entry(skill, 0) for skill in included] + ["", warning]
                )
                if fits(candidate):
                    self._cached_metadata[cache_key] = candidate
                    return candidate
                included.pop()

            minimal = "## Skills\n\nUse `list_skills` to discover skills on demand."
            if normalized_window > 0 and not fits(minimal):
                minimal = "## Skills"
            self._cached_metadata[cache_key] = minimal
            return minimal

    # ── 意图相关性动态注入（V1） ──────────────────────────────────────────
    # 与静态全量清单不同：按当前用户消息 + 意图 tool_hints 对全部可见技能做
    # 确定性相关性评分（零 LLM 开销），Top-K 技能以完整元数据注入（热区），
    # 其余技能以紧凑索引保留 —— 既"按需注入"又不"残缺"。
    # 完整 SKILL.md 仍由 get_skill_info 按需加载；list_skills 可枚举全量。

    # 每轮查询的 gram 集缓存（技能数多，避免重复切分）
    _QUERY_GRAMS_CACHE: dict[str, frozenset] = {}

    # 热区最低分：低于该分视为"无明确相关技能"（空热区 + 索引引导），
    # 避免误匹配的弱信号技能挤占注入位。6.0 ≈ 两个 2-gram 主题词命中。
    MIN_INTENT_HOT_SCORE = 6.0

    # 泛用功能词/动作词 gram：几乎任何技能文本都可能出现，对"主题相关性"
    # 没有区分度（如"帮我/查一下/一下/今天"），参与打分只会制造误匹配。
    # 这是 NLP 标准的停用词处理：白名单式主题词（小说/论文/小红书/PPT 等）
    # 完全不受影响；若需扩展可在配置中调整（当前为内置集合）。
    # 英文泛词同理（use/this/skill/file/any/time...）——技能描述普遍以
    # "Use this skill any time..." 开头，不剔除会全面污染打分。
    _STOP_GRAMS = frozenset(
        {
            # 中文泛用功能词
            "帮我", "帮我写", "我写", "写一", "写一篇", "一篇", "一下", "查一下",
            "给我", "我想", "我要", "可以", "请问", "怎么", "如何", "什么", "哪些",
            "一个", "一些", "这个", "那个", "今天", "内容", "时候", "还有", "然后",
            "因为", "所以", "关于", "为你", "需要", "进行", "操作", "使用",
            "帮我做", "帮我查", "帮我把", "做一", "做一份", "一份",
            # 英文泛用功能词/动作词
            "use", "uses", "used", "using", "this", "that", "these", "those",
            "with", "without", "for", "the", "and", "or", "not", "when", "you",
            "your", "yours", "can", "could", "will", "would", "should", "need",
            "needs", "want", "make", "makes", "making", "create", "creates",
            "creating", "write", "writes", "writing", "read", "reads", "reading",
            "into", "from", "within", "through", "about", "based", "provide",
            "provides", "providing", "support", "supports", "supporting", "such",
            "also", "via", "both", "all", "each", "any", "way", "ways", "input",
            "output", "file", "files", "data", "info", "information", "tool",
            "tools", "skill", "skills", "task", "tasks", "user", "users",
            "model", "models", "time", "times", "do", "does", "done", "get",
            "gets", "getting", "set", "sets", "setting", "new", "old", "one",
            "two", "more", "most", "some", "thing", "things", "part", "parts",
            "kind", "types", "type", "example", "examples", "please", "help",
            # 短功能词（介词/连词/be 动词等），在 derive 的"纯功能词查询"判定
            # 里同样需要剔除（"When to use this skill" 这类标题无主题词）
            "to", "of", "in", "on", "at", "by", "is", "be", "it", "as", "so",
            "but", "if", "then", "than", "am", "are", "was", "were", "been",
            "has", "have", "had", "did", "does", "its", "our", "their", "them",
            "him", "her", "his", "she", "he", "they", "we", "who", "whom",
            "which", "what", "where", "when", "why", "how", "than", "too",
        }
    )

    # 双语种子别名缓存（懒加载自 config.skills_intent_aliases）
    # 结构：dict[str, list[str]] — 一个中文主题词可对应多个英文术语
    # （如 日历 → ["calendar", "google calendar"]），全部加入查询扩展 gram。
    _ALIAS_MAP: dict[str, list[str]] | None = None
    # 反向别名（英文词 → 中文主题词），由 _ALIAS_MAP 自动倒排生成：
    # 英文查询 "novel" 会扩展出 小说 gram，打通"英文查询 → 中文技能"。
    _ALIAS_MAP_REV: dict[str, list[str]] | None = None

    # 正文评分窗口（懒加载自 config.skills_intent_body_window）
    _BODY_WINDOW: int | None = None

    @classmethod
    def _body_window(cls) -> int:
        if cls._BODY_WINDOW is None:
            try:
                from ..config import settings as _s

                cls._BODY_WINDOW = max(300, int(getattr(_s, "skills_intent_body_window", 2000) or 2000))
            except Exception:
                cls._BODY_WINDOW = 2000
        return cls._BODY_WINDOW

    @classmethod
    def _alias_map(cls) -> dict[str, list[str]]:
        if cls._ALIAS_MAP is None:
            aliases: dict[str, list[str]] = {}
            try:
                from ..config import settings as _s

                rows = getattr(_s, "skills_intent_aliases", None) or []
                for row in rows:
                    if isinstance(row, (list, tuple)) and len(row) >= 2:
                        zh = str(row[0]).strip().lower()
                        en = str(row[1]).strip().lower()
                        if zh and en:
                            aliases.setdefault(zh, [])
                            if en not in aliases[zh]:
                                aliases[zh].append(en)
            except Exception:
                pass
            cls._ALIAS_MAP = aliases
            # 倒排出英文词 → 中文主题词的反向映射，供英文查询扩展中文 gram。
            rev: dict[str, list[str]] = {}
            for zh, en_list in aliases.items():
                for en in en_list:
                    for w in re.findall(r"[a-z0-9]{3,}", en.lower()):
                        if w not in SkillCatalog._STOP_GRAMS:
                            rev.setdefault(w, [])
                            if zh not in rev[w]:
                                rev[w].append(zh)
            cls._ALIAS_MAP_REV = rev
        return cls._ALIAS_MAP

    @classmethod
    def _alias_map_rev(cls) -> dict[str, list[str]]:
        """英文查询词 → 中文主题词列表（懒加载，与 _alias_map 同源倒排）。"""
        if cls._ALIAS_MAP_REV is None:
            _ = cls._alias_map()  # 触发构建（_alias_map 内部会填充 _ALIAS_MAP_REV）
        return cls._ALIAS_MAP_REV or {}

    @staticmethod
    def _query_grams(query_lower: str) -> frozenset[str]:
        """把查询切成可用于匹配的 gram：ASCII 词(len>=3) + 中文 n-gram(2/3/4)。

        中文没有空格分词，用 n-gram 保证"小红书"这类短语能命中技能文本。
        泛用功能词 gram（_STOP_GRAMS）直接剔除，避免无区分度噪声。
        双语别名（_alias_map，配置驱动）做查询扩展：查询含中文主题词时，
        额外加入对应英文术语，打通"中文查询 → 纯英文技能"的跨语言缺口。
        """
        cached = SkillCatalog._QUERY_GRAMS_CACHE.get(query_lower)
        if cached is not None:
            return cached
        grams: set[str] = set()
        for w in re.findall(r"[a-z0-9]+", query_lower):
            if len(w) >= 3 and w not in SkillCatalog._STOP_GRAMS:
                grams.add(w)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", query_lower))
        for n in (4, 3, 2):
            for i in range(len(cjk) - n + 1):
                g = cjk[i : i + n]
                if g not in SkillCatalog._STOP_GRAMS:
                    grams.add(g)
        for zh, en_list in SkillCatalog._alias_map().items():
            if zh in query_lower:
                for en in en_list:
                    for w in re.findall(r"[a-z0-9]+", en):
                        if len(w) >= 3 and w not in SkillCatalog._STOP_GRAMS:
                            grams.add(w)
        # 反向扩展：查询里的英文词命中别名表的英文侧时，补上对应中文
        # 主题词的 n-gram（"novel" → 小说），英文查询也能命中中文技能。
        for w in list(grams):
            for zh in SkillCatalog._alias_map_rev().get(w, []):
                zh_cjk = "".join(re.findall(r"[\u4e00-\u9fff]", zh))
                for n in (4, 3, 2):
                    for i in range(len(zh_cjk) - n + 1):
                        g = zh_cjk[i : i + n]
                        if g and g not in SkillCatalog._STOP_GRAMS:
                            grams.add(g)
        if len(SkillCatalog._QUERY_GRAMS_CACHE) > 64:
            SkillCatalog._QUERY_GRAMS_CACHE.clear()
        SkillCatalog._QUERY_GRAMS_CACHE[query_lower] = frozenset(grams)
        return frozenset(grams)

    # ASCII gram 的边界匹配模式缓存（懒编译）
    _ASCII_PAT: dict[str, "re.Pattern[str]"] = {}

    @staticmethod
    def _count_hits(text: str, g: str) -> int:
        """单 gram 在文本中的命中次数（封顶 4）。

        - ASCII 词（len>=3）：词边界匹配 + 最多 2 个后缀字符容错
          （"ppt" 命中 "pptx"、"post" 命中 "posts"，但 "post" 不命中
          "postmortem"）。避免"复盘技能靠 post 子串凑分"这类污染。
        - 中文 gram：无词边界概念，保持子串计数。
        """
        if len(g) >= 3 and re.fullmatch(r"[a-z0-9]+", g):
            pat = SkillCatalog._ASCII_PAT.get(g)
            if pat is None:
                pat = re.compile(r"(?<![a-z0-9])" + re.escape(g) + r"[a-z]{0,2}(?![a-z0-9])")
                if len(SkillCatalog._ASCII_PAT) > 256:
                    SkillCatalog._ASCII_PAT.clear()
                SkillCatalog._ASCII_PAT[g] = pat
            return min(len(pat.findall(text)), 4)
        return min(text.count(g), 4)

    @staticmethod
    def _text_hits(text: str, grams: frozenset[str]) -> float:
        """文本对查询 gram 的加权命中分：按出现次数计（每 gram 封顶 4 次）。

        权重：4-gram +5 / 3-gram +3 / 2-gram +1.5。按次数累计让真正
        "以该词为主题"的技能（全文反复出现）明显高于只碰巧提一次的技能。
        """
        if not text:
            return 0.0
        total = 0.0
        for g in grams:
            n = len(g)
            if n < 2:
                continue
            cnt = SkillCatalog._count_hits(text, g)
            if cnt == 0:
                continue
            weight = 5.0 if n >= 4 else (3.0 if n == 3 else 1.5)
            total += cnt * weight
        return total

    @classmethod
    def _score_skill(cls, query_lower: str, priority_set: set[str], skill: object) -> float:
        """Deterministic relevance score for one skill against the current query.

        信号（从强到弱）：
        - intent 分类命中（来自 IntentAnalyzer.tool_hints 映射）+30
        - marketplace_name / name 在查询中整词命中 +20
        - 每个 keyword 子串命中 +25（keywords 是技能作者设计的触发词）
        - when_to_use 文本 gram 命中 ×1.5（封顶 40，短语最具体）
        - description 文本 gram 命中（封顶 30）
        - SKILL.md 正文预览（~600 字符）gram 命中（封顶 25，解决市场技能
          frontmatter 为英文、用户查询为中文的跨语言缺口）
        - name 文本 gram 命中（封顶 10）
        - 2-gram 参与以上全部信号（按次数加权），避免"小说/论文/股票"
          等短词因 <3 字符被漏掉

        全部信号低于 ``MIN_INTENT_HOT_SCORE`` = 无明确相关技能。
        """
        name = str(getattr(skill, "name", "") or "").lower()
        category = str(getattr(skill, "category", "") or "")
        keywords = list(getattr(skill, "keywords", []) or [])
        when = str(getattr(skill, "when_to_use", "") or "").lower()
        desc = str(getattr(skill, "description", "") or "").lower()

        score = 0.0
        grams = cls._query_grams(query_lower)

        when_hits = min(cls._text_hits(when, grams) * 1.5, 40.0)
        desc_hits = min(cls._text_hits(desc, grams), 30.0)

        body_hits = 0.0
        body_loader = getattr(skill, "get_body", None)
        if callable(body_loader):
            try:
                body_preview = str(body_loader())[: cls._body_window()].lower()
                body_hits = min(cls._text_hits(body_preview, grams), 25.0)
            except Exception:
                pass

        name_hits = min(cls._text_hits(name, grams), 10.0)
        lexical_total = when_hits + desc_hits + body_hits + name_hits

        # 分类命中提升（意图 hint → 真实分类 +30）只在技能本身已有词法命中的
        # 前提下生效：分类加分是"放大器"，不创造相关性。否则 File System 这类
        # 兜底 hint 会把整类文件工具技能灌进每一个热区，淹没真正的主题技能。
        if category.lower() in priority_set and lexical_total > 0:
            score += 30.0

        official = getattr(skill, "marketplace_name", None)
        for probe in (official, getattr(skill, "name", "")):
            if isinstance(probe, str) and probe:
                p_l = probe.lower()
                if p_l in query_lower:
                    score += 20.0
                    break
                # 名称尾部 token 精确命中（如查询含 "xiaohongshu" → 命中
                # name=...@xiaohongshu-creator 的 token）是 IR 里的标题命中
                # 强信号，给足权重，避免被"正文凑词"的泛技能压过。
                tail = p_l.rsplit("/", 1)[-1].rsplit("@", 1)[-1]
                if any(tok in query_lower for tok in re.findall(r"[a-z0-9]{3,}", tail)):
                    score += 20.0
                    break

        for kw in keywords:
            kw_l = str(kw).strip().lower()
            if kw_l and kw_l in query_lower:
                score += 25.0

        score += when_hits
        score += desc_hits
        score += body_hits
        score += name_hits
        return score

    def get_intent_catalog(
        self,
        *,
        query: str = "",
        intent_tool_hints: list[str] | None = None,
        top_k: int = 12,
        max_tokens: int | None = None,
        exposure_filter: str | None = None,
        index_mode: str = "count",
    ) -> str:
        """按当前任务相关性动态注入技能清单（热区 Top-K + 剩余索引）。

        Args:
            query: 当前用户消息原文（用于相关性评分）。
            intent_tool_hints: IntentAnalyzer 产出的抽象工具类别（如
                "File System"），命中分类的技能会被提升到热区。
            top_k: 热区保留详细元数据的技能数量上限。
            max_tokens: 整段预算；超预算时先缩描述、再降 top_k。
            exposure_filter: "core" / "core+recommended" / None。
            index_mode: "count"(默认，仅提示数量 + list_skills 发现，最省 token)
                / "names"(保留全部技能名索引，0 丢失) / "none"(不展示热区之外)。

        Returns:
            渲染后的技能目录段。查询与意图均为空时回退到静态全量目录
            ``get_metadata_catalog``（兼容旧行为，保证不残缺）。
        """
        query_lower = (query or "").strip().lower()
        hints = [str(h).strip().lower() for h in (intent_tool_hints or []) if str(h).strip()]
        if not query_lower and not hints:
            return self.get_metadata_catalog(
                max_tokens=max_tokens,
                exposure_filter=exposure_filter,
            )

        priority_set: set[str] = set()
        if hints:
            try:
                from ..prompt.budget import intent_to_priority_categories

                priority_set = set(intent_to_priority_categories(hints))
            except Exception as e:
                logger.debug("[SkillCatalog] intent priority mapping failed: %s", e)

        skills = self._list_model_visible(exposure_filter=exposure_filter)
        if not skills:
            return "## Available Skills\n\nNo skills available for model invocation."

        scored = [
            (s, self._score_skill(query_lower, priority_set, s)) for s in skills
        ]
        scored.sort(
            key=lambda t: (
                -t[1],
                (t[0].category or "Uncategorized").lower(),
                (t[0].name or "").lower(),
            )
        )
        _k = max(1, min(int(top_k or 12), len(skills)))
        hot = [s for s, sc in scored if sc >= self.MIN_INTENT_HOT_SCORE][:_k]
        hot_ids = {id(s) for s in hot}
        rest = [s for s, _ in scored if id(s) not in hot_ids]

        def _index_name(s: object) -> str:
            """索引用最短唯一标识（registry sid），比带命名空间的长名省 token。"""
            sid = str(getattr(s, "skill_id", "") or "")
            if sid:
                return sid
            return str(getattr(s, "name", "") or "")

        def _render(when_limit: int) -> str:
            lines = [
                "## Available Skills (relevant to current request)",
                "",
                "Entries below are discovery metadata only. Use `get_skill_info(skill_name)` "
                "to load the complete `SKILL.md` instructions before applying a skill.",
                SKILL_METADATA_ADVISORY,
                "",
                "### Relevant",
            ]
            if hot:
                for s in hot:
                    name = skill_catalog_name(s)
                    desc = " ".join(str(getattr(s, "description", "") or "").split())
                    when = (str(getattr(s, "when_to_use", "") or "").strip() or "")[:when_limit]
                    if when:
                        lines.append(
                            self._safe_format(
                                "- **{name}**: {desc} _(Use when: {when})_",
                                name=name,
                                desc=(desc[:120] + "..." if len(desc) > 120 else desc),
                                when=when,
                            )
                        )
                    else:
                        lines.append(
                            self._safe_format("- **{name}**: {desc}", name=name, desc=desc[:160])
                        )
            else:
                lines.append(
                    "_No clearly relevant skill matched this request — use `list_skills` "
                    "to discover, then `get_skill_info` to load._"
                )
            if rest:
                lines.append("")
                if index_mode == "names":
                    names = ", ".join(_index_name(s) for s in rest)
                    lines.append(f"### Other skills ({len(rest)}) — use `get_skill_info` to load")
                    lines.append(names)
                elif index_mode == "count":
                    lines.append(
                        f"_({len(rest)} more skill(s) — use `list_skills` to discover, "
                        "then `get_skill_info` to load._"
                    )
            return "\n".join(lines)

        budget = max(1, int(max_tokens or 0)) if max_tokens else 0
        for when_limit in (160, 80, 0):
            candidate = _render(when_limit)
            if budget <= 0 or self._estimate_metadata_tokens(candidate) <= budget:
                return candidate
            if when_limit == 0:
                break

        # 预算仍超：收缩热区（保留至少 1 个），索引始终 0 丢失
        while len(hot) > 1:
            hot.pop()
            hot_ids = {id(x) for x in hot}
            rest = [s for s, _ in scored if id(s) not in hot_ids]
            candidate = _render(0)
            if budget <= 0 or self._estimate_metadata_tokens(candidate) <= budget:
                return candidate
        return _render(0)

    def get_grouped_compact_catalog(
        self,
        *,
        exposure_filter: str | None = None,
        max_tokens: int = 0,
        priority_categories: tuple[str, ...] | None = None,
    ) -> str:
        """生成 **按分类分组的紧凑技能清单**，用于系统提示注入。

        零丢失 + 自适应压缩：
        - 所有技能名字始终保留（保证 LLM 能发现并调用）
        - 按分类字典序、再按 name 字典序输出（确定性，避免抖动）
        - 分类标题展示 ``DESCRIPTION.md`` 的描述（如果有）

        当 ``max_tokens > 0`` 时启用三级自适应压缩：
        - Level B (默认): ``- **name**: when_to_use`` (描述截至 160 字符)
        - Level B-short: 描述缩短至 80 字符（技能数 > 80 时自动触发）
        - Level C (index): 分类 + 逗号分隔名字，无描述

        当 ``priority_categories`` 非空时启用**分类优先级裁剪**（Fix-4）：
        - 列入优先级集合的分类按 Level B/B-short 输出（保留描述）
        - 其余分类一律降级为 Level C（仅名字），由 LLM 通过
          ``get_skill_info`` 按需展开。这种"主线详细 + 长尾索引"
          的混合模式可在保留全量发现能力的同时显著节省 token。

        缓存：按 ``(exposure_filter, max_tokens, priority_categories)`` 维度缓存。
        """
        with self._lock:
            cache_key = (
                exposure_filter,
                max_tokens,
                tuple(sorted(priority_categories or ())),
            )
            cached = self._cached_grouped.get(cache_key)
            if cached is not None:
                return cached

            # L2：进程首次未命中时尝试从磁盘 snapshot prime L1
            if not self._snapshot_loaded:
                self._snapshot_loaded = True
                try:
                    primed = self._load_disk_snapshot_if_valid()
                    if primed:
                        self._cached_grouped.update(primed)
                        if cache_key in primed:
                            return primed[cache_key]
                except Exception as e:
                    logger.debug("Skill catalog snapshot prime failed: %s", e)

            skills = self._list_model_visible(exposure_filter=exposure_filter)
            hidden_count = self.registry.count_catalog_hidden()

            if not skills:
                if hidden_count > 0:
                    result = (
                        "## Available Skills\n\n"
                        "No skills pre-loaded for this profile. "
                        f"{hidden_count} more skill(s) available — "
                        "use `list_skills` to discover, then `get_skill_info` to load."
                    )
                else:
                    result = (
                        "## Available Skills\n\n"
                        "No skills installed. Use the skill creation workflow to add new skills."
                    )
                self._cached_grouped[cache_key] = result
                return result

            grouped: dict[str, list] = {}
            for s in skills:
                cat = s.category or "Uncategorized"
                grouped.setdefault(cat, []).append(s)

            cat_descriptions: dict[str, str | None] = {}
            if self._category_registry is not None:
                try:
                    for entry in self._category_registry.list_all():
                        cat_descriptions[entry.name] = entry.description
                except Exception:
                    pass

            sorted_cats = sorted(grouped.keys(), key=lambda x: x.lower())

            def _render(when_max: int) -> str:
                """渲染带描述的技能清单 (Level B)"""
                lines: list[str] = [
                    "## Available Skills",
                    "",
                    "Use `get_skill_info(skill_name)` to load full instructions when needed.",
                    SKILL_INSTRUCTION_ADVISORY,
                    "",
                ]
                for cat in sorted_cats:
                    desc = cat_descriptions.get(cat)
                    lines.append(f"### {cat} — {desc}" if desc else f"### {cat}")
                    for s in grouped[cat]:
                        when = (getattr(s, "when_to_use", "") or "").strip()
                        if not when:
                            when = (s.description or "").split("\n")[0].strip()
                        when = when[:when_max]
                        lines.append(
                            self._safe_format(
                                "- **{name}**: {when}",
                                name=skill_catalog_name(s),
                                when=when,
                            )
                        )
                    lines.append("")
                if hidden_count > 0:
                    lines.append(
                        f"_({hidden_count} more skill(s) hidden by profile — "
                        "use `list_skills` to enumerate)_"
                    )
                return "\n".join(lines).rstrip() + "\n"

            def _render_index() -> str:
                """渲染仅名字的紧凑清单 (Level C)"""
                lines: list[str] = [
                    "## Available Skills",
                    "",
                    "Use `get_skill_info(skill_name)` to load full instructions before using a skill.",
                    SKILL_INSTRUCTION_ADVISORY,
                    "",
                ]
                for cat in sorted_cats:
                    names = [skill_catalog_name(s) for s in grouped[cat]]
                    desc = cat_descriptions.get(cat)
                    lines.append(f"### {cat} — {desc}" if desc else f"### {cat}")
                    lines.append(", ".join(names))
                    lines.append("")
                if hidden_count > 0:
                    lines.append(
                        f"_({hidden_count} more skill(s) hidden by profile — "
                        "use `list_skills` to enumerate)_"
                    )
                return "\n".join(lines).rstrip() + "\n"

            def _est_tokens(text: str) -> int:
                return max(len(text) // 4, len(text.encode("utf-8")) // 3)

            def _render_mixed(when_max: int) -> str:
                """混合模式：priority 分类用 Level B；其余用 Level C。"""
                priority_set = {c.lower() for c in (priority_categories or ())}
                lines: list[str] = [
                    "## Available Skills",
                    "",
                    "Use `get_skill_info(skill_name)` to load full instructions when needed.",
                    SKILL_INSTRUCTION_ADVISORY,
                    "",
                ]
                for cat in sorted_cats:
                    desc = cat_descriptions.get(cat)
                    is_priority = cat.lower() in priority_set
                    if is_priority:
                        # Level B 详细
                        lines.append(f"### {cat} — {desc}" if desc else f"### {cat}")
                        for s in grouped[cat]:
                            when = (getattr(s, "when_to_use", "") or "").strip()
                            if not when:
                                when = (s.description or "").split("\n")[0].strip()
                            when = when[:when_max]
                            lines.append(
                                self._safe_format(
                                    "- **{name}**: {when}",
                                    name=skill_catalog_name(s),
                                    when=when,
                                )
                            )
                        lines.append("")
                    else:
                        # Level C 仅名字 — 用 (index) 后缀提示
                        names = [skill_catalog_name(s) for s in grouped[cat]]
                        title = f"### {cat} (index) — {desc}" if desc else f"### {cat} (index)"
                        lines.append(title)
                        lines.append(", ".join(names))
                        lines.append("")
                if hidden_count > 0:
                    lines.append(
                        f"_({hidden_count} more skill(s) hidden by profile — "
                        "use `list_skills` to enumerate)_"
                    )
                return "\n".join(lines).rstrip() + "\n"

            if max_tokens <= 0:
                result = _render_mixed(160) if priority_categories else _render(160)
            else:
                if priority_categories:
                    result = _render_mixed(160)
                    if _est_tokens(result) > max_tokens:
                        result = _render_mixed(80)
                else:
                    result = _render(160)
                    if _est_tokens(result) > max_tokens:
                        result = _render(80)
                if _est_tokens(result) > max_tokens:
                    result = _render_index()

            self._cached_grouped[cache_key] = result
            logger.debug(
                "Generated grouped catalog: %d skills across %d categories "
                "(~%d tokens, max_tokens=%d)",
                len(skills),
                len(grouped),
                _est_tokens(result),
                max_tokens,
            )
            try:
                self._write_disk_snapshot()
            except Exception as e:
                logger.debug("Skill catalog snapshot write failed: %s", e)
            return result

    def get_index_catalog(self, *, exposure_filter: str | None = None) -> str:
        """
        获取已启用技能的"全量索引"（仅名称，尽量短，但完整）。

        Args:
            exposure_filter: "core" | "core+recommended" | None
        """
        with self._lock:
            skills = self._list_model_visible(exposure_filter=exposure_filter)
            hidden_count = self.registry.count_catalog_hidden()
            if not skills:
                if hidden_count > 0:
                    result = (
                        "## Skills Index\n\n"
                        "No skills pre-loaded for this profile. "
                        f"{hidden_count} more skill(s) available via `list_skills`."
                    )
                else:
                    result = "## Skills Index (complete)\n\nNo skills installed."
                if exposure_filter is None:
                    self._cached_index = result
                return result

            system_names: list[str] = []
            external_names: list[str] = []
            plugin_entries: list[str] = []

            for s in skills:
                if getattr(s, "system", False):
                    system_names.append(skill_catalog_name(s))
                elif getattr(s, "plugin_source", None):
                    plugin_id = s.plugin_source.replace("plugin:", "")
                    plugin_entries.append(f"{skill_catalog_name(s)} (via {plugin_id})")
                else:
                    external_names.append(skill_catalog_name(s))

            system_names.sort()
            external_names.sort()
            plugin_entries.sort()

            lines: list[str] = [
                "## Skills Index (complete)",
                "",
                "Use `get_skill_info(skill_name)` to load full instructions.",
                "Most external skills are **instruction-only** (no pre-built scripts) "
                "\u2014 read instructions via get_skill_info, then write code and execute via run_shell.",
                "Only use `run_skill_script` when a skill explicitly lists executable scripts.",
                SKILL_INSTRUCTION_ADVISORY,
            ]

            if system_names:
                lines += ["", f"**System skills ({len(system_names)})**: {', '.join(system_names)}"]
            if external_names:
                lines += [
                    "",
                    f"**External skills ({len(external_names)})**: {', '.join(external_names)}",
                ]
            if plugin_entries:
                lines += [
                    "",
                    f"**Plugin skills ({len(plugin_entries)})**: {', '.join(plugin_entries)}",
                ]

            result = "\n".join(lines)
            if exposure_filter is None:
                self._cached_index = result
            return result

    def generate_catalog_budgeted(self, budget_chars: int = 0) -> str:
        """Generate catalog with three-level degradation if budget_chars is set.

        Level A: full (name + description + when_to_use) via generate_catalog()
        Level B: name + short hint for each skill
        Level C: comma-separated names only

        If budget_chars <= 0, returns full catalog without budget constraint.
        """
        if budget_chars <= 0:
            return self.generate_catalog()

        full = self.generate_catalog()
        if len(full) <= budget_chars:
            return full

        # Level B: name + short hint
        with self._lock:
            skills = self._list_model_visible()
            if not skills:
                return "No skills installed."
            b_lines = ["## Skills (compact)"]
            for s in skills:
                hint = getattr(s, "when_to_use", "") or ""
                if hint:
                    b_lines.append(f"- **{skill_catalog_name(s)}**: {hint[:60]}")
                else:
                    desc_short = (s.description or "")[:40]
                    b_lines.append(f"- **{skill_catalog_name(s)}**: {desc_short}")
            level_b = "\n".join(b_lines)
            if len(level_b) <= budget_chars:
                return level_b

            # Level C: names only
            names = [skill_catalog_name(s) for s in skills]
            return f"Skills ({len(skills)}): {', '.join(names)}"

    def get_skill_summary(self, skill_name: str) -> str | None:
        """获取单个技能的摘要"""
        skill = self.registry.get(skill_name)
        if not skill:
            return None
        return f"**{skill_catalog_name(skill)}**: {skill.description}"

    def generate_recommendation_hint(
        self,
        task_description: str,
        *,
        max_hints: int = 3,
        max_chars: int = 250,
        exposure_filter: str | None = None,
    ) -> str:
        """根据用户输入生成轻量技能推荐 hint。

        基于 when_to_use 和 keywords 做简单关键词匹配，不调用 LLM。
        返回格式如: "💡 可能有用的技能: web-search (搜索网页), ..."

        Args:
            task_description: 用户的任务描述/输入
            max_hints: 最多推荐几个技能
            max_chars: hint 总长度上限
            exposure_filter: "core" / "core+recommended" / None(all except hidden)
        """
        if not task_description:
            return ""

        _allowed: set[str] | None = None
        if exposure_filter == "core":
            _allowed = {"core"}
        elif exposure_filter == "core+recommended":
            _allowed = {"core", "recommended"}
        query_lower = task_description.lower()
        candidates: list[tuple[float, str, str]] = []

        for s in self.registry.list_enabled():
            if s.disable_model_invocation or s.catalog_hidden:
                continue
            _exp = getattr(s, "exposure_level", "recommended")
            if _allowed and _exp not in _allowed:
                continue

            score = 0.0
            official = getattr(s, "marketplace_name", None)
            if isinstance(official, str) and official and official.lower() in query_lower:
                score += 10.0
            when = getattr(s, "when_to_use", "") or ""
            kws = getattr(s, "keywords", []) or []

            for kw in kws:
                if kw.lower() in query_lower:
                    score += 2.0
            if when:
                when_words = when.lower().split()
                for w in when_words:
                    if len(w) > 2 and w in query_lower:
                        score += 0.5

            if score > 0:
                short_desc = (s.description or "")[:40]
                candidates.append((score, skill_catalog_name(s), short_desc))

        if not candidates:
            return ""

        candidates.sort(key=lambda x: x[0], reverse=True)
        top = candidates[:max_hints]
        parts = [f"{name} ({desc})" for _, name, desc in top]
        hint = "💡 可能有用的技能: " + ", ".join(parts)

        if len(hint) > max_chars:
            hint = hint[: max_chars - 3] + "..."
        return hint

    def invalidate_cache(self) -> None:
        """使所有缓存失效"""
        with self._lock:
            self._cached_catalog = None
            self._cached_index = None
            self._cached_compact = None
            self._cached_grouped.clear()
            self._cached_metadata.clear()
        self._invalidate_disk_snapshot()

    @property
    def skill_count(self) -> int:
        """技能数量"""
        return self.registry.count

    # ── 二层缓存：磁盘 snapshot（参考 OpenKitsune） ──────────────────

    @staticmethod
    def _snapshot_path() -> Path | None:
        """返回 ``data/.skills_prompt_snapshot.json`` 的绝对路径。"""
        try:
            from ..config import settings

            return Path(settings.project_root) / "data" / ".skills_prompt_snapshot.json"
        except Exception:
            try:
                return Path.cwd() / "data" / ".skills_prompt_snapshot.json"
            except Exception:
                return None

    def _build_manifest(self) -> dict[str, list[int]]:
        """收集所有 SKILL.md / DESCRIPTION.md 的 (mtime_ns, size) 作为 manifest。"""
        manifest: dict[str, list[int]] = {}
        seen_dirs: set[str] = set()
        for entry in self.registry.list_all():
            sp = getattr(entry, "skill_path", None)
            if not sp:
                continue
            try:
                p = Path(sp)
                if p.exists():
                    st = p.stat()
                    manifest[str(p)] = [st.st_mtime_ns, st.st_size]
                # 同级或上溯查找 DESCRIPTION.md（最多向上 4 层）
                cur = p.parent
                for _ in range(4):
                    key = str(cur)
                    if key in seen_dirs:
                        break
                    seen_dirs.add(key)
                    desc = cur / "DESCRIPTION.md"
                    if desc.exists():
                        st = desc.stat()
                        manifest[str(desc)] = [st.st_mtime_ns, st.st_size]
                    if cur.parent == cur:
                        break
                    cur = cur.parent
            except OSError:
                continue
        return manifest

    def _load_disk_snapshot_if_valid(self) -> dict[tuple, str] | None:
        """如果 manifest 与 snapshot 一致，返回缓存字典。

        磁盘快照只存 max_tokens=0 的无预算版本（完整描述），
        预算压缩版在内存中按需从完整版推导，不持久化。
        """
        path = self._snapshot_path()
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        snap_manifest = data.get("manifest")
        snap_catalogs = data.get("catalogs")
        if not isinstance(snap_manifest, dict) or not isinstance(snap_catalogs, dict):
            return None
        current = self._build_manifest()
        if current != snap_manifest:
            return None
        if data.get("marketplace_names", {}) != self._marketplace_name_snapshot():
            return None
        result: dict[tuple, str] = {}
        for k, v in snap_catalogs.items():
            if not isinstance(v, str):
                continue
            exposure: str | None = k if k else None
            result[(exposure, 0)] = v
        return result

    def _write_disk_snapshot(self) -> None:
        """原子地把 L1 缓存写入磁盘 snapshot。"""
        path = self._snapshot_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        manifest = self._build_manifest()
        # 只持久化 max_tokens=0 的无预算版本；预算压缩版在内存中按需推导
        catalogs = {}
        for (exposure, mt), v in self._cached_grouped.items():
            if mt == 0:
                catalogs[exposure if exposure is not None else ""] = v
        payload = {
            "version": 1, "manifest": manifest, "catalogs": catalogs,
            "marketplace_names": self._marketplace_name_snapshot(),
        }

        try:
            tmp_fd, tmp_str = tempfile.mkstemp(
                prefix=".skills_snap.", suffix=".json.tmp", dir=str(path.parent)
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp_path, path)
        except OSError as e:
            logger.debug("Snapshot write failed: %s", e)
            try:
                if "tmp_path" in locals() and tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    def _marketplace_name_snapshot(self) -> dict[str, str]:
        return {
            entry.skill_id: entry.marketplace_name for entry in self.registry.list_all()
            if isinstance(getattr(entry, "marketplace_name", None), str) and entry.marketplace_name
        }

    def _invalidate_disk_snapshot(self) -> None:
        """清空磁盘 snapshot 与 ``_snapshot_loaded`` 标记。"""
        self._snapshot_loaded = False
        path = self._snapshot_path()
        if path is None:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.debug("Snapshot delete failed: %s", e)


def generate_skill_catalog(registry: SkillRegistry) -> str:
    """便捷函数：生成技能清单"""
    catalog = SkillCatalog(registry)
    return catalog.generate_catalog()
