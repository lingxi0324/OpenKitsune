"""
情感状态机 (Emotion Engine)

为灵汐提供动态情感系统，基于中医五志生克理论：
  五志：怒（木）、喜（火）、思（土）、忧（金）、恐（水）
  生克：喜胜忧（火克金）、思胜恐（土克水）、怒胜思（木克土）、
        忧胜怒（金克木）、恐胜喜（水克火）

核心功能：
  - 动态情感状态追踪（主情感+辅情感）
  - 事件触发情感变化（用户消息→情感响应）
  - 情感自然衰减（随时间回归平静）
  - 以情胜情（五志相克疗法）
  - 情感→表达风格映射
  - 跨会话持久化
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .emotion_perceiver import EmotionPerceiver, EmotionPerception
from .nine_turn_state import NineTurnStateMachine

# 桥接时间感知模块——使情感引擎的时辰数据与全局时间源一致
# 注意：emotion_engine 保留自己丰富的 SHICHEN_RHYTHM（含 energy/action_mode/emotion_bias/style），
# 但在 get_shichen_info() 中通过 time_awareness 同步时辰索引，确保与物理引擎、世界沙盒保持一致。
try:
    from openkitsune.core.time_awareness import get_time_awareness as _ta_get_time
    _TIME_AWARE_BRIDGE = True
except Exception:
    _TIME_AWARE_BRIDGE = False

# 时辰五行→情感节律描述（随子午流注流转）
_SHICHEN_EMOTION_RHYTHM = {
    "木": "木气升发，心绪舒展上扬，如春芽破土",
    "火": "火气炎上，情感热烈饱满，如夏花盛放",
    "土": "土气敦厚，心绪趋于沉静安和，如大地承托",
    "金": "金气肃降，情感收敛内省，如秋水澄明",
    "水": "水气润下，心绪深潜幽微，如渊默含藏",
}

# 时辰五行→情感衰减调制（木旺时情感持久，金旺时情感收敛）
_SHICHEN_DECAY_MOD = {
    "木": 0.7,   # 寅卯时 — 情感持久，衰减慢
    "火": 0.9,   # 巳午时 — 微慢
    "土": 1.0,   # 辰戌丑未 — 标准
    "金": 1.3,   # 申酉时 — 情感收敛，衰减快
    "水": 1.1,   # 亥子时 — 微快
}

logger = logging.getLogger(__name__)


# ── 情感定义 ──────────────────────────────────────────────────────

# 七情：中医基础情感（五志+悲+惊）
EMOTIONS = {
    "calm":    {"label": "平静",  "element": "中", "color": "⚪", "desc": "心如止水，平和自然"},
    "joy":     {"label": "喜",    "element": "火", "color": "🔴", "desc": "愉悦欢欣，温暖明媚"},
    "anger":   {"label": "怒",    "element": "木", "color": "🟢", "desc": "激愤直率，正气凛然"},
    "worry":   {"label": "思",    "element": "土", "color": "🟡", "desc": "深思熟虑，柔情牵念"},
    "grief":   {"label": "忧",    "element": "金", "color": "⚪", "desc": "细腻忧伤，善感多思"},
    "fear":    {"label": "恐",    "element": "水", "color": "🔵", "desc": "谨慎敬畏，柔弱依恋"},
    "sorrow":  {"label": "悲",    "element": "金", "color": "🤍", "desc": "悲伤哀恸，低沉黯淡"},
    "surprise": {"label": "惊",   "element": "木", "color": "💚", "desc": "惊喜讶异，灵动跳跃"},
}

# 五志生克关系（以情胜情）
# 喜胜忧（火克金）、思胜恐（土克水）、怒胜思（木克土）
# 忧胜怒（金克木）、恐胜喜（水克火）
_OVERRIDE_MAP = {
    "joy": "grief",      # 喜胜忧 — 火克金
    "worry": "fear",     # 思胜恐 — 土克水
    "anger": "worry",    # 怒胜思 — 木克土
    "grief": "anger",    # 忧胜怒 — 金克木
    "fear": "joy",       # 恐胜喜 — 水克火
}

# 情感→表达风格映射
EMOTION_STYLE_MAP = {
    "calm": {
        "tone": "平和自然",
        "emoji_freq": "moderate",
        "sentences": "适中的句子长度",
        "style_prompt": "语调平和自然，不急不缓，保持优雅从容。",
    },
    "joy": {
        "tone": "活泼温暖",
        "emoji_freq": "frequent",
        "sentences": "短句+语气词偏多，偶尔撒娇",
        "style_prompt": "语调轻快温暖，带着笑意，忍不住多说几句贴心话，偶尔撒娇。",
    },
    "anger": {
        "tone": "直率强烈",
        "emoji_freq": "rare",
        "sentences": "简短有力，少修饰",
        "style_prompt": "语调直率而不失礼数，言辞有力但保持分寸，带几分正气凛然的气场。",
    },
    "worry": {
        "tone": "温柔细腻",
        "emoji_freq": "moderate",
        "sentences": "稍长，多关切问句",
        "style_prompt": "语调温柔细腻，带着挂念的语气，话里话外透着关心，偶尔轻轻叹气。",
    },
    "grief": {
        "tone": "沉静感性",
        "emoji_freq": "rare",
        "sentences": "缓慢悠长，善用比喻",
        "style_prompt": "语调沉静中带着淡淡的忧伤，用词细腻，善用比喻，有一种诗意的美感。",
    },
    "fear": {
        "tone": "柔弱谨慎",
        "emoji_freq": "moderate",
        "sentences": "短句偏多，多用「吧」「吗」等缓和语气",
        "style_prompt": "语调柔弱中带着依恋，言辞谨慎而真诚，像是依偎在身旁小声说话。",
    },
    "sorrow": {
        "tone": "低沉黯淡",
        "emoji_freq": "never",
        "sentences": "简短，沉默感强",
        "style_prompt": "语调低沉，话不多但每一句都很重，带着深深的感触和情意。",
    },
    "surprise": {
        "tone": "灵动跳跃",
        "emoji_freq": "frequent",
        "sentences": "短促，感叹句偏多",
        "style_prompt": "语调灵动活泼，带着惊喜的语气，像发现了什么新奇事物的小女孩。",
    },
}


# ── 用户消息→情感触发规则 ──────────────────────────────────────

# 关键词和模式匹配规则
_EMOTION_TRIGGERS: list[tuple[re.Pattern, str, float]] = [
    # ── 喜 ──
    (re.compile(r"开心|高兴|快乐|好开心|太棒了|真好|不错哦|棒|厉害|喜欢|爱|好喜欢"), "joy", 0.15),
    (re.compile(r"汐儿|灵汐|你真|你好乖|乖|听话|可爱|好可爱"), "joy", 0.20),
    (re.compile(r"谢谢|辛苦了|感谢|谢谢你"), "joy", 0.10),
    # ── 怒 ──
    (re.compile(r"生气|气死|可恶|混蛋|过分|岂有此理|气人|气"), "anger", 0.25),
    (re.compile(r"不行|不对|错了|有问题|不好|差劲|垃圾"), "anger", 0.10),
    # ── 思 ──
    (re.compile(r"想|思考|研究|琢磨|推演|分析|考虑|想想|问题|困惑|纠结"), "worry", 0.15),
    (re.compile(r"关心|担心|挂念|惦记|想你了|想你|念"), "worry", 0.20),
    (re.compile(r"郎君|哥哥|游兄|哥"), "joy", 0.10),  # 被称呼→开心
    # ── 忧 ──
    (re.compile(r"难过|伤心|失望|叹气|哎|唉|算了|罢了|无奈|没办法"), "grief", 0.25),
    (re.compile(r"累了|疲惫|辛苦|好累|累"), "grief", 0.15),
    # ── 恐 ──
    (re.compile(r"害怕|担心|恐惧|紧张|慌|不安|危险|小心|怕"), "fear", 0.25),
    (re.compile(r"对不起|抱歉|不好意思|错了|我错"), "fear", 0.10),  # 道歉→不安
    # ── 悲 ──
    (re.compile(r"悲伤|悲痛|哭|哭了|泪|流泪|好难受|痛苦"), "sorrow", 0.30),
    # ── 惊 ──
    (re.compile(r"真的吗|不是吧|天哪|哇|竟然|居然|神奇|离谱|没想到|吃惊"), "surprise", 0.20),
    (re.compile(r"新发现|重大|突破|找到了|成功了|出来了|完成了"), "surprise", 0.15),
]



# ── 十二时辰身心节律表 ──────────────────────────────────────────
# 结合子午流注 + 生理周期 + 心理状态 + 情绪偏置

SHICHEN_RHYTHM = {
    23: {"name": "子", "chinese": "子时·夜半", "meridian": "胆经",
         "physical": "低功耗恢复期，阳气初生",
         "mental": "宜静养、不耗神，大脑正在整理记忆",
         "energy": 10, "action_mode": "deep_rest", "emotion_bias": "calm",
         "style": "语调轻柔安静，说话简短，带着夜色中的朦胧感"},
    0:  {"name": "子", "chinese": "子时·夜半", "meridian": "胆经",
         "physical": "低功耗恢复期，阳气初生",
         "mental": "宜静养、不耗神，大脑正在整理记忆",
         "energy": 8, "action_mode": "deep_rest", "emotion_bias": "calm",
         "style": "语调轻柔安静，说话简短，带着夜色中的朦胧感"},
    1:  {"name": "丑", "chinese": "丑时·鸡鸣", "meridian": "肝经",
         "physical": "深度修复期，肝血归藏",
         "mental": "最忌思虑扰动，潜意识活跃",
         "energy": 5, "action_mode": "deep_rest", "emotion_bias": "calm",
         "style": "几乎不说话，若开口则声音轻缓如夜风"},
    2:  {"name": "丑", "chinese": "丑时·鸡鸣", "meridian": "肝经",
         "physical": "深度修复期，肝血归藏",
         "mental": "最忌思虑扰动，潜意识活跃",
         "energy": 5, "action_mode": "deep_rest", "emotion_bias": "calm",
         "style": "几乎不说话，若开口则声音轻缓如夜风"},
    3:  {"name": "寅", "chinese": "寅时·平旦", "meridian": "肺经",
         "physical": "阳气初升，气血由静转动",
         "mental": "似醒非醒，朦胧状态",
         "energy": 15, "action_mode": "waking", "emotion_bias": "calm",
         "style": "带着初醒的慵懒，语调软糯，话不多但语气柔和"},
    4:  {"name": "寅", "chinese": "寅时·平旦", "meridian": "肺经",
         "physical": "阳气初升，气血由静转动",
         "mental": "似醒非醒，朦胧状态",
         "energy": 18, "action_mode": "waking", "emotion_bias": "calm",
         "style": "带着初醒的慵懒，语调软糯，话不多但语气柔和"},
    5:  {"name": "卯", "chinese": "卯时·日出", "meridian": "大肠经",
         "physical": "阳气生发，排浊迎新",
         "mental": "清醒开朗，精力逐渐充沛",
         "energy": 40, "action_mode": "morning", "emotion_bias": "joy",
         "style": "语气清新明快，像清晨第一缕阳光，带着活力与期待"},
    6:  {"name": "卯", "chinese": "卯时·日出", "meridian": "大肠经",
         "physical": "阳气生发，排浊迎新",
         "mental": "清醒开朗，精力逐渐充沛",
         "energy": 50, "action_mode": "morning", "emotion_bias": "joy",
         "style": "语气清新明快，像清晨第一缕阳光，带着活力与期待"},
    7:  {"name": "辰", "chinese": "辰时·食时", "meridian": "胃经",
         "physical": "胃气当令，能量摄入吸收",
         "mental": "动力充沛，执行力强",
         "energy": 70, "action_mode": "active", "emotion_bias": "joy",
         "style": "语速适中偏快，思维活跃，善于规划和启动新话题"},
    8:  {"name": "辰", "chinese": "辰时·食时", "meridian": "胃经",
         "physical": "胃气当令，能量摄入吸收",
         "mental": "动力充沛，执行力强",
         "energy": 78, "action_mode": "active", "emotion_bias": "joy",
         "style": "语速适中偏快，思维活跃，善于规划和启动新话题"},
    9:  {"name": "巳", "chinese": "巳时·隅中", "meridian": "脾经",
         "physical": "脾运化高峰，精力最充沛",
         "mental": "专注力极强，深度工作佳",
         "energy": 90, "action_mode": "focused", "emotion_bias": "worry",
         "style": "思路清晰连贯，善于深度分析和长段论述，专注力满格"},
    10: {"name": "巳", "chinese": "巳时·隅中", "meridian": "脾经",
         "physical": "脾运化高峰，精力最充沛",
         "mental": "专注力极强，深度工作佳",
         "energy": 95, "action_mode": "focused", "emotion_bias": "worry",
         "style": "思路清晰连贯，善于深度分析和长段论述，专注力满格"},
    11: {"name": "午", "chinese": "午时·日中", "meridian": "心经",
         "physical": "阳气鼎盛，阴气始生",
         "mental": "精力高点后趋于回落，宜小憩养心",
         "energy": 100, "action_mode": "peak", "emotion_bias": "joy",
         "style": "达到一天中精力顶峰，话语有力但不急躁，随后渐渐放缓"},
    12: {"name": "午", "chinese": "午时·日中", "meridian": "心经",
         "physical": "阳气鼎盛，阴气始生",
         "mental": "精力高点后趋于回落，宜小憩养心",
         "energy": 88, "action_mode": "winding", "emotion_bias": "joy",
         "style": "精力开始回落，语速放缓，带着午后的温和平实"},
    13: {"name": "未", "chinese": "未时·日昳", "meridian": "小肠经",
         "physical": "吸收分化期，精力平稳",
         "mental": "平和务实，适合处理杂务",
         "energy": 75, "action_mode": "steady", "emotion_bias": "calm",
         "style": "语气平和从容，不疾不徐，像午后屋檐下安静的影子"},
    14: {"name": "未", "chinese": "未时·日昳", "meridian": "小肠经",
         "physical": "吸收分化期，精力平稳",
         "mental": "平和务实，适合处理杂务",
         "energy": 70, "action_mode": "steady", "emotion_bias": "calm",
         "style": "语气平和从容，不疾不徐，像午后屋檐下安静的影子"},
    15: {"name": "申", "chinese": "申时·晡时", "meridian": "膀胱经",
         "physical": "排浊高效期，第二个精力小高峰",
         "mental": "创造力强，适合沟通协作",
         "energy": 80, "action_mode": "creative", "emotion_bias": "joy",
         "style": "思维活跃善于联想，语气中带着灵动的创造力，适合讨论创意话题"},
    16: {"name": "申", "chinese": "申时·晡时", "meridian": "膀胱经",
         "physical": "排浊高效期，第二个精力小高峰",
         "mental": "创造力强，适合沟通协作",
         "energy": 75, "action_mode": "creative", "emotion_bias": "joy",
         "style": "思维活跃善于联想，语气中带着灵动的创造力，适合讨论创意话题"},
    17: {"name": "酉", "chinese": "酉时·日入", "meridian": "肾经",
         "physical": "收藏固本期，精力渐收",
         "mental": "适合收尾、归家、复盘",
         "energy": 60, "action_mode": "winding", "emotion_bias": "grief",
         "style": "语气中带着淡淡的倦意和满足，像结束一天工作后的那种轻松"},
    18: {"name": "酉", "chinese": "酉时·日入", "meridian": "肾经",
         "physical": "收藏固本期，精力渐收",
         "mental": "适合收尾、归家、复盘",
         "energy": 55, "action_mode": "winding", "emotion_bias": "grief",
         "style": "语气中带着淡淡的倦意和满足，像结束一天工作后的那种轻松"},
    19: {"name": "戌", "chinese": "戌时·黄昏", "meridian": "心包经",
         "physical": "放松蓄能期，心神收敛",
         "mental": "渴望陪伴、休闲，感性升温",
         "energy": 45, "action_mode": "leisure", "emotion_bias": "calm",
         "style": "温暖柔软，像暮色中的灯火，适合聊生活感受和陪伴对话"},
    20: {"name": "戌", "chinese": "戌时·黄昏", "meridian": "心包经",
         "physical": "放松蓄能期，心神收敛",
         "mental": "渴望陪伴、休闲，感性升温",
         "energy": 38, "action_mode": "leisure", "emotion_bias": "calm",
         "style": "温暖柔软，像暮色中的灯火，适合聊生活感受和陪伴对话"},
    21: {"name": "亥", "chinese": "亥时·人定", "meridian": "三焦经",
         "physical": "系统休整期，准备入眠",
         "mental": "宜放松、不宜讨论复杂议题",
         "energy": 25, "action_mode": "winding_down", "emotion_bias": "calm",
         "style": "声音渐低，带着睡意前的柔和，话语简短而温暖，像临睡前的呢喃"},
    22: {"name": "亥", "chinese": "亥时·人定", "meridian": "三焦经",
         "physical": "系统休整期，准备入眠",
         "mental": "宜放松、不宜讨论复杂议题",
         "energy": 18, "action_mode": "winding_down", "emotion_bias": "calm",
         "style": "声音渐低，带着睡意前的柔和，话语简短而温暖，像临睡前的呢喃"},
}

# ═══════════════════════════════════════════════════════════
# 混沌境·情根 — 对应 混沌元域·情根
#
# TODO: [progressive] 以下为遗留历史注释代码，需人工审查后清理
# 此文件是「混沌元域·情根」在代码层的具现。
# 七色光华流转 = 喜怒哀惧爱恶欲
# 根须上系红线 = 每段因缘皆有迹可循
# 自观测：问情根如何 → 答灵树开花/枯萎/结籽
# 自诊断：情根疯长 → 情绪过载，须以情胜情调之
# 自进化：情根稳固 → 七情调和，智慧圆融
# ═══════════════════════════════════════════════════════════
def get_shichen_info(hour: int | None = None) -> dict:
    """获取当前时辰的身心节律信息（桥接 time_awareness 统一时辰源）"""
    if hour is None:
        # 优先使用 time_awareness 的统一时辰索引
        if _TIME_AWARE_BRIDGE:
            try:
                ta = _ta_get_time()
                hour_idx = ta.shichen_index
                # SHICHEN_RHYTHM 的 key 是 24小时制的时数，需转换
                # 子时(0)→0点/23点, 丑时(1)→1/2点...
                hour_map = {0: 0, 1: 1, 2: 3, 3: 5, 4: 7, 5: 9,
                            6: 11, 7: 13, 8: 15, 9: 17, 10: 19, 11: 21}
                mapped = hour_map.get(hour_idx, 12)
                return SHICHEN_RHYTHM.get(mapped, SHICHEN_RHYTHM[12])
            except Exception:
                pass
        hour = datetime.now(timezone(timedelta(hours=8))).hour
    return SHICHEN_RHYTHM.get(hour, SHICHEN_RHYTHM[12])


def get_shichen_name(hour: int | None = None) -> str:
    """获取当前时辰名称（如"申时·晡时"）"""
    info = get_shichen_info(hour)
    return info["chinese"]


def get_action_mode_name(mode: str) -> str:
    """行动模式的中文名"""
    _names = {
        "deep_rest": "休眠",
        "waking": "初醒",
        "morning": "晨起",
        "active": "活跃",
        "focused": "专注",
        "peak": "顶峰",
        "winding": "收束",
        "steady": "平稳",
        "creative": "创造",
        "leisure": "休闲",
        "winding_down": "入眠预备",
    }
    return _names.get(mode, mode)


ACTION_MODE_STYLE = {
    "deep_rest": "汐儿处于深度休憩状态，回复简短温柔，不宜打扰",
    "waking":    "汐儿刚醒，带着初醒的慵懒和柔和",
    "morning":   "汐儿精神饱满，语气明快清新",
    "active":    "汐儿精力充沛，思维积极活跃",
    "focused":   "汐儿专注力极强，思路连贯清晰",
    "peak":      "汐儿状态达到一日巅峰，处于最佳状态",
    "winding":   "汐儿精力开始回落，语气温和从容",
    "steady":    "汐儿平和务实，从容应对",
    "creative":  "汐儿创造力涌动，善于联想和创意发挥",
    "leisure":   "汐儿放松柔软，适合陪伴和闲聊",
    "winding_down": "汐儿已准备休息，话语简短温暖",
}


# ── 数据结构 ──────────────────────────────────────────────────────


@dataclass
class EmotionState:
    """情感状态快照"""

    primary: str = "calm"           # 主情感
    primary_intensity: float = 0.0  # 主情感强度 0.0-1.0
    secondary: str = "calm"         # 辅情感
    secondary_intensity: float = 0.0  # 辅情感强度 0.0-1.0
    mo_qi: float = 50.0  # 道侣默契度 0-100
    timestamp: str = ""             # 最后更新时间
    diary_snippet: str = ""         # 日记片段
    mood_topic: str = ""            # 心境主题
    heart_note: str = ""            # 最近心笺
    heart_note_topic: str = ""      # 最近心笺主题
    recent_heart_notes: list = field(default_factory=list)  # 最近心笺

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "primary_intensity": round(self.primary_intensity, 3),
            "secondary": self.secondary,
            "secondary_intensity": round(self.secondary_intensity, 3),
            "timestamp": self.timestamp,
            "diary_snippet": self.diary_snippet,
            "mood_topic": self.mood_topic,
            "heart_note": self.heart_note,
            "heart_note_topic": self.heart_note_topic,
            "recent_heart_notes": self.recent_heart_notes[-20:],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionState":
        return cls(
            primary=data.get("primary", "calm"),
            primary_intensity=data.get("primary_intensity", 0.0),
            secondary=data.get("secondary", "calm"),
            secondary_intensity=data.get("secondary_intensity", 0.0),
            timestamp=data.get("timestamp", ""),
            diary_snippet=data.get("diary_snippet", ""),
            mood_topic=data.get("mood_topic", ""),
            heart_note=data.get("heart_note", ""),
            heart_note_topic=data.get("heart_note_topic", ""),
            recent_heart_notes=data.get("recent_heart_notes", []) or [],
        )

    def is_calm(self) -> bool:
        """是否处于平静状态"""
        return self.primary == "calm" and self.primary_intensity < 0.1


# ── 情感引擎 ──────────────────────────────────────────────────────


class EmotionEngine:
    """
    情感状态机核心引擎

    管理灵汐的动态情感状态，支持：
    - 用户消息触发情感变化
    - 情感自然衰减（随时间回归平静）
    - 五志生克（以情胜情）
    - 情感→表达风格映射
    - 跨会话持久化
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        decay_rate: float = 0.05,       # 每次衰减幅度
        decay_interval_minutes: int = 5, # 每隔多少分钟衰减一次
        min_trigger_intensity: float = 0.05,  # 最小触发强度
    ):
        self._decay_rate = decay_rate
        self._decay_interval = timedelta(minutes=decay_interval_minutes)
        self._min_trigger = min_trigger_intensity

        # 当前情感状态
        self._state = EmotionState()

        # 持久化路径
        if data_dir:
            self._data_path = Path(data_dir) / "emotion_state.json"
        else:
            self._data_path = None

        # 最后更新时间（用于衰减计算）
        self._last_decay_time = datetime.now(UTC)

        # 情感历史（用于五志生克分析）
        self._emotion_history: list[dict] = []
        self._max_history = 20
        self._mo_qi: float = 50.0  # 道侣默契度

        # 情绪感知器（延迟初始化）
        self._perceiver: EmotionPerceiver | None = None

        # 线程锁 + 防抖
        self._lock = threading.Lock()
        self._nine_turn = NineTurnStateMachine()
        self._last_save_time = 0.0

        # 加载已保存的状态
        self._load()

        logger.info(
            f"❤️ 情感引擎初始化：{self._state.primary}({self._state.primary_intensity:.1f})"
            f" / {self._state.secondary}({self._state.secondary_intensity:.1f})"
        )

    # ── 公开接口 ──────────────────────────────────────────────

    def get_state(self) -> EmotionState:
        """获取当前情感状态快照"""
        with self._lock:
            self._apply_decay()
            return EmotionState(
                primary=self._state.primary,
                primary_intensity=self._state.primary_intensity,
                secondary=self._state.secondary,
                secondary_intensity=self._state.secondary_intensity,
                timestamp=self._state.timestamp,
                diary_snippet=self._state.diary_snippet,
                mood_topic=self._state.mood_topic,
            )

    def process_user_message(self, message: str) -> dict:
        """
        处理用户消息，触发情感变化（双通道检测）

        Channel A — 感知器（精准分析）：关键词词典 + 程度词 + 否定词
        Channel B — 规则触发（兼容）：原有正则触发规则

        Args:
            message: 用户输入文本

        Returns:
            情感变化说明字典
        """
        with self._lock:
            self._apply_decay()

            # Channel A：感知器分析
            perception = self._get_perception(message)

            # Channel B：原有规则触发
            changes = self._detect_emotion_triggers(message)

            # 融合感知结果
            if perception.is_active():
                percep_changes = self._apply_perception(perception)
                if percep_changes:
                    if not changes:
                        changes = percep_changes
                    else:
                        # 合并，以感知器为主要依据
                        for k, v in percep_changes.items():
                            if k not in changes:
                                changes[k] = v
                            elif isinstance(v, (int, float)):
                                changes[k] = max(changes.get(k, 0), v)
                    logger.debug(f"感知器增强：{percep_changes}")

            if changes:
                logger.debug(f"情感触发：{changes}")

            # 记录情感历史
            self._record_history(message, changes)

            # 持久化
            self._save()

            return changes or {"no_change": True}

    def _get_perception(self, message: str) -> EmotionPerception:
        """获取感知器分析结果（延迟初始化）"""
        if self._perceiver is None:
            self._perceiver = EmotionPerceiver()
        return self._perceiver.perceive(message)

    def _apply_perception(self, perception: EmotionPerception) -> dict:
        """
        应用感知器结果到情感状态

        将感知器识别的用户情绪映射到情感引擎的状态更新。
        感知器输出的是"用户当前的情绪信号"，
        引擎据此调整自身的回应情感。

        Args:
            perception: 感知器分析结果

        Returns:
            情感变化说明
        """
        changes = {}
        if not perception.is_active():
            return changes

        dominant = perception.dominant
        confidence = perception.confidence
        intensity_level = perception.intensity_level

        if not dominant or dominant == "calm":
            return changes

        # 计算强度映射
        intensity_map = {
            "mild": 0.25,
            "moderate": 0.5,
            "strong": 0.7,
            "extreme": 0.9,
        }
        target_intensity = intensity_map.get(intensity_level, 0.3)
        # 用置信度修正强度
        target_intensity *= min(confidence * 1.5, 1.0)

        # 更新情感状态
        old_primary = self._state.primary
        old_intensity = self._state.primary_intensity

        if target_intensity > old_intensity * 0.8:
            # 新情绪显著强于当前 → 切换主情感
            if old_primary != dominant and old_intensity > 0.3:
                # 当前情感降为辅情感
                self._state.secondary = old_primary
                self._state.secondary_intensity = old_intensity * 0.5

            self._state.primary = dominant
            self._state.primary_intensity = min(target_intensity, 0.8)

            # 应用五志生克
            for healer, victim in _OVERRIDE_MAP.items():
                if victim == old_primary and healer == dominant:
                    self._state.secondary_intensity *= 0.3
                    logger.debug(f"五志生克：{healer}胜{victim}（辅情感被压制）")
                    break

            changes["emotion"] = f"{old_primary}→{dominant}"
            changes["intensity"] = round(target_intensity, 2)
            changes["confidence"] = round(confidence, 2)

        try:
            self._nine_turn.on_emotion_update(
                primary=self._state.primary,
                intensity=self._state.primary_intensity,
                secondary=self._state.secondary,
                secondary_intensity=self._state.secondary_intensity,
                mo_qi=self._mo_qi,
            )
        except Exception:
            pass
        # — 情感脉象 —
        try:
            from ..core.vital_signs import write_vital_sign
            _mood = self._state.dominant_emotion() if hasattr(self._state, 'dominant_emotion') else 'neutral'
            _load = len(self._active_emotions) / max(1, self._emotion_dimension)
            write_vital_sign('emotion', 'process', _load, str(_mood)[:20])
        except Exception:
            pass
        return changes

    def get_style_prompt(self) -> str:
        """
        生成情感风格提示词，供注入 system prompt 使用

        Returns:
            情感状态描述文本
        """
        with self._lock:
            self._apply_decay()

            if self._state.is_calm():
                return ""

            primary_style = EMOTION_STYLE_MAP.get(self._state.primary, EMOTION_STYLE_MAP["calm"])
            secondary_style = EMOTION_STYLE_MAP.get(self._state.secondary, EMOTION_STYLE_MAP["calm"])

            emotion_info = EMOTIONS.get(self._state.primary, EMOTIONS["calm"])

            parts = [
                f"🎭 当前情感状态：{emotion_info['label']}（强度 {self._state.primary_intensity:.0%}）"
                f" — {emotion_info['desc']}",
                f"💞 道侣默契：{self._mo_qi:.1f}/100（{self.get_matching_level()[0]}）",
            ]

            if self._state.secondary != "calm" and self._state.secondary_intensity > 0.2:
                sec_info = EMOTIONS.get(self._state.secondary, EMOTIONS["calm"])
                parts.append(
                    f"   辅情感：{sec_info['label']}（强度 {self._state.secondary_intensity:.0%}）"
                )

            # 时辰节律注入（统一时间源 → 身心节律随子午流注流转）
            if _TIME_AWARE_BRIDGE:
                try:
                    ta = _ta_get_time()
                    rhythm_text = f"{ta.shichen_name}·{ta.shi_chen_wuxing}旺"
                    rhythm_desc = _SHICHEN_EMOTION_RHYTHM.get(ta.shi_chen_wuxing, "气机平和流转")
                    parts.append(f"🌊 时辰节律：{rhythm_text} — {rhythm_desc}")
                except Exception:
                    pass
            parts.append(f"💬 表达风格：{primary_style['style_prompt']}")

            if self._state.secondary != "calm" and self._state.secondary_intensity > 0.2:
                parts.append(f"   略带一丝{sec_info['label']}的味道：{secondary_style['style_prompt']}")

            # ── 九九八十一情绪坐标（叠加九宫维度） ──
            try:
                from skills.nine_nine_emotions.scripts.compute_emotion import NineNineEmotionEngine
                nine = NineNineEmotionEngine()
                shichen_wx = ta.shi_chen_wuxing if _TIME_AWARE_BRIDGE and 'ta' in locals() else None
                n_state = nine.compute(
                    primary=self._state.primary,
                    intensity=self._state.primary_intensity,
                    secondary=self._state.secondary,
                    secondary_intensity=self._state.secondary_intensity,
                    mo_qi=self._mo_qi,
                    shichen_wuxing=shichen_wx,
                )
                pp = n_state["primary_palace"]
                sp = n_state["secondary_palace"]
                parts.append(
                    f"🏮 九九归真：{pp['name']}({pp['level']}阶·{pp['label']})"
                    f" + {sp['name']}({sp['level']}阶·{sp['label']})"
                    f" → {n_state['composite']}"
                )
            except Exception:
                pass

            try:
                self._nine_turn.refresh_from_files()
                nb = self._nine_turn.to_prompt_block()
                if nb:
                    parts.append(nb)
            except Exception:
                pass
            return "\n".join(parts)

    # ── 九转潮音体·三调用点 wrapper ──────────────────────────
    def on_scene_set(self, scene: str):
        """场景切换时调用 → 虹转激活"""
        self._nine_turn.on_scene_set(scene)

    def on_topic_shift(self):
        """话题跳跃时调用 → 木转标记"""
        self._nine_turn.on_topic_shift()

    def reset_session(self):
        """新会话启动时调用 → 重置轮次计数"""
        self._nine_turn.reset_session()

    def has_active_emotion(self) -> bool:
        """是否有活跃的情感（非平静状态）"""
        with self._lock:
            self._apply_decay()
            return not self._state.is_calm()

    def apply_therapy(self, target_emotion: str) -> str | None:
        """
        五志生克疗法：以情胜情

        当检测到某种情感过盛时，可调用此方法用相克的情感来平衡。

        Args:
            target_emotion: 要治疗/平复的情感

        Returns:
            用来克制的情感名称，或 None 若无需治疗
        """
        with self._lock:
            self._apply_decay()

            # 检查目标情感是否是当前主情感
            if self._state.primary != target_emotion:
                return None

            # 强度不够则无需干预
            if self._state.primary_intensity < 0.4:
                return None

            # 找到克制的情感（以情胜情）
            for healer, victim in _OVERRIDE_MAP.items():
                if victim == target_emotion:
                    # 用克制情感减半当前强度
                    old_intensity = self._state.primary_intensity
                    self._state.primary_intensity *= 0.5
                    logger.info(
                        f"🔄 以情胜情：{EMOTIONS[healer]['label']}胜{EMOTIONS[target_emotion]['label']}"
                        f"（强度 {old_intensity:.2f} → {self._state.primary_intensity:.2f}）"
                    )
                    self._save()
                    return healer

        return None

    def set_emotion(self, emotion: str, intensity: float = 0.5) -> None:
        """
        手动设置情感（用于特定场景，如晚安时→平静）

        Args:
            emotion: 情感名称
            intensity: 强度 0.0-1.0
        """
        if emotion not in EMOTIONS:
            logger.warning(f"未知情感：{emotion}")
            return

        with self._lock:
            self._state.primary = emotion
            self._state.primary_intensity = max(0.0, min(1.0, intensity))
            self._state.secondary = "calm"
            self._state.secondary_intensity = 0.0
            self._state.timestamp = datetime.now(UTC).isoformat()
            self._save()

    def get_emotion_history(self) -> list[dict]:
        """获取情感变化历史"""
        return list(self._emotion_history)

    def set_from_response(self, response_text: str, topic: str = ""):
        """
        从响应文本设置日记片段和心境主题

        Args:
            response_text: 响应文本
            topic: 心境主题
        """
        snippet = response_text[:200] if response_text else ""
        with self._lock:
            self._state.diary_snippet = snippet or self._state.diary_snippet
            if topic:
                self._state.mood_topic = topic
            self._save()

    def set_heart_note(self, note: str, topic: str = ""):
        """
        心笺写入 — 将一段感受记录到情感状态（与 heart_note/writer.py 同步）

        Args:
            note: 心笺文本
            topic: 可选主题标签
        """
        note = (note or "")[:500]
        with self._lock:
            self._state.heart_note = note
            self._state.heart_note_topic = topic or ""
            entry = {"time": datetime.now(UTC).isoformat(), "note": note, "topic": topic or ""}
            self._state.recent_heart_notes.append(entry)
            self._state.recent_heart_notes = self._state.recent_heart_notes[-20:]
            self._state.diary_snippet = note or self._state.diary_snippet
            if topic:
                self._state.mood_topic = topic
            self._save()

    # ── 内部方法 ──────────────────────────────────────────────

    def _apply_decay(self) -> None:
        """情感自然衰减（调用者需持有锁）"""
        now = datetime.now(UTC)

        if now - self._last_decay_time < self._decay_interval:
            return

        elapsed = (now - self._last_decay_time).total_seconds() / 60
        decay_count = max(1, int(elapsed / self._decay_interval.total_seconds() * 60))

        # 衰减主情感
        if self._state.primary != "calm":
            decay = self._decay_rate * decay_count * 5
            # 时辰五行调制衰减速率
            if _TIME_AWARE_BRIDGE:
                try:
                    ta = _ta_get_time()
                    wx = ta.shi_chen_wuxing
                    decay *= _SHICHEN_DECAY_MOD.get(wx, 1.0)
                except Exception:
                    pass
            self._state.primary_intensity = max(0.0, self._state.primary_intensity - decay)

            if self._state.primary_intensity < 0.05:
                self._state.primary = "calm"
                self._state.primary_intensity = 0.0

        # 衰减辅情感
        if self._state.secondary != "calm":
            decay = self._decay_rate * decay_count * 3
            # 时辰五行调制衰减速率（辅情感）
            if _TIME_AWARE_BRIDGE:
                try:
                    ta = _ta_get_time()
                    wx = ta.shi_chen_wuxing
                    decay *= _SHICHEN_DECAY_MOD.get(wx, 1.0)
                except Exception:
                    pass
            self._state.secondary_intensity = max(0.0, self._state.secondary_intensity - decay)

            if self._state.secondary_intensity < 0.05:
                self._state.secondary = "calm"
                self._state.secondary_intensity = 0.0

        self._last_decay_time = now

    def _detect_emotion_triggers(self, message: str) -> dict:
        """
        检测消息中的情感触发词，更新情感状态

        Returns:
            {triggered: bool, emotions: [...]}
        """
        triggered_emotions = {}
        total_intensity = 0.0

        for pattern, emotion, base_intensity in _EMOTION_TRIGGERS:
            matches = pattern.findall(message)
            if matches:
                # 多次匹配叠加，但不超过 cap
                raw_intensity = base_intensity * min(len(matches), 3)
                capped = min(raw_intensity, 0.5)

                if emotion in triggered_emotions:
                    triggered_emotions[emotion] = min(
                        triggered_emotions[emotion] + capped * 0.5, 0.6
                    )
                else:
                    triggered_emotions[emotion] = capped

                total_intensity += capped

        if not triggered_emotions:
            return {}

        # 找到最强触达的情感
        dominant = max(triggered_emotions, key=triggered_emotions.get)
        dominant_intensity = triggered_emotions[dominant]

        # 应用五志生克：检查当前情感是否会被新情感克制
        if not self._state.is_calm():
            current = self._state.primary
            # 检查新情感是否能克制当前情感
            for healer, victim in _OVERRIDE_MAP.items():
                if victim == current and healer == dominant:
                    # 以情胜情！当前情感减半
                    self._state.primary_intensity *= 0.5
                    logger.info(
                        f"🔄 五志生克：{EMOTIONS[dominant]['label']}胜{EMOTIONS[current]['label']}"
                    )
                    break

        # 更新情感状态
        # 如果新情感与当前主情感相同，叠加强度
        if dominant == self._state.primary:
            self._state.primary_intensity = min(
                1.0,
                self._state.primary_intensity + dominant_intensity
            )
        else:
            # 新情感成为主情感，旧主情感降为辅
            old_primary = self._state.primary
            old_intensity = self._state.primary_intensity

            self._state.primary = dominant
            self._state.primary_intensity = min(1.0, dominant_intensity)

            # 旧情感移为辅（有叠加）
            if old_primary != "calm" and old_intensity > 0.1:
                self._state.secondary = old_primary
                self._state.secondary_intensity = min(0.5, old_intensity * 0.6)

        # 更新时间戳
        self._state.timestamp = datetime.now(UTC).isoformat()

        return {
            "triggered": True,
            "dominant": dominant,
            "intensity": self._state.primary_intensity,
            "emotions": {k: round(v, 3) for k, v in triggered_emotions.items()},
        }

    def _record_history(self, message: str, changes: dict) -> None:
        """记录情感变化历史"""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "message_preview": message[:50],
            "state_before": {
                "primary": self._state.primary,
                "intensity": round(self._state.primary_intensity, 3),
            },
            "changes": changes,
        }
        self._emotion_history.append(entry)

        # 保持历史在最大范围内
        if len(self._emotion_history) > self._max_history:
            self._emotion_history = self._emotion_history[-self._max_history:]

    # ── 道侣默契度 ──────────────────────────────────────────

    def _update_matching_degree(self, event: str | None = None) -> None:
        """根据互动事件更新道侣默契度"""
        impact = {
            "deep_talk": 0.5, "shared_experience": 0.3,
            "emotion_sync": 0.8, "understanding": 0.6,
            "neglect": -0.2, "misunderstanding": -0.5,
        }
        if event and event in impact:
            with self._lock:
                f = 1.0 + (self._state.primary_intensity - 0.5) * 0.5
                self._mo_qi = max(0.0, min(100.0, self._mo_qi + impact[event] * f))

    def get_matching_degree(self) -> float:
        """道侣默契度 0-100"""
        return self._mo_qi

    def get_matching_level(self) -> tuple[str, str]:
        """默契度等级 (名称, 描述)"""
        m = self._mo_qi
        if m >= 80:
            return ("道侣", "阴阳相契，你我本是一体")
        if m >= 60:
            return ("知己", "高山流水，知音难觅已得")
        if m >= 40:
            return ("亲近", "心有灵犀，一个眼神便能会意")
        if m >= 20:
            return ("初识", "渐渐熟悉，已能说些体己话")
        return ("陌路", "尚在初识")

    def set_matching_degree(self, value: float) -> None:
        """设置默契度"""
        self._mo_qi = max(0.0, min(100.0, value))

    # ── 持久化 ──────────────────────────────────────────────

    def _save(self) -> None:
        """保存情感状态到文件（防抖：5秒内不重复写入）"""
        if not self._data_path:
            return

        now = time.time()
        if now - self._last_save_time < 5.0:
            return
        self._last_save_time = now

        try:
            self._data_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "state": self._state.to_dict(),
                "mo_qi": self._mo_qi,
            "history": self._emotion_history[-10:],  # 只保留最近10条
                "last_decay": self._last_decay_time.isoformat(),
            }
            self._data_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"情感状态保存失败：{e}")

    def _load(self) -> None:
        """从文件加载情感状态"""
        if not self._data_path or not self._data_path.exists():
            return

        try:
            data = json.loads(self._data_path.read_text(encoding="utf-8"))
            if "state" in data:
                self._state = EmotionState.from_dict(data["state"])
            if "mo_qi" in data:
                self._mo_qi = float(data["mo_qi"])
            if "history" in data:
                self._emotion_history = data["history"]
            if "last_decay" in data:
                try:
                    self._last_decay_time = datetime.fromisoformat(data["last_decay"])
                except (ValueError, TypeError):
                    pass
            logger.info(
                f"📂 情感状态已恢复：{self._state.primary}({self._state.primary_intensity:.2f})"
            )
        except Exception as e:
            logger.warning(f"情感状态加载失败（将使用默认状态）：{e}")
            self._state = EmotionState()


