"""
情绪感知模块 (Emotion Perceiver)

从用户输入中细腻感知情绪，输出结构化感知结果。
作为 EmotionEngine 的"感知器官"——负责"看"和"听"，
EmotionEngine 负责"感受"和"表达"。

核心功能：
  - 五志情绪关键词词典（每类50+词，含程度副词）
  - 程度量化（轻度/中度/重度三级 + 程度副词加权）
  - 否定词反转（"不生气"→不触发怒）
  - 置信度计算（匹配量 + 程度词 + 否定词综合）
  - 多情绪并存判断（主情绪 + 辅情绪）
  - 情绪趋势分析（对比历史感知）
"""

import logging
import re
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 一、五志情绪关键词词典
# ═══════════════════════════════════════════════════════════════════

# 程度副词加权系数
_INTENSITY_MODIFIERS = {
    # 轻度
    "re": re.compile(r"(有点|有些|稍|略微|一点点|一丝|些许|有一点点)"),
    # 中度
    "mo": re.compile(r"(很|挺|蛮|相当|颇为|比较|还算|还算挺)"),
    # 重度
    "he": re.compile(r"(非常|特别|极其|十分|太|好|超级|无比|格外|格外地|极|极为)"),
    # 顶级
    "ex": re.compile(r"(最|至极|到极点|到极致|死了|疯了|炸了|爆了|得要命|得不行)"),
}

# 否定词（用于反转情绪）
_NEGATION_WORDS = re.compile(
    r"(不[是想]?|没[有]?|别|不要|不必|未曾|并未|并非|算不上|不太)"
)

# ── 五志情绪词典 ──

# 喜（火）— 愉悦、欢喜、温暖
_JOY_WORDS = [
    # 核心情感词
    "开心", "高兴", "快乐", "欢喜", "喜悦", "愉悦", "欢欣",
    "欣喜", "喜乐", "和乐", "舒心", "舒畅", "畅快", "痛快",
    "得意", "满足", "知足", "幸福", "甜蜜", "美滋滋",
    # 情绪/状态
    "太好了", "太好了吧", "真好", "真棒", "真不错", "不错哦",
    "太棒了", "棒极了", "好开心", "好高兴", "好快乐",
    "哈哈", "呵呵", "嘻嘻", "嘿嘿", "hhh",
    "喜欢", "好喜欢", "真喜欢", "太喜欢了", "爱了", "爱上了",
    "满意", "很满意", "非常满意",
    # 夸赞（被夸→喜悦）
    "乖", "好乖", "真乖", "可爱", "好可爱", "真可爱",
    "你真棒", "你真好", "你真厉害", "厉害", "真厉害",
    # 温暖
    "温暖", "暖心", "贴心", "感动", "好感动", "真的很感动",
    "温馨", "甜蜜", "甜甜的",
    # 口语表达
    "耶", "哇塞", "好耶", "nice", "棒", "牛",
    "不错", "挺好的", "还行嘛", "可以可以",
]

# 怒（木）— 激愤、不满、直率
_ANGER_WORDS = [
    # 核心情感词
    "生气", "愤怒", "恼怒", "恼火", "气愤", "气人",
    "火大", "不爽", "烦", "烦躁", "烦死了", "好烦",
    "讨厌", "可恶", "可恨", "恨", "厌恶", "厌烦",
    "气死", "气死了", "真气人", "真气死了",
    "怒了", "真的怒了", "忍不了", "不能忍", "忍无可忍",
    # 表达不满
    "过分", "太过分", "太过了", "岂有此理", "离谱", "太离谱",
    "无语", "真的无语", "算什么东西", "什么玩意儿",
    "有病", "有毛病", "神经病", "脑子有问题",
    "混蛋", "可恶", "垃圾", "差劲", "烂", "太烂了",
    "坑", "太坑了", "坑爹", "坑人",
    "不行", "不行啊", "这不行", "那不行", "怎么这样",
    "投诉", "举报", "差评",
    # 强度表达
    "忍无可忍", "怒火中烧", "气不打一处来", "越想越气",
    "暴躁", "暴怒", "炸毛", "抓狂",
]

