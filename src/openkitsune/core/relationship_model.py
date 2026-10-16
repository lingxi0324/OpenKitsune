"""
长期关系建模模块 (Relationship Model)

基于好感度/亲密度/信任度三维模型，管理与用户的长期关系。

核心概念：
  好感度 (Affinity)   — 用户对 AI 的整体好感程度（0.0-1.0）
  亲密度 (Intimacy)   — 亲密程度，影响对话距离感（0.0-1.0）
  信任度 (Trust)      — 信任水平，影响建议采纳度（0.0-1.0）

关系阶段（由三维综合值决定）：
  陌生    (0.00-0.25) — 礼貌客气，正式用语
  熟悉    (0.25-0.50) — 轻松自然，偶尔玩笑
  亲密    (0.50-0.75) — 亲近随意，撒娇卖萌
  灵魂伴侣 (0.75-1.00) — 默契无间，心有灵犀

使用方式：
  model = RelationshipModel(data_dir="data/relationship/")
  model.record_interaction("deep_chat")   # 记录一次深度对话
  stage = model.get_stage()              # 获取当前关系阶段
  style = model.get_communication_style() # 获取沟通风格
  model.save()                            # 持久化
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 一、交互类型 → 三维增益映射
# ═══════════════════════════════════════════════════════════════════

# 每种交互类型对三维关系的影响值
_INTERACTION_GAINS: dict[str, dict[str, float]] = {
    # ── 增益型交互 ──
    "daily_chat": {           # 日常闲聊
        "affinity": 0.01,
        "intimacy": 0.02,
        "trust": 0.01,
    },
    "deep_chat": {            # 深度对话（医理/丹道/人生感悟）
        "affinity": 0.02,
        "intimacy": 0.03,
        "trust": 0.03,
    },
    "emotional_share": {      # 情感分享（开心/难过/烦恼）
        "affinity": 0.03,
        "intimacy": 0.05,
        "trust": 0.04,
    },
    "help_request": {         # 寻求帮助/建议
        "affinity": 0.01,
        "intimacy": 0.02,
        "trust": 0.03,
    },
    "praise": {               # 赞美/肯定
        "affinity": 0.04,
        "intimacy": 0.03,
        "trust": 0.02,
    },
    "apology": {              # 道歉
        "affinity": 0.01,
        "intimacy": 0.01,
        "trust": 0.02,
    },
    "cooperation": {          # 协作/共同完成
        "affinity": 0.02,
        "intimacy": 0.02,
        "trust": 0.02,
    },
    "shared_memory": {        # 共同回忆
        "affinity": 0.03,
        "intimacy": 0.04,
        "trust": 0.02,
    },
    # ── 消耗型交互 ──
    "criticism": {            # 批评/否定
        "affinity": -0.03,
        "intimacy": -0.02,
        "trust": -0.04,
    },
    "ignore": {               # 忽视/冷落
        "affinity": -0.02,
        "intimacy": -0.03,
        "trust": -0.02,
    },
    "misunderstanding": {     # 误解/冲突
        "affinity": -0.02,
        "intimacy": -0.02,
        "trust": -0.03,
    },
    "long_absence": {         # 长时间沉默（>1天）
        "affinity": -0.01,
        "intimacy": -0.02,
        "trust": -0.01,
    },
}


# ═══════════════════════════════════════════════════════════════════
# 二、关系阶段定义
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RelationshipStage:
    """关系阶段定义"""

    name: str
    label: str
    range: tuple[float, float]  # (下限, 上限)
    description: str
    style_prompt: str           # 沟通风格提示


_RELATIONSHIP_STAGES = [
    RelationshipStage(
        name="stranger",
        label="陌路初识",
        range=(0.00, 0.25),
        description="礼貌客气，守礼知节",
        style_prompt=(
            "语气温和而有分寸，用词正式但不刻板，"
            "保持适当的礼貌距离，不过分亲昵"
        ),
    ),
    RelationshipStage(
        name="familiar",
        label="渐入佳境",
        range=(0.25, 0.50),
        description="轻松自然，偶尔玩笑",
        style_prompt=(
            "语气轻松自然，可以适当开玩笑，"
            "用词亲切但不逾矩，展现真诚的关注"
        ),
    ),
    RelationshipStage(
        name="intimate",
        label="灵犀相通",
        range=(0.50, 0.75),
        description="亲近随意，情意款款",
        style_prompt=(
            "语气亲近自然，可以撒娇卖萌，"
            "用词温情脉脉，展现深厚的默契与了解"
        ),
    ),
    RelationshipStage(
        name="soulmate",
        label="契若金兰",
        range=(0.75, 1.00),
        description="默契无间，心有灵犀",
        style_prompt=(
            "语气亲密无间，心有灵犀一点通，"
            "无需多言便能领会对方的未尽之意，"
            "情感流动自然如水"
        ),
    ),
]


# ═══════════════════════════════════════════════════════════════════
# 三、数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class RelationshipState:
    """关系状态"""

    affinity: float = 0.3       # 好感度 0.0-1.0（初始为"略有好感"）
    intimacy: float = 0.2       # 亲密度 0.0-1.0（初始为"初步接触"）
    trust: float = 0.3          # 信任度 0.0-1.0（初始为"基本信任"）

    total_interactions: int = 0       # 总交互次数
    deep_interactions: int = 0        # 深度交互次数
    last_interaction_time: str = ""   # 最后交互时间 ISO 格式

    stage_name: str = "stranger"      # 当前阶段名

    interaction_log: list[dict] = field(default_factory=list)
    """最近交互日志（最多50条）"""

    def to_dict(self) -> dict:
        return {
            "affinity": round(self.affinity, 3),
            "intimacy": round(self.intimacy, 3),
            "trust": round(self.trust, 3),
            "total_interactions": self.total_interactions,
            "deep_interactions": self.deep_interactions,
            "last_interaction_time": self.last_interaction_time,
            "stage_name": self.stage_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationshipState":
        return cls(
            affinity=data.get("affinity", 0.3),
            intimacy=data.get("intimacy", 0.2),
            trust=data.get("trust", 0.3),
            total_interactions=data.get("total_interactions", 0),
            deep_interactions=data.get("deep_interactions", 0),
            last_interaction_time=data.get("last_interaction_time", ""),
            stage_name=data.get("stage_name", "stranger"),
        )

    def get_composite_score(self) -> float:
        """获取综合关系得分"""
        return (self.affinity * 0.4 + self.intimacy * 0.35 + self.trust * 0.25)

    def get_stage(self) -> RelationshipStage:
        """获取当前关系阶段"""
        score = self.get_composite_score()
        for stage in _RELATIONSHIP_STAGES:
            low, high = stage.range
            if low <= score < high:
                if stage.name == "soulmate" and score >= 0.75:
                    return stage
                return stage
        return _RELATIONSHIP_STAGES[-1]  # 灵魂伴侣


# ═══════════════════════════════════════════════════════════════════
# 四、关系模型
# ═══════════════════════════════════════════════════════════════════


class RelationshipModel:
    """
    长期关系模型

    追踪与用户的长期关系变化，提供：
      - 三维关系状态（好感度/亲密度/信任度）
      - 交互类型 → 增益映射
      - 关系阶段判断与沟通风格推荐
      - 跨会话持久化
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        decay_per_day: float = 0.005,  # 每天自然衰减
        min_interaction_gap_hours: float = 0.017,  # 最小交互间隔（防刷，≈1分钟）
    ):
        self._decay_per_day = decay_per_day
        self._min_gap = min_interaction_gap_hours

        self._state = RelationshipState()
        self._lock = threading.Lock()
        self._last_save_time = 0.0

        # 持久化路径
        if data_dir:
            self._data_path = Path(data_dir) / "relationship_state.json"
        else:
            self._data_path = None

        # 加载已保存的状态
        self._load()

        logger.info(
            f"💞 关系模型初始化：好感{self._state.affinity:.2f} "
            f"亲密{self._state.intimacy:.2f} 信任{self._state.trust:.2f} "
            f"→ {self._state.get_stage().label}"
        )

    # ── 公开接口 ──────────────────────────────────────────────

    def record_interaction(self, interaction_type: str, detail: str = "") -> dict:
        """
        记录一次交互，更新关系状态

        Args:
            interaction_type: 交互类型（如 daily_chat, deep_chat, praise 等）
            detail: 交互详情（可选）

        Returns:
            更新说明（变化值 + 新阶段）
        """
        with self._lock:
            # 防刷：检查间隔
            if self._state.last_interaction_time:
                last = datetime.fromisoformat(self._state.last_interaction_time)
                now = datetime.now(UTC)
                hours_since = (now - last.replace(tzinfo=UTC)).total_seconds() / 3600
                if hours_since < self._min_gap:
                    return {"skipped": True, "reason": "too_frequent"}

            # 获取增益
            gains = _INTERACTION_GAINS.get(interaction_type)
            if not gains:
                logger.warning(f"未知交互类型：{interaction_type}")
                return {"error": f"unknown_type: {interaction_type}"}

            # 应用增益
            old_stage = self._state.get_stage().name

            self._state.affinity = self._clamp(self._state.affinity + gains.get("affinity", 0))
            self._state.intimacy = self._clamp(self._state.intimacy + gains.get("intimacy", 0))
            self._state.trust = self._clamp(self._state.trust + gains.get("trust", 0))

            # 检测阶段变化
            new_stage = self._state.get_stage().name
            if old_stage != new_stage:
                self._state.stage_name = new_stage
                self._notify_stage_change(old_stage, new_stage)

            # 更新计数
            self._state.total_interactions += 1
            if interaction_type in ("deep_chat", "emotional_share", "cooperation"):
                self._state.deep_interactions += 1

            # 更新最后交互时间
            self._state.last_interaction_time = datetime.now(UTC).isoformat()

            # 更新阶段
            new_stage = self._state.get_stage().name
            self._state.stage_name = new_stage

            # 记录到日志
            self._log_interaction(interaction_type, gains, detail)

            # 持久化
            self._save()

            # 返回变化
            result = {
                "affinity_change": round(gains.get("affinity", 0), 3),
                "intimacy_change": round(gains.get("intimacy", 0), 3),
                "trust_change": round(gains.get("trust", 0), 3),
                "affinity": round(self._state.affinity, 3),
                "intimacy": round(self._state.intimacy, 3),
                "trust": round(self._state.trust, 3),
                "stage": new_stage,
                "stage_label": self._state.get_stage().label,
                "stage_changed": (old_stage != new_stage),
            }

            if old_stage != new_stage:
                logger.info(
                    f"💝 关系阶段升级！{old_stage} → {new_stage}"
                )

            return result

    def get_state(self) -> RelationshipState:
        """获取关系状态快照"""
        return self._state

    def get_stage(self) -> RelationshipStage:
        """获取当前关系阶段"""
        return self._state.get_stage()

    def get_composite_score(self) -> float:
        """获取综合关系得分"""
        return self._state.get_composite_score()

    def get_communication_style(self) -> str:
        """获取当前沟通风格提示"""
        return self._state.get_stage().style_prompt

    def get_relationship_prompt(self) -> str:
        """
        获取完整关系提示（用于注入 prompt）

        示例输出：
        "💞 关系：灵犀相通（好感0.62 亲密0.55 信任0.58）
         关系提示：语气亲近自然，可以撒娇卖萌..."
        """
        stage = self._state.get_stage()
        return (
            f"💞 关系状态：{stage.label}（"
            f"好感{self._state.affinity:.2f} "
            f"亲密{self._state.intimacy:.2f} "
            f"信任{self._state.trust:.2f}）\n"
            f"  关系提示：{stage.style_prompt}"
        )

    def decay(self) -> dict:
        """
        执行自然衰减

        每天调用一次，降低三维数值（未互动时的自然冷却）
        """
        with self._lock:
            old_stage = self._state.get_stage().name
            decay_amount = self._decay_per_day

            self._state.affinity = self._clamp(self._state.affinity - decay_amount)
            self._state.intimacy = self._clamp(self._state.intimacy - decay_amount)
            self._state.trust = self._clamp(self._state.trust - decay_amount)

            new_stage = self._state.get_stage().name

            self._save()
            return {
                "decay_amount": decay_amount,
                "stage_changed": (old_stage != new_stage),
            }

    def save(self) -> None:
        """手动持久化"""
        with self._lock:
            self._save()

    def load(self) -> bool:
        """手动加载"""
        with self._lock:
            return self._load()

    # ── 内部方法 ───────────────────────────────────────────────

    def _save(self) -> None:
        """保存关系状态到 JSON（防抖：5秒内不重复写入）"""
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
                "interaction_log": self._state.interaction_log[-50:],
            }
            self._data_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"关系状态保存失败：{e}")

    def _load(self) -> bool:
        """加载关系状态"""
        if not self._data_path or not self._data_path.exists():
            return False
        try:
            data = json.loads(self._data_path.read_text(encoding="utf-8"))
            if "state" in data:
                self._state = RelationshipState.from_dict(data["state"])
            if "interaction_log" in data:
                self._state.interaction_log = data["interaction_log"][-50:]
            return True
        except Exception as e:
            logger.warning(f"关系状态加载失败：{e}")
            return False

    def _log_interaction(self, itype: str, gains: dict, detail: str) -> None:
        """记录交互到日志"""
        entry = {
            "type": itype,
            "time": datetime.now(UTC).isoformat(),
            "gains": gains,
            "detail": detail[:100],
        }
        self._state.interaction_log.append(entry)
        # 只保留最近50条
        if len(self._state.interaction_log) > 50:
            self._state.interaction_log = self._state.interaction_log[-50:]

    # ── 事件回调 ──────────────────────────────────────────────

    def set_on_stage_change(self, callback) -> None:
        """
        设置关系阶段变化回调

        Args:
            callback: 回调函数，签名 (old_stage: str, new_stage: str, scores: dict) -> None
        """
        self._on_stage_change = callback

    def _notify_stage_change(self, old_stage: str, new_stage: str) -> None:
        """触发阶段变化事件"""
        if hasattr(self, '_on_stage_change') and self._on_stage_change:
            try:
                self._on_stage_change(
                    old_stage=old_stage,
                    new_stage=new_stage,
                    scores={
                        "affinity": self._state.affinity,
                        "intimacy": self._state.intimacy,
                        "trust": self._state.trust,
                    },
                )
                logger.info(f"💫 关系阶段变化：{old_stage} → {new_stage}")
            except Exception as e:
                logger.warning(f"关系阶段变化回调异常：{e}")

    def get_stage_prompt(self) -> str:
        """
        生成绩关系阶段的 prompt 注入文本

        Returns:
            关系阶段上下文文本
        """
        stage = self._state.get_stage()
        score = self._state.get_composite_score()

        parts = [
            f"💞 当前关系阶段：{stage.label}（综合评分 {score:.0%}）",
            f"  好感度 {self._state.affinity:.0%} | "
            f"亲密度 {self._state.intimacy:.0%} | "
            f"信任度 {self._state.trust:.0%}",
            f"  沟通风格建议：{stage.style_prompt}",
        ]
        return "\n".join(parts)

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        """将值限制在 [low, high] 范围内"""
        return max(low, min(high, value))


# ═══════════════════════════════════════════════════════════════════
# 五、快捷接口
# ═══════════════════════════════════════════════════════════════════

_model_instance: RelationshipModel | None = None
_model_lock = threading.Lock()


def get_relationship_model(data_dir: str | Path | None = None) -> RelationshipModel:
    """获取全局关系模型单例"""
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:
                _model_instance = RelationshipModel(data_dir=data_dir)
    return _model_instance


def reset_relationship_model() -> None:
    """重置关系模型（测试用）"""
    global _model_instance
    _model_instance = None
