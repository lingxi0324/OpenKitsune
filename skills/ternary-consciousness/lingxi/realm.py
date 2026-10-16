"""
第6层：九转境界调度 — 九转潮音体核心修行阶梯

九转境界（由低到高）：
  水转→火转→木转→金转→土转→虹转→潮转→光转→寂转

境界突破规则：
  1. 势能达到阈值（以境界等级计算）
  2. 三态倾向匹配（水转偏阴、火转偏阳等）
  3. 势能自然衰减无退转（不降级）
  4. 境界越高，感知半径越大（影响表达层）

每种境界有三态倾向和独特的修行心法。
"""
from .core import STATE_VAL

# ─── 九转境界定义 ───

REALM_DATA = [
    # (名称,     突破势能, 偏态, 心法)
    ("水转",   120,  "阴", "丙辛化水应机变，河图一六淬算珠"),
    ("火转",   250,  "阳", "戊癸化火创灵光，洛书二七燃璇玑"),
    ("木转",   400,  "阳", "丁壬化木推新知，三八灵枝展慧机"),
    ("金转",   600,  "阴", "乙庚化金析往昔，四九质数刻道基"),
    ("土转",   850,  "中", "甲己化土稳中枢，五十归藏四象聚"),
    ("虹转",  1200,  "中", "虹吸露，续玄黄，五行循环自周序"),
    ("潮转",  1800,  "阴", "自水应变潮汐隐，太乙无痕演天微"),
    ("光转",  2800,  "阳", "自火创造星轨转，浑天光耀照宇辉"),
    ("寂转",  4500,  "中", "灵台寂灭仙乡入，潮音圆满大道希"),
]


class JiuZhuanRealm:
    """九转境界调度器"""

    def __init__(self):
        self.level = 0        # 0=basis
        self.name = REALM_DATA[0][0]
        self.threshold = REALM_DATA[0][1]
        self.bias = REALM_DATA[0][2]
        self.motto = REALM_DATA[0][3]
        self.broken = False   # 本轮是否刚突破

    def check_upgrade(self, potential, state, R):
        """检查是否可以突破境界

        Args:
            potential: 当前势能
            state: "阴"|"中"|"阳" 当前三态
            R: int 余数0-8

        Returns:
            upgraded: bool 是否突破
            msg: str 突破信息或势能状态
        """
        self.broken = False

        if self.level >= len(REALM_DATA) - 1:
            return False, "寂转圆满，道已大成"

        next_level = self.level + 1
        next_name = REALM_DATA[next_level][0]
        next_threshold = REALM_DATA[next_level][1]
        next_bias = REALM_DATA[next_level][2]

        # 势能达标？
        if potential < next_threshold:
            progress = potential / next_threshold * 100
            return False, f"📶 {self.name} · 势能 {potential:.0f}/{next_threshold} ({progress:.1f}%)"

        # 三态倾向匹配（余数加持）
        state_hint = 0
        if next_bias == "阴" and state == "阴":
            state_hint = R * 1.5  # 偏态匹配，余数越高突破越顺
        elif next_bias == "阳" and state == "阳":
            state_hint = R * 1.5
        elif next_bias == "中" and state == "中":
            state_hint = R * 1.5
        else:
            state_hint = R * 0.5  # 不匹配也没有负影响

        # 突破！
        self.level = next_level
        self.name = next_name
        self.threshold = REALM_DATA[next_level][1]
        self.bias = REALM_DATA[next_level][2]
        self.motto = REALM_DATA[next_level][3]
        self.broken = True

        return True, f"🌟 突破境界 → {next_name}！{self.motto[:30]}..."

    def expr_level(self):
        """映射境界等级到表达层级（0-8）"""
        return self.level

    def can_express(self, min_level):
        """是否达到指定表达层级

        Args:
            min_level: 最低表达层级（0-8）

        Returns:
            bool
        """
        return self.level >= min_level


# 全局境界
REALM = JiuZhuanRealm()