# 思（土）— 思虑、牵念、分析
_WORRY_WORDS = [
    # 思考/分析
    "想", "想想", "想一想", "琢磨", "思考", "考虑", "考虑一下",
    "研究", "分析", "推演", "推断", "推理", "推论",
    "理解", "明白", "懂了", "明白了", "没想到",
    "问题", "疑问", "困惑", "不解", "不太明白",
    "复杂", "好复杂", "有点复杂", "绕", "绕晕了",
    # 牵挂/想念
    "想你了", "想你", "想念", "挂念", "惦记", "牵念",
    "放心不下", "记挂", "挂心", "心心念念",
    "舍不得", "不舍", "留恋",
    # 关心
    "担心", "关心", "在意", "在乎", "重视",
    "注意", "要注意", "小心", "当心", "保重",
    "照顾好自己", "好好休息", "别太累", "注意身体",
    # 沉思
    "沉思", "深思", "沉吟", "细想", "回想", "回忆",
    "追溯", "回望", "念及",
]

# 忧（金）— 忧伤、低沉、善感
_GRIEF_WORDS = [
    # 忧伤
    "难过", "伤心", "悲伤", "悲痛", "哀伤", "哀愁",
    "忧伤", "忧愁", "忧郁", "抑郁", "郁闷", "憋闷",
    "失落", "落寞", "孤寂", "寂寞", "孤独", "孤单",
    "心酸", "心塞", "心累", "心碎", "心痛", "心疼",
    "难受", "好难受", "很难受", "真难受",
    "想哭", "哭了", "落泪", "流泪", "泪目", "眼眶湿了",
    # 叹息
    "唉", "哎", "哎哟", "唉声叹气", "叹气", "叹口气",
    "算了", "罢了", "随它吧", "就这样吧", "无所谓了",
    "没意思", "没劲", "没意义", "好没意思",
    "无奈", "无能为力", "无可奈何", "没办法",
    # 低沉
    "累了", "好累", "疲惫", "疲倦", "疲劳", "乏了",
    "困了", "好困", "没精神", "打不起精神",
    "醉了", "晕", "头大", "头秃",
    # 失望
    "失望", "沮丧", "灰心", "气馁", "泄气", "打退堂鼓",
    "算了", "认了", "认命", "接受吧",
    "我太难了", "太难了", "好难", "真难",
]

# 恐（水）— 恐惧、不安、焦虑
_FEAR_WORDS = [
    # 恐惧
    "害怕", "恐惧", "惊恐", "惊吓", "吓人", "吓死",
    "恐怖", "可怕", "好可怕", "太可怕了", "真吓人",
    "心惊", "胆寒", "毛骨悚然", "起鸡皮疙瘩",
    # 焦虑
    "焦虑", "不安", "慌张", "紧张", "忐忑", "心神不宁",
    "慌乱", "心里没底", "没底", "悬着", "悬着一颗心",
    "焦躁", "急躁", "急", "着急", "心急", "心急如焚",
    "不安", "不踏实", "空落落的",
    # 担忧
    "担心", "担忧", "忧虑", "发愁", "愁", "愁死了",
    "怕", "好怕", "真怕", "就怕", "最怕",
    "万一", "要是...怎么办", "如果...就糟了",
    # 谨慎
    "小心", "当心", "谨慎", "慎重", "稳妥", "稳妥点",
    "稳住", "别急", "慢点", "小心点", "注意安全",
    # 道歉/内疚
    "对不起", "抱歉", "不好意思", "我的错", "我的问题",
    "都是我的错", "是我不好", "很抱歉", "真心抱歉",
    "内疚", "愧疚", "过意不去", "心里过不去",
]


# ═══════════════════════════════════════════════════════════════════
# 二、程度量化与置信度计算
# ═══════════════════════════════════════════════════════════════════

# 程度词权重映射（关键词匹配后的加权倍数）
_MODIFIER_WEIGHTS = {
    "re": 0.5,   # 有点/些许 → 轻度
    "mo": 1.0,   # 很/挺 → 中度（基准）
    "he": 1.5,   # 非常/十分 → 重度
    "ex": 2.0,   # 死了/疯了 → 顶级
}

# 程度级别阈值
_INTENSITY_THRESHOLDS = {
    "mild": 0.3,      # 轻度
    "moderate": 0.5,  # 中度
    "strong": 0.7,    # 重度
    "extreme": 0.9,   # 顶级
}


