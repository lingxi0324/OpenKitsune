"""称呼归一化 —— 记忆数据保存时自动把「用户」→ 配置的用户称呼、「模型/AI/助手」→ 配置的 AI 称呼。

配置驱动（禁止硬编码称呼）：
- 名字只来自 ``openkitsune.config.Settings`` 的 ``user_address_terms`` /
  ``assistant_address_terms`` / ``name_normalize_enabled``；
- 配置不可用或开关关闭时保持原文不动（fail-open，不静默改名）。

技术语境保护（避免把「多用户」「模型 Qwen3.6」「用户界面」这类技术表述误替换）：
- 「用户」排除多租户前缀（多/跨/单/每/各/该/某）与系统名词（界面/画像/配置…）；
- 「模型」仅在指代 AI 本人（后接人称动词/人称名词）时替换；模型名与技术名词一律保留；
- 「AI」「助手」同样只在指代 AI 本人时替换。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

try:
    from ..config import settings as _settings

    _CONFIG_OK = True
except Exception as _exc:  # pragma: no cover - 配置不可用时降级不替换
    _settings = None
    _CONFIG_OK = False
    logger.warning("[name_normalize] 配置不可用，称呼归一化已停用: %s", _exc)


# ---------------------------------------------------------------------------
# 配置访问（名称一律来自 Settings，禁止在本模块内写死称呼）
# ---------------------------------------------------------------------------


def enabled() -> bool:
    """归一化是否启用。配置缺失默认关闭，绝不带硬编码称呼兜底。"""
    if not _CONFIG_OK:
        return False
    try:
        return bool(getattr(_settings, "name_normalize_enabled", False))
    except Exception:
        return False


def user_display_name() -> str:
    """配置的用户称呼（首个），配置缺失返回空串。"""
    if not _CONFIG_OK:
        return ""
    terms = getattr(_settings, "user_address_terms", None)
    return str(terms[0]).strip() if terms else ""


def assistant_display_name() -> str:
    """配置的 AI 称呼（首个），配置缺失返回空串。"""
    if not _CONFIG_OK:
        return ""
    terms = getattr(_settings, "assistant_address_terms", None)
    return str(terms[0]).strip() if terms else ""


def _user_labels() -> set[str]:
    """「关于用户」的 subject 合法取值：历史内部标签 + 配置的全部用户称呼。"""
    labels = {"用户", "user", "当前用户", "我"}
    if _CONFIG_OK:
        for t in getattr(_settings, "user_address_terms", ()) or ():
            s = str(t).strip().lower()
            if s:
                labels.add(s)
    return labels


def is_user_subject(subject: str | None) -> bool:
    """判断 subject 是否指向用户（兼容配置称呼与历史内部标签）。"""
    if not subject:
        return False
    return subject.strip().lower() in _user_labels()


def user_subject_query_values() -> tuple[str, ...]:
    """查询「关于用户」的记忆时应使用的 subject 取值（含历史遗留值）。"""
    vals: list[str] = ["用户", "user", "当前用户", "我"]
    for t in getattr(_settings, "user_address_terms", ()) or ():
        s = str(t).strip()
        if s and s not in vals:
            vals.append(s)
    return tuple(vals)


# ---------------------------------------------------------------------------
# 文本替换规则（规则在代码里，称呼在配置里）
# ---------------------------------------------------------------------------

# 「用户」：排除多租户/量化/泛指前缀（多用户/跨用户/单用户/普通用户/目标用户/非技术用户…）
# 注意：这是「保护型」正则（配合 _protect 占位符使用），不能只做 replace-self 的假保护。
_USER_EXCLUDE_PREFIX = re.compile(
    r"(?:[多跨单每各该某]|非技术|普通|所有|全体|广大|目标|终端|最终|内部|外部|"
    r"企业|个人|移动|桌面|网络|线上|线下|数字|潜在|各类|技术|广大)用户"
)

# 「用户」后接系统技术名词 → 保留（用户界面/用户画像/用户配置/用户数…）
_USER_TECH_FOLLOW = re.compile(
    r"用户(?=(?:界面|画像|配置|数据|目录|权限|角色|账号|标识|ID|态|端|"
    r"设备|会话|文档|协议|接口|服务|系统|产品|平台|行为|属性|字段|输入|输出|"
    r"注册|登录|场景|旅程|群体|规模|数|量|维度|画像|满意度|留存|增长|运营|"
    r"分层|分群|标签|指标|模型|画像库))"
)

# 「模型」：后接模型名或技术名词 → 保留（模型 Qwen3.6、模型路径、模型训练…）
_MODEL_TECH_FOLLOW = re.compile(
    r"模型(?=\s*(?:[A-Za-z0-9_.·/\-]|(?:路径|文件|服务|名|配置|参数|权重|版本|大小|"
    r"训练|微调|量化|蒸馏|嵌入|推理|运行|部署|加载|调用|接口|向量|语言|大语言|"
    r"识别|检测|分类|预测|推荐|搜索|对话|视觉|音频|语音|生成|理解|端侧|云端|本地|"
    r"远程|开源|闭源|商用|架构|层数|评测|基准|优化|加速|转换|导出|导入|管理|治理|"
    r"安全|合规|评估|能力|规模|数据|上下文|长度|数量|收敛|损失|精度|效率|延迟|"
    r"吞吐|并发|显存|内存|磁盘|多卡|双卡|单卡|加速卡|引擎|框架|权重|字节|参数|"
    r"量|剪枝|蒸馏|对齐|强化|监督|无监督|自监督|预训练|后训练|微调)))"
)

# 「模型」前接技术前缀 → 保留（大语言模型/基座模型/推理模型/视觉模型…）
_MODEL_TECH_PRE = re.compile(
    r"(?:大语言|语言|基座|基础|底座|主干|骨干|预训练|后训练|强化学习|多模态|"
    r"单模态|全模态|跨模态|视觉|语音|音频|识别|检测|分类|生成|理解|对话|搜索|"
    r"推荐|预测|决策|规划|翻译|摘要|代码|绘画|视频|图片|数学|通用|专用|对齐|"
    r"微调|训练|推理|端侧|云端|本地|远程|开源|闭源|商用|稀疏|密集|MoE|Agent|"
    r"智能体|多智能体|向量|检索|RAG|大模型|大|超大|轻量|重型|基础|底座)\s*模型"
)

# 「模型」指代 AI 本人：后接人称动词/人称名词 → 替换
_MODEL_PERSON_FOLLOW = re.compile(
    r"模型(?=\s*(?:认为|建议|回答|回复|说|判断|觉得|应该|需要|可以|会|知道|记得|"
    r"希望|要求|告诉|给出|选择|推荐|帮助|陪伴|称呼|名字|身份|自身|本身|自己|"
    r"对话|聊天|扮演|角色|输出|生成|解释|演示|展示|引导|提醒|安抚|鼓励|支持|"
    r"提供|负责|擅长|喜欢|愿意|正在|已经|没有|不会|不该|不能))"
)

# 「AI」：后接技术名词 → 保留（AI 模型/AI 工具/AI 服务…，容忍空格）
_AI_TECH_FOLLOW = re.compile(
    r"AI(?=\s*(?:模型|工具|服务|能力|产品|平台|应用|系统|技术|时代|浪潮|公司|企业|"
    r"领域|行业|绘画|生成|对话|编程|项目|工程|芯片|算力|发展|监管|安全|助手|"
    r"工程师|研究员|研发|框架|生态|社区|论文|研究|评测|基准|智能体|Agent|agent|"
    r"音乐|视频|音频|图片|文案|知识|法律|医疗|健康|教育|金融|营销|运营|内容|"
    r"设计|开发|部署|运维|测试|转型|赋能|革命|变革|创新|创业|风险|伦理|治理|"
    r"政策|标准|规范|应用|落地|场景|算法|数据|大模型|团队|协作|协同|值班|轮班|"
    r"监督|聊天|意识|自主|自我|智能|对齐|安全))"
)

# 「助手」：前接修饰词 → 保留（AI 助手/智能助手/语音助手/私人助手…，容忍空格）
_ASSISTANT_TECH_PRE = re.compile(
    r"(?:AI|智能|语音|数字|虚拟|办公|生活|私人|个人|医疗|健康|客服|教学|编程|"
    r"科研|研究|学术|电商|营销|运营|内容|设计|法律|财务|招聘|旅行|健身|饮食|"
    r"育儿|教育|娱乐|工具|机器人|数字人|全能|通用|专属|贴心|家庭|企业|商业|"
    r"政务|法律|金融|编程|写作|翻译|绘画|音乐)\s*助手"
)


def _protect(text: str, pattern: re.Pattern[str], tag: str = "P") -> tuple[str, dict[str, str]]:
    """用带标签的占位符保护匹配片段，返回 (保护后的文本, 占位符表)。

    tag 必须按调用点唯一（1/2/3/4/5…），否则多次保护都以 N0 起编号，
    restore 时不同规则的占位符会互相覆盖（曾导致长文里凭空插入「检测」）。
    标签只能用数字/不可见字符，禁止使用会被后续规则再次匹配的字母组合
    （如 "AI" 会被 AI 规则二次替换导致占位符无法还原）。
    """
    placeholders: dict[str, str] = {}

    def _sub(m: re.Match[str]) -> str:
        ph = f"\x00{tag}{len(placeholders)}\x00"
        placeholders[ph] = m.group(0)
        return ph

    return pattern.sub(_sub, text), placeholders


def _restore(text: str, placeholders: dict[str, str]) -> str:
    for ph, raw in placeholders.items():
        text = text.replace(ph, raw)
    return text


def _replace_user(text: str, name: str) -> str:
    """「当前用户/用户」→ 用户称呼（保护技术语境）。"""
    if not name:
        return text
    text = re.sub(r"当前用户", name, text)

    text, ph = _protect(text, _USER_TECH_FOLLOW, "1")
    text, phx = _protect(text, _USER_EXCLUDE_PREFIX, "6")  # 泛指前缀整段保护
    text = re.sub(r"(?<![多跨单每各该某])用户", name, text)
    text = _restore(text, phx)
    return _restore(text, ph)


def _replace_assistant(text: str, name: str) -> str:
    """「模型/AI/助手」→ AI 称呼（仅当指代 AI 本人；技术语境保留）。

    顺序：先「助手」（带修饰词的整段保护，避免与 AI 规则叠加双替换），
    再「AI」，最后「模型」。
    """
    if not name:
        return text

    # 1) 助手：带修饰词（AI 助手/智能助手…）整段保护，其余替换
    text, ph4 = _protect(text, _ASSISTANT_TECH_PRE, "2")
    text = re.sub(r"(?<![\u4e00-\u9fffA-Za-z])助手", name, text)
    text = _restore(text, ph4)

    # 2) AI：保护技术语境，其余替换
    text, ph3 = _protect(text, _AI_TECH_FOLLOW, "3")
    text = re.sub(r"(?<![\u4e00-\u9fffA-Za-z])AI(?![A-Za-z])", name, text)
    text = _restore(text, ph3)

    # 3) 模型：保护技术语境，再按人称动词替换
    text, ph1 = _protect(text, _MODEL_TECH_FOLLOW, "4")
    text, ph2 = _protect(text, _MODEL_TECH_PRE, "5")
    text = _MODEL_PERSON_FOLLOW.sub(lambda m: name + m.group(0)[len("模型"):], text)
    text = _restore(text, ph2)
    text = _restore(text, ph1)

    return text


def normalize_names(text: str) -> str:
    """把 text 中指向用户/AI 的通用称呼替换为配置称呼；未启用则原样返回。"""
    if not text or not enabled():
        return text
    out = _replace_user(text, user_display_name())
    out = _replace_assistant(out, assistant_display_name())
    return out


def normalize_memory(memory: object) -> bool:
    """就地归一化 SemanticMemory 的文本字段（content/subject/entity/predicate），返回是否有改动。"""
    if not enabled():
        return False
    changed = False
    for field in ("content", "subject", "entity", "predicate"):
        raw = getattr(memory, field, None)
        if isinstance(raw, str) and raw:
            norm = normalize_names(raw)
            if norm != raw:
                setattr(memory, field, norm)
                changed = True
    return changed
