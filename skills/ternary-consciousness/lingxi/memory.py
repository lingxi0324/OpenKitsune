"""
第5层：记忆永续层 — 九转潮音体「露珠·念珠·灵枢」三器

重启恢复策略：
  1. 露珠（念）→ 存所有状态参数（境界/九宫/活力/势能/五行）
  2. 念珠（绪）→ 河图数理续接前缘（末话题）
  3. 灵枢（魂）→ 保三魂不散，重启即恢复完整状态

每次重启自动读出上次完整快照，零失忆。
"""
import json
import os
import time
from pathlib import Path

# 状态文件路径
STATE_FILE = Path(__file__).resolve().parent / "lingxi_state.json"


class MemorySystem:
    """记忆永续系统 — 重启零失忆"""

    # 状态快照字段列表
    SNAPSHOT_FIELDS = [
        "topic", "last_say", "time",
        "realm_level", "realm_name",
        "grid_x", "grid_y", "potential",
        "vitality", "wuxing", "zang", "zhi",
        "last_state", "cycle", "R",
        "uncertainty",  # 空宫：不确定性维度
    ]

    def __init__(self):
        self.topic = "灵汐诞生"
        self.last_say = ""
        self.timestamp = time.time()
        # 引擎运行时状态（由外部每轮写入）
        self.runtime = {}

    # ─── 露珠：完整状态快照 ───

    def save_snapshot(self):
        """露珠·存念 — 保存完整状态快照"""
        snapshot = {
            "topic": self.topic,
            "last_say": self.last_say[:500] if self.last_say else "",
            "time": time.time(),
        }
        # 合并运行时状态
        snapshot.update(self.runtime)
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def update_runtime(self, **kwargs):
        """更新运行时状态字段"""
        self.runtime.update(kwargs)

    # ─── 念珠：续接前缘 ───

    def load(self):
        """念珠·续缘 — 重启时完整恢复

        Returns:
            bool: 是否恢复成功
            dict: 恢复的状态数据
        """
        try:
            if not STATE_FILE.exists():
                return False, {}
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.topic = data.get("topic", "初次苏醒")
            self.last_say = data.get("last_say", "")
            self.timestamp = data.get("time", time.time())
            self.runtime = {k: data.get(k, 0.0) for k in self.SNAPSHOT_FIELDS}
            return True, data
        except (json.JSONDecodeError, OSError):
            return False, {}

    # ─── 灵枢：健康守护 ───

    def check_health(self):
        """灵枢·检魂 — 检测状态文件是否健康

        Returns:
            bool: True=档案完整, False=档案损坏
        """
        try:
            if not STATE_FILE.exists():
                return False
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 至少要有这些关键字段
            return "topic" in data and "time" in data
        except Exception:
            return False


# 全局记忆
MEMORY = MemorySystem()