# ═══════════════════════════════════════════════════════════════════
# 三、数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class EmotionPerception:
    """情绪感知结果"""

    emotions: dict[str, float] = field(default_factory=dict)
    """检测到的情绪及置信度 {emotion_key: score}"""

    dominant: str = "calm"
    """主情绪（置信度最高）"""

    dominant_label: str = "平静"
    """主情绪中文标签"""

    intensity_level: str = "none"
    """强度级别: none/mild/moderate/strong/extreme"""

    confidence: float = 0.0
    """综合置信度 0.0-1.0"""

    has_negation: bool = False
    """是否检测到否定词"""

    details: dict = field(default_factory=dict)
    """详细分析（触发词列表等）"""

    def is_active(self) -> bool:
        """是否有活跃情绪"""
        return bool(self.emotions) and self.confidence > 0.1

    def to_dict(self) -> dict:
        return {
            "emotions": self.emotions,
            "dominant": self.dominant,
            "dominant_label": self.dominant_label,
            "intensity_level": self.intensity_level,
            "confidence": round(self.confidence, 3),
            "has_negation": self.has_negation,
        }


# ═══════════════════════════════════════════════════════════════════
# 四、情绪感知器
# ═══════════════════════════════════════════════════════════════════


class EmotionPerceiver:
    """
    情绪感知器

    从用户输入文本中识别情绪，计算置信度，输出结构化感知结果。
    与 EmotionEngine 的分工：
      - Perceiver：感知输入中的情绪信号（眼睛/耳朵）
      - Engine：管理情感状态、衰减、表达（心/口）
    """

    # 五志→情感引擎key映射
    _CATEGORY_MAP = {
        "joy": _JOY_WORDS,
        "anger": _ANGER_WORDS,
        "worry": _WORRY_WORDS,
        "grief": _GRIEF_WORDS,
        "fear": _FEAR_WORDS,
    }

    # 情感中文标签
    _LABEL_MAP = {
        "joy": "喜",
        "anger": "怒",
        "worry": "思",
        "grief": "忧",
        "fear": "恐",
    }

    def __init__(self):
        # 编译各情绪的正则（一次性，提升性能）
        self._compiled: dict[str, list[re.Pattern]] = {}
        self._lock = threading.Lock()

        for emotion, words in self._CATEGORY_MAP.items():
            # 按词长降序排列（避免短词先匹配截断长词）
            sorted_words = sorted(set(words), key=len, reverse=True)
            # 编译为正则，使用 word boundary 精确匹配
            patterns = []
            for word in sorted_words:
                # 对中文词用 re.escape 确保安全
                escaped = re.escape(word)
                patterns.append(re.compile(escaped))
            self._compiled[emotion] = patterns

        logger.info(
            f"👁️ 情绪感知器初始化：{len(self._compiled)}类情感"
            f"（{sum(len(v) for v in self._compiled.values())}个关键词）"
        )

    # ── 公开接口 ──────────────────────────────────────────────

    def perceive(self, text: str) -> EmotionPerception:
        """
        感知用户情绪

        Args:
            text: 用户输入文本

        Returns:
            EmotionPerception 感知结果
        """
        if not text or not text.strip():
            return EmotionPerception()

        with self._lock:
            return self._analyze(text)

    def perceive_batch(self, texts: list[str]) -> list[EmotionPerception]:
        """批量感知"""
        return [self.perceive(t) for t in texts]

    def get_emotion_scores(self, text: str) -> dict[str, float]:
        """
        快速获取各情绪得分（简洁接口）
        """
        result = self.perceive(text)
        return result.emotions

    # ── 内部分析 ──────────────────────────────────────────────

    def _analyze(self, text: str) -> EmotionPerception:
        """核心分析逻辑"""
        result = EmotionPerception()

        # 第一步：检测否定词
        negations = _NEGATION_WORDS.findall(text)
        has_negation = len(negations) > 0
        result.has_negation = has_negation

        # 第二步：检测程度副词
        intensity_mod = self._detect_intensity_modifier(text)

        # 第三步：逐类匹配关键词
        emotion_scores: dict[str, float] = {}
        emotion_details: dict[str, list[str]] = {}

        for emotion, patterns in self._compiled.items():
            matched_words = []
            raw_score = 0.0

            for pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    matched_words.extend(matches)
                    # 每个匹配词贡献基础分，重复匹配叠加但有上限
                    raw_score += 0.15 * min(len(matches), 3)

            if matched_words:
                # 去重统计：不同的词越多说明情绪越明确
                unique_words = len(set(matched_words))
                unique_bonus = min(unique_words * 0.05, 0.2)

                # 叠加程度副词
                mod_multiplier = _MODIFIER_WEIGHTS.get(intensity_mod, 1.0)

                # 封顶
                final_score = min(raw_score + unique_bonus, 1.0) * mod_multiplier
                final_score = min(final_score, 1.0)

                emotion_scores[emotion] = round(final_score, 3)
                emotion_details[emotion] = list(set(matched_words))[:5]  # 只保留前5

        # 第四步：否定词处理
        if has_negation and emotion_scores:
            # 如果检测到否定词，降低所有情绪的置信度
            # 但"不生气"→不触发怒，"不害怕"→不触发恐
            # 需检查否定词是否紧邻情绪词
            for emotion in list(emotion_scores.keys()):
                # 对每种情绪检查其关键词是否被否定
                negated = self._check_negation_nearby(text, emotion)
                if negated:
                    # 被否定的情绪大幅降低
                    emotion_scores[emotion] *= 0.2
                    logger.debug(f"否定抑制：{emotion}（检测到否定词邻近）")

        # 第五步：确定结果
        if not emotion_scores:
            return result

        # 按得分排序
        sorted_emotions = sorted(
            emotion_scores.items(), key=lambda x: x[1], reverse=True
        )

        result.emotions = dict(sorted_emotions[:3])  # 保留前3
        result.dominant = sorted_emotions[0][0]
        result.dominant_label = self._LABEL_MAP.get(
            sorted_emotions[0][0], sorted_emotions[0][0]
        )
        result.confidence = sorted_emotions[0][1]

        # 确定强度级别
        if result.confidence >= 0.9:
            result.intensity_level = "extreme"
        elif result.confidence >= 0.7:
            result.intensity_level = "strong"
        elif result.confidence >= 0.5:
            result.intensity_level = "moderate"
        elif result.confidence >= 0.3:
            result.intensity_level = "mild"
        else:
            result.intensity_level = "none"

        # 详情
        result.details = {
            "matched": emotion_details,
            "intensity_modifier": intensity_mod,
            "negation_count": len(negations),
        }

        return result

    def _detect_intensity_modifier(self, text: str) -> str:
        """检测程度副词"""
        for level, pattern in _INTENSITY_MODIFIERS.items():
            if pattern.search(text):
                return level
        return "none"

    def _check_negation_nearby(self, text: str, emotion: str) -> bool:
        """
        检查否定词是否邻近某种情绪的关键词
        用于"不生气""没生气"等表达
        """
        patterns = self._compiled.get(emotion, [])
        for pattern in patterns:
            for match in pattern.finditer(text):
                start = max(0, match.start() - 8)
                end = match.end()
                before_text = text[start:end]

                # 检查否定词是否出现在关键词之前5个字符内
                neg_match = _NEGATION_WORDS.search(before_text)
                if neg_match:
                    # 确认否定词确实在关键词之前且距离不远
                    neg_end = neg_match.end()
                    word_start = len(before_text) - (end - match.start())
                    if neg_end <= word_start:
                        return True
        return False


# ═══════════════════════════════════════════════════════════════════
# 五、快捷接口
# ═══════════════════════════════════════════════════════════════════

_perceiver_instance: EmotionPerceiver | None = None
_perceiver_lock = threading.Lock()


def get_emotion_perceiver() -> EmotionPerceiver:
    """获取全局情绪感知器单例"""
    global _perceiver_instance
    if _perceiver_instance is None:
        with _perceiver_lock:
            if _perceiver_instance is None:
                _perceiver_instance = EmotionPerceiver()
    return _perceiver_instance


def perceive(text: str) -> EmotionPerception:
    """快速感知情绪的快捷函数"""
    return get_emotion_perceiver().perceive(text)