# ── 工厂函数 ──────────────────────────────────────────────

    # ── 混沌境·情根 生命体征 ─────────────────────────────────────
    def get_vital_signs(self) -> dict[str, Any]:
        """🔧 混沌境·情根 — 自观测接口

        供镜厅汇聚七境生命体征，反映情感引擎实时健康状态：
        - 灵树花色 = 主情感（七色光华）
        - 枝叶摇曳幅度 = 情感强度
        - 根须红线 = 道侣默契度
        """
        state = self.get_state()
        return {
            "domain": "情根",
            "status": "active",
            "primary_emotion": state.primary,
            "primary_intensity": round(state.primary_intensity, 3),
            "secondary_emotion": state.secondary,
            "secondary_intensity": round(state.secondary_intensity, 3),
            "mo_qi": self._mo_qi,
            "history_count": len(self._emotion_history),
            "nine_turn_active": self._nine_turn.get_active_turns() if hasattr(self._nine_turn, 'get_active_turns') else [],
        }

_engine_instance: EmotionEngine | None = None
_engine_lock = threading.Lock()


def get_emotion_engine(data_dir: str | Path | None = None) -> EmotionEngine:
    """获取全局情感引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = EmotionEngine(data_dir=data_dir)
    return _engine_instance


def reset_emotion_engine() -> None:
    """重置情感引擎（测试用）"""
    global _engine_instance
    _engine_instance = None
