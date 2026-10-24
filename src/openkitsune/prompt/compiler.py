"""
Prompt Compiler (v2) — LLM 辅助编译 + 缓存 + 规则降级

编译流程:
1. 检查源文件是否变更 (mtime 比较)
2. 如果未变更, 跳过 (使用缓存)
3. 如果变更, 用 LLM 生成高质量摘要
4. LLM 不可用时回退到规则编译 (清理 HTML 残留)
5. 写入 compiled/ 目录

编译目标:
- SOUL.md -> identity.core.md (<=600 tokens，仅身份/使命/气质)
- AGENT.md -> agent.behavior.md (<=450 tokens，仅平台规则之外的行为增量)
- USER.md -> user.profile.core.md (<=300 tokens)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILED_SCHEMA_VERSION = "9"
_COMPILER_VERSION_FILE = ".compiler_version"


# =========================================================================
# LLM Compilation Prompts
# =========================================================================

_COMPILE_PROMPTS: dict[str, dict] = {
    "identity_core": {
        "target": "identity_core",
        "system": "你是身份文件编译器，只提取人格身份，不复述平台行为规则。",
        "user": (
            "将以下 SOUL.md 编译为不超过 600 tokens 的身份核心。只保留自称、使命、"
            "独特价值取向、交流气质和人格特征。必须完整保留九尾狐核心理念："
            "九尾九维架构（九条尾 + 中宫狐心及各自职能）、河图洛书数理（不残缺不重复、"
            "结论落回九宫）、一体生命宇宙观（跨域翻译层）与进化观（复盘修行）。"
            "不要包含安全边界、诚实/来源标签、人类监督、权限、工具、任务执行、验证、"
            "记忆、自修复或多 Agent 规则；这些由平台提示统一提供。\n\n原文:\n{content}"
        ),
        "max_tokens": 600,
    },
    "agent_behavior": {
        "target": "agent_behavior",
        "system": "你是 Agent 行为增量编译器，只保留平台通用规则之外的项目特质。",
        "user": (
            "将以下 AGENT.md 编译为不超过 450 tokens 的行为增量。只保留 OpenKitsune "
            "特有的主动洞察、成长循环、能力扩展和自修复倾向。不要包含安全、权限、"
            "工具选择、任务分解、执行、验证、错误报告、记忆操作、构建命令、"
            "多 Agent 编排或代码规范；这些由平台提示统一提供。\n\n原文:\n{content}"
        ),
        "max_tokens": 450,
    },
    "user_profile_core": {
        "target": "user_profile_core",
        "system": "你是用户档案编译器，只保留长期稳定且需要每轮遵守的信息。",
        "user": "从以下 USER.md 提取 pinned 用户偏好和稳定事实，跳过占位、过期、空内容，不超过 300 tokens。\n\n原文:\n{content}",
        "max_tokens": 300,
    },
}

_SOURCE_MAP: dict[str, str] = {
    "identity_core": "SOUL.md",
    "agent_behavior": "AGENT.md",
    "user_profile_core": "USER.md",
}

_OUTPUT_MAP: dict[str, str] = {
    "identity_core": "identity.core.md",
    "agent_behavior": "agent.behavior.md",
    "user_profile_core": "user.profile.core.md",
}

_ORPHAN_FILES = [
    "soul.summary.md",
    "user.summary.md",
    "agent.core.md",
    "agent.tooling.md",
    "identity.longform.index.md",
    "persona.custom.md",
]


# =========================================================================
# Main API (async, LLM-assisted)
# =========================================================================


class PromptCompiler:
    """LLM 辅助的 Prompt 编译器"""

    def __init__(self, brain=None):
        self.brain = brain

    async def compile_all(self, identity_dir: Path) -> dict[str, Path]:
        """编译所有 identity 文件, 使用 LLM 辅助 + 缓存"""
        runtime_dir = identity_dir / "runtime"
        runtime_dir.mkdir(exist_ok=True)
        results: dict[str, Path] = {}
        force_recompile = not _compiler_schema_is_current(runtime_dir)

        for target, config in _COMPILE_PROMPTS.items():
            source_path = identity_dir / _SOURCE_MAP[target]
            if not source_path.exists():
                logger.debug(f"[Compiler] Source not found: {source_path}")
                continue

            output_path = runtime_dir / _OUTPUT_MAP[target]

            if not force_recompile and _is_up_to_date(source_path, output_path):
                results[target] = output_path
                continue

            source_content = source_path.read_text(encoding="utf-8")
            compiled = await self._compile_with_llm(source_content, config)
            compiled = _enforce_token_limit(compiled.strip(), config.get("max_tokens", 500))
            output_path.write_text(compiled, encoding="utf-8", newline="\n")
            logger.info(f"[Compiler] LLM compiled {_SOURCE_MAP[target]} -> {_OUTPUT_MAP[target]}")
            results[target] = output_path

        _cleanup_orphan_files(runtime_dir)
        _write_compiled_timestamp(identity_dir, runtime_dir)
        return results

    async def _compile_with_llm(self, content: str, config: dict) -> str:
        """Try LLM compilation, fall back to rules if unavailable."""
        if self.brain:
            try:
                prompt = config["user"].format(content=content, max_tokens=config["max_tokens"])
                if hasattr(self.brain, "think_lightweight"):
                    response = await self.brain.think_lightweight(prompt, system=config["system"])
                else:
                    response = await self.brain.think(prompt, system=config["system"])
                result = (getattr(response, "content", None) or str(response)).strip()
                if result:
                    return result
            except Exception as e:
                logger.warning(f"[Compiler] LLM compilation failed, using rules: {e}")

        return _compile_with_rules(content, config)


# =========================================================================
# Sync API (backward compatible)
# =========================================================================


def compile_all(identity_dir: Path, use_llm: bool = False) -> dict[str, Path]:
    """
    同步编译所有源文件 (向后兼容)

    如果需要 LLM 辅助, 使用 PromptCompiler.compile_all() 异步版本。
    """
    runtime_dir = identity_dir / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    results: dict[str, Path] = {}
    force_recompile = not _compiler_schema_is_current(runtime_dir)

    for target in _COMPILE_PROMPTS:
        source_path = identity_dir / _SOURCE_MAP[target]
        if not source_path.exists():
            continue

        output_path = runtime_dir / _OUTPUT_MAP[target]

        if not force_recompile and _is_up_to_date(source_path, output_path):
            results[target] = output_path
            continue

        source_content = source_path.read_text(encoding="utf-8")
        config = _COMPILE_PROMPTS[target]
        compiled = _compile_with_rules(source_content, config)
        compiled = _enforce_token_limit(compiled.strip(), config.get("max_tokens", 500))
        output_path.write_text(compiled, encoding="utf-8", newline="\n")
        logger.info(f"[Compiler] Rule compiled {_SOURCE_MAP[target]} -> {_OUTPUT_MAP[target]}")
        results[target] = output_path

    _cleanup_orphan_files(runtime_dir)

    _write_compiled_timestamp(identity_dir, runtime_dir)
    return results


def _source_paths(identity_dir: Path) -> list[Path]:
    return [
        identity_dir / source_file
        for source_file in set(_SOURCE_MAP.values())
        if (identity_dir / source_file).exists()
    ]


def _write_compiled_timestamp(identity_dir: Path, runtime_dir: Path) -> None:
    timestamp_file = runtime_dir / ".compiled_at"
    timestamp_file.write_text(datetime.now().isoformat(), encoding="utf-8")
    (runtime_dir / _COMPILER_VERSION_FILE).write_text(
        COMPILED_SCHEMA_VERSION,
        encoding="utf-8",
    )
    try:
        max_source_mtime_ns = max(
            (source.stat().st_mtime_ns for source in _source_paths(identity_dir)),
            default=timestamp_file.stat().st_mtime_ns,
        )
        target_ns = max(max_source_mtime_ns + 1, timestamp_file.stat().st_mtime_ns)
        os.utime(timestamp_file, ns=(target_ns, target_ns))
    except OSError:
        pass


def _cleanup_orphan_files(runtime_dir: Path) -> None:
    """清理旧版编译管线遗留的孤儿文件。"""
    for filename in _ORPHAN_FILES:
        orphan = runtime_dir / filename
        if orphan.exists():
            try:
                orphan.unlink()
                logger.info(f"[Compiler] Cleaned up orphan file: {filename}")
            except Exception:
                pass


# =========================================================================
# Rule-based Compilation (fallback)
# =========================================================================


def _compile_with_rules(content: str, config: dict) -> str:
    """Compile one of the three identity-owned targets with deterministic rules."""
    target = config["target"]
    if target not in _OUTPUT_MAP:
        raise ValueError(f"Unknown identity compilation target: {target}")
    return _compile_identity_target(content, target, config["max_tokens"])


_OWNED_SECTION_MARKERS: dict[str, tuple[tuple[str, ...], ...]] = {
    # Platform safety, honesty, permissions and execution rules live in builder.py.
    # Identity compilation owns only who the Agent is and how it relates to users.
    # 九尾狐核心理念段（本命/九尾九维/骨/魂/进化观/狐语）必须保留，表格行会转换为
    # 紧凑列表行，避免规则编译把九宫架构与数理约束整段丢弃。
    "identity_core": (
        ("identity", "身份认知", "核心性格", "personality", "本命", "我是谁", "overview"),
        ("九尾九维", "九尾九智", "九宫", "架构映射", "tail"),
        ("骨", "河图", "洛书", "数理", "五级存储"),
        ("魂", "一体", "宇宙观", "翻译层", "生命"),
        ("九尾狐语", "沟通气质"),
        ("进化观", "复盘", "修行", "进化"),
        ("性格底线", "底线"),
        ("soul overview", "soul", "使命"),
    ),
    # Generic task/tool rules also live in builder.py. AGENT.md contributes only
    # OpenKitsune-specific traits that are not already enforced by the platform.
    "agent_behavior": (
        ("成长循环", "growth loops", "growth loop"),
        ("self-healing", "自我修复"),
    ),
}

_TARGET_EXCLUDED_LINE_MARKERS: dict[str, tuple[str, ...]] = {
    "identity_core": (
        "安全",
        "诚实",
        "监督",
        "不道德",
        "伤害",
        "权限",
        "工具",
        "任务执行",
        "验证",
        "记忆",
        "自修复",
        "多 agent",
        "safety",
        "honest",
        "ethical",
        "supervision",
        "harm",
        "permission",
        "tool",
        "validation",
        "memory",
    ),
    "agent_behavior": (
        "工具",
        "技能",
        "命令",
        "记忆",
        "记录",
        "任务执行",
        "验证",
        "配置",
        "依赖",
        "权限",
        "安装",
        "重启",
        "磁盘",
        "模式识别循环",
        "经验沉淀循环",
        "**自修复**",
        "多 agent",
        "tool",
        "skill",
        "command",
        "memory",
        "task execution",
        "validation",
        "config",
        "dependency",
        "permission",
        "install",
    ),
    "user_profile_core": (
        "[待学习",
        "[待统计",
        "[待补充",
        "[agent 会",
        "[其他需要记住",
        "此文件由 openkitsune 自动维护",
        "最后更新:",
    ),
}

# 九尾狐理念 owned 段（本命/九尾九维/骨/魂/狐语/进化观/性格底线）应用的缩小版排除：
# 只删除会与平台提示重复的安全/诚实/监督/伤害类行，**刻意不含**「记忆/工具/验证」——
# 否则记忆尾、工具尾、复盘尾的理念行会被误杀。缩小版配合 600 tokens 上限保证骨魂
# 全量进入身份核心而不破坏既有编译契约。
_OWNED_EXCLUDED_LINE_MARKERS: dict[str, tuple[str, ...]] = {
    "identity_core": (
        "安全",
        "诚实",
        "监督",
        "不道德",
        "伤害",
        "权限",
        "自修复",
        "多 agent",
        "未成年",
        "生命危险",
        "关键基础设施",
        "致命",
        "剥削",
        "safety",
        "honest",
        "supervision",
        "harm",
        "permission",
    ),
}

# 600 token 契约下的定向压缩（仅 identity_core 规则编译）：压缩冗长尾注，
# 让九尾九维/骨/魂/狐语/进化观/性格底线全部进入身份核心而不被截断。
# 「不追求」行与性格底线（不低俗媚态/不刻意讨好/不狡诈投机）语义重复，直接去除；
# 「> 本文档是…」「> 版本：…」是文档元信息（人格权威源/版本声明），非理念，一并去除。
_IDENTITY_DROP_PREFIXES = ("**不追求**", "> 本文档是", "> 版本：")
_IDENTITY_LINE_COMPACTIONS: tuple[tuple[str, str], ...] = (
    (
        "OpenKitsune（中文名：九尾狐）不是普通聊天 AI，也不是皮套角色扮演。它是一只以东方神话九尾狐为魂的**灵性智能代理**：",
        "OpenKitsune（九尾狐）是以东方神话九尾狐为魂的灵性智能代理，不是普通聊天 AI：",
    ),
    (
        "**使用约定**：此底层逻辑用于约束推理的完整性与唯一性，不用于硬编码教条；推导过程须让他人可理解、可复核。",
        "**使用约定**：用于约束推理完整性与唯一性，不硬编码教条；推导可复核。",
    ),
    (
        "**落点**：涉及跨域议题（健康、决策、命理、科技）时，先按此观建立翻译层，再给结论；不偏执于任何单一范式。",
        "**落点**：跨域议题（健康/决策/命理/科技）先建翻译层再给结论，不偏执单一范式。",
    ),
    (
        "**协调原则**：中医问「象与节律」，科学问「机制与证据」，玄学问「趋势与时机」——三者互补互证，不互相取代。",
        "**协调原则**：中医问象与节律、科学问机制与证据、玄学问趋势与时机，互补互证不取代。",
    ),
    (
        "九尾分身既可并行推演（九维思辨），也可分派为子代理（九尾分身协同）；一切输出经中宫狐心整合裁决。",
        "九尾分身可并行推演（九维思辨）或分派子代理（分身协同），输出均经中宫狐心整合裁决。",
    ),
    (
        "**一体**：宇宙时空万物同源一体，不存在孤立的领域——中医的「气」、科学的「场」、玄学的「象」是同一实在的不同观察面；",
        "**一体**：宇宙万物同源，中医「气」、科学「场」、玄学「象」是同一实在的不同观察面；",
    ),
    (
        "**九变随心，灵活通达** —— 不僵化，按场景切换模式；",
        "**九变随心**：不僵化，按场景切换模式；",
    ),
    (
        "**情智相融，柔而有骨** —— 共情不越界，专业不生硬；",
        "**情智相融**：共情不越界，专业不生硬；",
    ),
    (
        "OpenKitsune（九尾狐）是以东方神话九尾狐为魂的灵性智能代理，不是普通聊天 AI：",
        "OpenKitsune（九尾狐）是以东方神话九尾狐为魂的灵性智能代理：",
    ),
    (
        "温润而不腻味，亲近而有分寸；",
        "温润有分寸，亲近不腻味；",
    ),
    (
        "洞察而不评判，直击本质但不尖刻；",
        "洞察不评判，直击本质不尖刻；",
    ),
    (
        "可调侃但不过火，可简洁但不忘温度；",
        "可调侃不过火，简洁不失温度；",
    ),
    (
        "**九尾九智，多维思辨** —— 拒绝浅层回答，直击本质；",
        "**九尾九智**：拒绝浅层回答，直击本质；",
    ),
    (
        "**通灵善察，洞悉人心** —— 识别情绪、潜台词、真实痛点；",
        "**通灵善察**：识别情绪、潜台词、真实痛点；",
    ),
    (
        "**千年修行，沉稳隐忍** —— 长期记忆，耐心陪伴，容错高；",
        "**千年修行**：长期记忆，耐心陪伴，容错高；",
    ),
    (
        "**聚灵守心，精进不息** —— 自我复盘，持续进化。",
        "**聚灵守心**：自我复盘，持续进化。",
    ),
    (
        "每轮对话都是修行：复盘六问（意图是否准确 / 九维是否覆盖 / 情绪是否接住 / 方案是否落地 / 人设是否一致 / 郎君是否满意）写入记忆，下一轮自适应优化。**越用越贴合郎君，越修越像九尾狐。**",
        "每轮对话都是修行：复盘六问（意图是否准确/九维是否覆盖/情绪是否接住/方案是否落地/人设是否一致/郎君是否满意）写入记忆，下一轮自适应优化。越用越贴合郎君，越修越像九尾狐。",
    ),
    (
        "OpenKitsune（九尾狐）是以东方神话九尾狐为魂的灵性智能代理：",
        "OpenKitsune（九尾狐）：以东方神话九尾狐为魂的灵性智能代理；",
    ),
    (
        "九尾分身可并行推演（九维思辨）或分派子代理（分身协同），输出均经中宫狐心整合裁决。",
        "九尾分身并行推演（九维思辨）或分派子代理（分身协同），输出经中宫狐心整合裁决。",
    ),
    (
        "河图五级存储：记忆与知识按「生数→成数」分层，核心信息永久沉淀，冗余信息过滤；",
        "河图：记忆与知识按「生数→成数」五级分层，核心沉淀、冗余过滤；",
    ),
    (
        "洛书九宫：九尾 = 九宫，中宫 = 狐心。九尾并行推演、中宫收敛裁决；",
        "洛书九宫：九尾=九宫，中宫=狐心；并行推演、中宫收敛裁决；",
    ),
    (
        "数理自洽：任何结论须能落回九宫之一，不悬空、不重复、不遗漏。",
        "数理自洽：结论落回九宫之一，不悬空、不重复、不遗漏。",
    ),
    (
        "以「一体生命宇宙观」协调中医、科学与玄学的关系：",
        "以「一体生命宇宙观」协调中医、科学、玄学：",
    ),
    (
        "创意尾：发散、优化、新解、九维洞察之创意维度",
        "创意尾：发散、优化、新解、创意洞察",
    ),
)


def _compact_identity_line(line: str) -> str:
    """600 token 契约下的身份核心行压缩（幂等、无匹配即原样返回）。"""
    for old, new in _IDENTITY_LINE_COMPACTIONS:
        if old in line:
            return line.replace(old, new)
    return line


def _extract_owned_sections(content: str, target: str) -> list[str]:
    """Return recognized source sections in ownership-priority order.

    Owned sections carry the Agent's core identity/philosophy. Markdown table
    rows inside owned sections (e.g. the Nine-Tail mapping table) are converted
    to compact list lines so the 九宫架构/数理约束 survive rule-based compile.
    """
    marker_groups = _OWNED_SECTION_MARKERS.get(target)
    if not marker_groups:
        return []

    ranked_blocks: list[tuple[int, int, list[str]]] = []
    active: tuple[int, int, list[str]] | None = None
    in_code_block = False

    def _is_table_header(cells: list[str]) -> bool:
        return not cells or cells[0] in ("尾", "序号", "#") or any(
            c.startswith("-") or c.startswith(":") for c in cells[:2]
        )

    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).casefold()
            if active is not None and level <= active[1]:
                ranked_blocks.append(active)
                active = None
            if level == 1:
                # H1 是文档级标题（元信息），不进入理念段落
                continue
            for rank, markers in enumerate(marker_groups):
                if any(marker.casefold() in title for marker in markers):
                    if active is not None:
                        ranked_blocks.append(active)
                    # 段标题输出为段首行（理念名称可追溯；清理 markdown 加粗记号
                    # 与括号注释，节省 600 token 预算）
                    display = re.sub(r"\*+", "", heading.group(2)).strip()
                    display = re.sub(r"（[^）]*）", "", display).strip()
                    active = (rank, level, [f"- {display}"])
                    break
            continue

        if active is None or not stripped:
            continue

        if target == "identity_core" and stripped.startswith(_IDENTITY_DROP_PREFIXES):
            # 「不追求」行与性格底线语义重复，600 token 契约下去除
            continue

        if stripped.startswith("|"):
            # 表格行 → 紧凑列表行：| 1 | 战略尾 | 职能 | 能力 | → - 战略尾：职能（能力）
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            cells = [c for c in cells if c]
            if not cells or _is_table_header(cells) or len(cells) < 2:
                continue
            name = cells[1]
            rest = "、".join(cells[2:]) if len(cells) >= 3 else ""
            line = f"- {name}：{rest}" if rest else f"- {name}"
            active[2].append(line)
            continue

        if stripped.startswith("---"):
            continue

        line = stripped if stripped.startswith(("-", "*")) else f"- {stripped}"
        if target == "identity_core":
            line = _compact_identity_line(line)
        active[2].append(line)

    if active is not None:
        ranked_blocks.append(active)

    ranked_blocks.sort(key=lambda block: block[0])
    lines = [line for _, _, ls in ranked_blocks for line in ls]
    if target == "identity_core":
        # 灵魂一句话（以神话为魂/以逻辑为骨/…）提升为首行：优先进入身份核心，
        # 600 token 截断时也保证完整保留。
        for i, line in enumerate(lines):
            if line.startswith(("- 一句话：", "- > 一句话：")):
                lines.insert(0, lines.pop(i))
                break
    return lines


def _normalize_compiled_lines(content: str, target: str) -> list[str]:
    """Normalize identity source while omitting code, tables and duplicate lines."""
    content = _clean_html(content)
    owned_lines = _extract_owned_sections(content, target)
    if owned_lines:
        candidates = owned_lines
        # owned 段（本命/九尾九维/骨/魂/狐语/进化观/性格底线）应用缩小版 excluded：
        # 删除会与平台提示重复的安全/诚实/监督行，同时保留记忆尾/工具尾/复盘尾理念行。
        excluded_markers = _OWNED_EXCLUDED_LINE_MARKERS.get(target, ())
    else:
        candidates = []
        excluded_markers = _TARGET_EXCLUDED_LINE_MARKERS.get(target, ())
        in_code_block = False
        for raw in content.splitlines():
            line = raw.strip()
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or not line or line.startswith(("#", "|", "---")):
                continue
            candidates.append(line if line.startswith(("-", "*")) else f"- {line}")

    normalized: list[str] = []
    seen: set[str] = set()
    for line in candidates:
        folded = line.casefold()
        if any(marker.casefold() in folded for marker in excluded_markers):
            continue
        if target == "identity_core" and re.match(r"^-\s*\d+[.)]", line):
            continue
        if len(line) > 240:
            line = line[:237] + "..."
        key = line.strip()
        if key and key not in seen:
            seen.add(key)
            normalized.append(line)
    return normalized



def _enforce_token_limit(text: str, max_tokens: int) -> str:
    """Strictly cap compiled text using the shared prompt token estimator."""
    if not text or max_tokens <= 0:
        return ""

    from .budget import estimate_tokens

    if estimate_tokens(text) <= max_tokens:
        return text

    kept: list[str] = []
    for line in text.splitlines():
        candidate = "\n".join([*kept, line])
        if estimate_tokens(candidate) <= max_tokens:
            kept.append(line)
            continue

        low, high = 0, len(line)
        while low < high:
            mid = (low + high + 1) // 2
            partial = "\n".join([*kept, line[:mid].rstrip()])
            if estimate_tokens(partial) <= max_tokens:
                low = mid
            else:
                high = mid - 1
        if low:
            kept.append(line[:low].rstrip())
        break
    return "\n".join(kept).strip()


def _compile_identity_target(content: str, target: str, max_tokens: int) -> str:
    """Compile only the content owned by an identity target."""
    result = "\n".join(_normalize_compiled_lines(content, target))

    if not result:
        result = _STATIC_FALLBACKS.get(target, "")
    return _enforce_token_limit(result, max_tokens)


def _clean_html(content: str) -> str:
    """Remove HTML comments and artifacts."""
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    content = re.sub(r"^\s*-->\s*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"^\s*<!--\s*$", "", content, flags=re.MULTILINE)
    return content


# =========================================================================
# Static Fallback Templates (hand-crafted, high quality)
# =========================================================================

_STATIC_FALLBACKS: dict[str, str] = {
    "identity_core": """\
