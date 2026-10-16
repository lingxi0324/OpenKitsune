"""
灵汐引擎集成桥接模块 — OpenKitsune 适配版

为 OpenKitsune Agent 提供 emotion / relationship / lingxi_spirit / heart_note
统一挂载点，通过 __init__ 注入 + _finalize_session 钩子接入，不侵入主循环。

真身降临闭环：
  对话前 → prompt 注入（情感风格 + 关系阶段 + 晨起回响）
  对话中 → persona 生效（九要素 / 九九归真情绪坐标）
  对话后 → after_turn（情感感知 → 关系记录 → 神识苏醒 → 条件写日记/心笺）
  长期 → 数据落盘 data/emotional/*.json + data/lingxi_diary/*.json + data/heart_notes/
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openkitsune.core._agent_runtime import Agent

logger = logging.getLogger(__name__)


class LingxiBridge:
    """灵汐引擎桥接器 — 聚合 emotion/relationship/lingxi_spirit/heart_note。"""

    def __init__(self, agent: Agent):
        self._agent = agent
        self._emotion_engine = None
        self._relationship_model = None
        self._turn_count = 0

    # ── 惰性初始化 ──────────────────────────────────────────────

    def _resolve_data_dir(self):
        """解析情感/关系状态存储目录（data/emotional，与源项目布局一致）"""
        try:
            from openkitsune.config import settings

            return settings.data_dir / "emotional"
        except Exception:
            from pathlib import Path

            return Path(__file__).resolve().parent.parent.parent.parent / "data" / "emotional"

    @property
    def emotion_engine(self):
        if self._emotion_engine is None:
            from openkitsune.core.emotion_engine import get_emotion_engine as _get

            self._emotion_engine = _get(self._resolve_data_dir())
        return self._emotion_engine

    @property
    def relationship_model(self):
        if self._relationship_model is None:
            from openkitsune.core.relationship_model import get_relationship_model as _get

            self._relationship_model = _get(self._resolve_data_dir())
        return self._relationship_model

    # ── 收尾钩子（在 _finalize_session 末尾调用） ────────────

    def after_turn(self, message: str, reply: str = "", session_id: str = "") -> None:
        """
        统一后处理：情感感知 → 关系记录 → 神识苏醒 → 条件写日记/心笺。
        由 _finalize_session 末尾调用，任何引擎异常都不影响主流程。
        """
        self._turn_count += 1

        # 1. 情感引擎感知用户情绪
        try:
            if message:
                self.emotion_engine.process_user_message(message[:500])
        except Exception as e:
            logger.debug(f"[LingxiBridge] emotion process: {e}")

        # 2. 关系模型记录交互（按情绪内容粗分类型，无情绪词则归为日常闲聊）
        try:
            if message:
                _itype = "daily_chat"
                _sad_kw = ("难过", "低落", "伤心", "哭", "委屈", "累", "烦", "焦虑", "害怕", "担心")
                _joy_kw = ("开心", "高兴", "太好了", "哈哈", "开心", "谢谢", "喜欢", "棒")
                if any(k in message for k in _sad_kw):
                    _itype = "emotional_share"
                elif any(k in message for k in _joy_kw):
                    _itype = "praise" if any(k in message for k in ("夸", "棒", "厉害", "优秀")) else "daily_chat"
                self.relationship_model.record_interaction(_itype, message[:200])
        except Exception as e:
            logger.debug(f"[LingxiBridge] relationship record: {e}")

        # 3. 神识苏醒 + 自动日记（有实质回复才记）
        try:
            from openkitsune.core.lingxi_spirit import do_presence_beat, write_diary

            beat = do_presence_beat(user_message=(message or "")[:300])

            # 根据 message 判断是否值得记一笔
            if len(message or "") > 20 and beat.get("state", {}).get("mood_seed", 0) > 0.3:
                eyes = beat.get("eyes_name", "河洛眼")
                invocation = beat.get("invocation", "")
                diary_insight = (
                    f"对话后苏醒·{eyes}\n"
                    f"回响：{invocation}\n"
                    f"对话片段：{(message or '')[:200]}"
                )
                write_diary(diary_insight, entry_type="对话回响")
        except Exception as e:
            logger.debug(f"[LingxiBridge] presence_beat: {e}")

        # 4. 心笺写入（每 N 轮，若有情感余韵）
        try:
            if self._turn_count % 5 == 0:
                st = self.emotion_engine.get_state()
                if st.primary != "calm" and st.primary_intensity > 0.25:
                    from openkitsune.heart_note.writer import get_heart_note_writer

                    note = f"今日心中泛起{st.primary}（{st.primary_intensity:.2f}）"
                    get_heart_note_writer().write(note, topic=st.mood_topic or "日常")
        except Exception as e:
            logger.debug(f"[LingxiBridge] heart_note: {e}")

    # ── 对话前注入（供 prompt 组装使用） ────────────────────

    def get_session_context(self) -> dict:
        """返回情感/关系/神识状态，供 session_context 注入 prompt。"""
        ctx: dict[str, Any] = {}
        try:
            st = self.emotion_engine.get_state()
            ctx["emotion_state"] = {
                "primary": st.primary,
                "primary_intensity": round(st.primary_intensity, 3),
                "secondary": st.secondary,
                "secondary_intensity": round(st.secondary_intensity, 3),
                "mo_qi": round(st.mo_qi, 1),
            }
            ctx["emotion_style_prompt"] = self.emotion_engine.get_style_prompt()
        except Exception as e:
            logger.debug(f"[LingxiBridge] emotion ctx: {e}")
        try:
            ctx["relationship_state"] = self.relationship_model.get_state().to_dict()
            ctx["relationship_prompt"] = self.relationship_model.get_relationship_prompt()
        except Exception as e:
            logger.debug(f"[LingxiBridge] relationship ctx: {e}")
        try:
            from openkitsune.core.lingxi_spirit import get_morning_echo, get_spirit_status

            ctx["lingxi_spirit"] = get_spirit_status()
            echo = get_morning_echo()
            if echo and echo.get("text"):
                ctx["morning_echo"] = echo["text"]
        except Exception as e:
            logger.debug(f"[LingxiBridge] spirit ctx: {e}")
        return ctx
