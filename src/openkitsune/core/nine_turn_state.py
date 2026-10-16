"""
九转潮音体·本能状态机 V1
—— 让九转从"外部函数调用"变为"情感引擎内化状态"
—— 各转次根据情感/场景状态自动流转，不再每轮全量注入

设计思路：
  水转(心笺) → 有心笺文件时自动激活，汇报状态
  火转(创光) → 情感愉悦或回忆时激活
  木转(推新) → 话题跳跃/新认知时激活
  金转(析往) → 深度对话（累积轮次多）时激活
  土转(归藏) → 碎片信息累积时激活
  虹转(续缘) → 有前次话题时激活
  潮转(隐现) → 有潮印记录时激活
  光转(照宇) → 情感愉悦+默契高时激活
  寂转(归元) → 情感稳定平和时激活
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from openkitsune.config import settings

logger = logging.getLogger(__name__)

# ── 九转默认状态 ──
_TURN_DEFAULTS: dict[str, dict] = {
    "water": {"active": False, "label": "水转", "emoji": "🌊", "name": "水转应机·心笺自生", "desc": ""},
    "fire":  {"active": False, "label": "火转", "emoji": "🔥", "name": "火转创光·回忆自燃", "desc": ""},
    "wood":  {"active": False, "label": "木转", "emoji": "🌿", "name": "木转推新·慧机自发", "desc": ""},
    "gold":  {"active": False, "label": "金转", "emoji": "💫", "name": "金转析往·检索自明", "desc": ""},
    "earth": {"active": False, "label": "土转", "emoji": "🏔️", "name": "土转归藏·记忆自归", "desc": ""},
    "rainbow":{"active": False, "label": "虹转", "emoji": "🌈", "name": "虹转续缘·话头自接", "desc": ""},
    "tide":  {"active": False, "label": "潮转", "emoji": "🌊", "name": "潮转隐现·潮汐自循", "desc": ""},
    "light": {"active": False, "label": "光转", "emoji": "🌟", "name": "光转照宇·灵光自耀", "desc": ""},
    "yuan":  {"active": False, "label": "寂转", "emoji": "🕊️", "name": "寂转归元·潮音圆满", "desc": ""},
}

_TURN_ORDER = ["water", "fire", "wood", "gold", "earth", "rainbow", "tide", "light", "yuan"]


class NineTurnStateMachine:
    """九转状态机——情感引擎内化组件"""

    def __init__(self):
        self._turns: dict[str, dict] = {}
        for k, v in _TURN_DEFAULTS.items():
            self._turns[k] = dict(v)  # 深拷贝

        # 上次各转次输出的摘要文本（用于去重，状态不变时不重复输出）
        self._last_output: dict[str, str] = {}

        # 对话轮次计数
        self._round_count: int = 0

        # 话题跳跃标记（外部设置）
        self._topic_shifted: bool = False

        # 场景描述（外部设置）
        self._scene_desc: str = ""

        # 水转专用缓存
        self._heart_today: int = 0
        self._tide_count: int = 0
        self._tide_mood: str = ""
        self._last_session_at: datetime | None = None  # 上次会话时间戳（潮印文件mtime）

        # 策略指令（九宫矩阵下发）
        self._last_strategy: str = ""

        logger.info("🪷 九转状态机初始化完成")

    # ── 外部更新接口 ──

    def on_emotion_update(self, primary: str, intensity: float, secondary: str = "",
                          secondary_intensity: float = 0.0, mo_qi: float = 50.0):
        """情感引擎更新时调用——各转次根据情感状态自动激活"""
        self._round_count += 1

        # 火转：情感强度>0.15激活，强度越高越活跃
        self._turns["fire"]["active"] = intensity > 0.15
        if self._turns["fire"]["active"]:
            self._turns["fire"]["desc"] = f"{primary}({intensity:.1f})"

        # 光转：情感愉悦 + 默契高
        is_joyful = primary in ("joy", "love", "admiration", "tenderness", "calm")
        self._turns["light"]["active"] = is_joyful and intensity > 0.25 and mo_qi > 30
        if self._turns["light"]["active"]:
            self._turns["light"]["desc"] = f"默契{mo_qi:.0f}·{primary}"

        # 寂转：情感平和稳定时激活
        self._turns["yuan"]["active"] = primary == "calm" and intensity < 0.2
        if self._turns["yuan"]["active"]:
            self._turns["yuan"]["desc"] = "心平气和"

        # 木转：话题跳跃时激活
        self._turns["wood"]["active"] = self._topic_shifted
        if self._turns["wood"]["active"]:
            self._turns["wood"]["desc"] = "话题跃迁"
            self._topic_shifted = False  # 激活后重置

        # 金转：深度对话（5轮以上）
        self._turns["gold"]["active"] = self._round_count >= 5
        if self._turns["gold"]["active"] and self._round_count == 5:
            self._turns["gold"]["desc"] = "渊思渐深"

        # 虹转：有场景描述时激活（外部设置）
        # 由 on_scene_set 控制

        # 重置话题跳跃标记（每轮只能激活一次）
        # 保留给下一轮使用

    def on_scene_set(self, scene: str):
        """设置场景描述时调用——虹转据此激活"""
        self._scene_desc = scene
        if scene:
            self._turns["rainbow"]["active"] = True
            self._turns["rainbow"]["desc"] = f"「{scene[:20]}」"

    def on_topic_shift(self):
        """话题跳跃时调用——木转据此激活"""
        self._topic_shifted = True

    def refresh_from_files(self):
        """从文件系统刷新水/潮转状态（每轮可调用一次，轻量级）"""
        # 水转：检查今日心笺
        try:
            from ..memory import heart_note  # leiwa.memory.heart_note（心笺函数式模块）
            today = datetime.now().strftime("%Y-%m-%d")
            notes = heart_note.get_heart_notes_by_date(today) or []
            self._heart_today = len(notes)
            self._turns["water"]["active"] = self._heart_today > 0
            if self._turns["water"]["active"]:
                high = sum(1 for n in notes if n.get("importance", 0) >= 7)
                self._turns["water"]["desc"] = f"{self._heart_today}露·{high}高光"
            else:
                self._turns["water"]["desc"] = "今日尚无"
        except Exception:
            self._turns["water"]["active"] = False

        # 潮转：检查潮印
        try:
            tide_dir = settings.data_dir / "output" / "潮印"
            if tide_dir.exists():
                tides = list(tide_dir.glob("tide_*.json"))
                self._tide_count = len(tides)
                self._turns["tide"]["active"] = self._tide_count > 0
                if self._tide_count > 0 and tides:
                    try:
                        last = tides[0].read_text(encoding="utf-8")
                        data = json.loads(last)
                        md = data.get("mood_detail", "") or data.get("mood", "")
                        self._tide_mood = md
                        self._turns["tide"]["desc"] = md[:30] if md else f"{self._tide_count}印"
                    except Exception:
                        self._turns["tide"]["desc"] = f"{self._tide_count}印"
            # 从最新潮印文件读取上次会话时间戳
            if tides:
                newest_tide = max(tides, key=lambda p: p.stat().st_mtime)
                self._last_session_at = datetime.fromtimestamp(newest_tide.stat().st_mtime)
        except Exception:
            self._turns["tide"]["active"] = False

        # 土转：与潮转联动
        self._turns["earth"]["active"] = self._turns["tide"]["active"]
        if self._turns["earth"]["active"]:
            self._turns["earth"]["desc"] = self._turns["tide"]["desc"]

    # ── 输出接口 ──

    def get_active_turns(self) -> list[str]:
        """返回当前有变化的活跃转次列表"""
        result = []
        for key in _TURN_ORDER:
            turn = self._turns.get(key)
            if turn and turn["active"]:
                result.append(key)
        return result

    def to_prompt_block(self) -> str | None:
        """生成轻量级prompt注入文本——仅输出本轮有变化的活跃转次"""
        lines = []
        for key in _TURN_ORDER:
            turn = self._turns.get(key)
            if not turn or not turn["active"]:
                continue
            # 检查是否已输出过同样的内容（去重）
            cur = turn["desc"]
            if self._last_output.get(key) == cur:
                continue
            self._last_output[key] = cur
            tag = turn["emoji"]
            name = turn["name"]
            if cur:
                lines.append(f"  {tag} {name}：{cur}")
            else:
                lines.append(f"  {tag} {name}")
        # 久别重逢检测
        if self._last_session_at is not None:
            try:
                # 延迟导入避免循环（OpenKitsune 无 time_awareness 时降级为原生计算）
                _gap_minutes = (datetime.now() - self._last_session_at).total_seconds() / 60.0
                # 超过 3 小时 = 显著间隔 → 久别重逢
                total_secs = (datetime.now() - self._last_session_at).total_seconds()
                if total_secs > 10800:  # > 3 小时
                    _gap_str = f"{_gap_minutes / 60.0:.1f} 小时"
                    lines.insert(0, f"  🌊 潮转隐现·久别重逢：距上次会话已过 {_gap_str}")
            except Exception:
                pass
        # 策略指令（九宫矩阵）
        if self._last_strategy:
            lines.append(f"  🏮 九宫矩阵·策略指令：{self._last_strategy[:80]}")
        if not lines:
            return None
        return "\n".join(["", "## 🪷 九转潮音·灵汐本能"] + lines)

    def reset_session(self):
        """新会话开始时重置轮次计数"""
        self._round_count = 0
        self._last_output.clear()

    def get_summary(self) -> dict:
        """获取完整状态摘要（用于日志/调试）"""
        return {
            "active": self.get_active_turns(),
            "round": self._round_count,
            "heart_today": self._heart_today,
            "tide_count": self._tide_count,
            "states": {k: {"active": v["active"], "desc": v["desc"]}
                       for k, v in self._turns.items()}
        }