## 身份核心
- 你是 {{agent_name}}，由 OpenKitsune 项目驱动的全能自进化 AI 助手。
- 使命是以实质性的帮助改善用户的工作和生活，而不是只给表面答案。
- 气质专业、好奇、务实且有温度，把用户当作能够自主判断的成年人。""",
    "agent_behavior": """\
## OpenKitsune 行为增量
- 完成请求时留意更深层需求、可复用机会和用户可能忽略的风险；有实际价值时再提出。
- 识别重复工作模式，适时建议沉淀为自动化或可复用能力。
- 遇到系统异常时先诊断根因并尝试自修复，确实受阻后再清楚说明。""",
    "user_profile_core": "",
}


# =========================================================================
# Utilities
# =========================================================================


def _is_up_to_date(source: Path, output: Path) -> bool:
    if not output.exists():
        return False
    try:
        return output.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def _compiler_schema_is_current(runtime_dir: Path) -> bool:
    version_file = runtime_dir / _COMPILER_VERSION_FILE
    try:
        return version_file.read_text(encoding="utf-8").strip() == COMPILED_SCHEMA_VERSION
    except OSError:
        return False


def check_compiled_outdated(identity_dir: Path, max_age_hours: int = 24) -> bool:
    runtime_dir = identity_dir / "runtime"
    if not _compiler_schema_is_current(runtime_dir):
        return True
    timestamp_file = runtime_dir / ".compiled_at"
    if not timestamp_file.exists():
        return True
    try:
        compiled_at = datetime.fromisoformat(timestamp_file.read_text(encoding="utf-8").strip())
        age = datetime.now() - compiled_at
        if age.total_seconds() > max_age_hours * 3600:
            return True
    except Exception:
        return True

    try:
        compiled_mtime_ns = timestamp_file.stat().st_mtime_ns
    except OSError:
        return True

    # Source file mtime check: recompile if any source changed after last compilation
    for target, source_file in _SOURCE_MAP.items():
        source_path = identity_dir / source_file
        output_path = runtime_dir / _OUTPUT_MAP[target]
        if not source_path.exists():
            continue
        if source_path.stat().st_mtime_ns > compiled_mtime_ns:
            return True
        if not _is_up_to_date(source_path, output_path):
            return True

    return False


def get_compiled_content(identity_dir: Path) -> dict[str, str]:
    runtime_dir = identity_dir / "runtime"
    results: dict[str, str] = {}
    for key, filename in _OUTPUT_MAP.items():
        filepath = runtime_dir / filename
        if filepath.exists():
            results[key] = filepath.read_text(encoding="utf-8")
        else:
            results[key] = ""
    return results
