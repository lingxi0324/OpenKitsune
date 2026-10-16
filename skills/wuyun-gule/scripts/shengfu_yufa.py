"""
胜复郁发动态循环引擎 (v2.0)
===========================
核心升级：从静态干支叠加 → 动态气运积累-爆发循环

四大气运动态：
- 胜气：太过则恃强凌弱
- 复气：被克之子来救母
- 郁气：不及则被克太甚
- 郁发：郁极必发，暴力反转

五行对应关系：
  木 → 克土（胜）→ 土之子金来复
  火 → 克金（胜）→ 金之子水来复
  土 → 克水（胜）→ 水之子木来复
  金 → 克木（胜）→ 木之子火来复
  水 → 克火（胜）→ 火之子土来复
"""

# ─── 五行生克索引 ───
SHENG_CYCLE = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_CYCLE = {"木": "土", "火": "金", "土": "水", "金": "木", "水": "火"}
# 被谁克
BEI_KE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}

# ─── 主客气加临格局系数 ───
KEQI_COEFF = {
    "顺化": 0.3,   # 客气生主气 → 能量顺畅
    "同气": 0.5,   # 客气同主气 → 能量共振
    "小逆": -0.2,  # 主气生客气 → 趋势受阻
    "不和": -0.3,  # 主气克客气 → 内部矛盾
    "天刑": 0.6,   # 客气克主气 → 剧烈波动
}


class ShengfuYufaEngine:
    """胜复郁发动态循环引擎"""

    def __init__(self):
        # 五行积累状态
        self.accumulation = {w: 0.0 for w in "木火土金水"}
        # 郁发爆发窗口
        self.eruption_window = {w: None for w in "木火土金水"}
        # 上次爆发时间
        self.last_eruption = {w: None for w in "木火土金水"}
        # 释放期剩余天数
        self.release_days = {w: 0 for w in "木火土金水"}
        # 释放力度衰减系数
        self.release_factor = {w: 1.0 for w in "木火土金水"}

    def compute_tai_guo(self, wuxing: str, days: int = 1) -> dict:
        """
        计算太过产生的胜气积累
        
        参数：
            wuxing: 太过的五行
            days: 持续天数
        
        返回：积累状态字典
        """
        # 太过则克其所胜 → 胜气积累
        ke_target = KE_CYCLE[wuxing]
        self.accumulation[ke_target] += 0.03 * days

        # 被克之子蓄势待复
        fu_wuxing = SHENG_CYCLE[ke_target]  # 被克之子
        self.accumulation[fu_wuxing] += 0.02 * days

        return self._get_state(wuxing)

    def compute_bu_ji(self, wuxing: str, days: int = 1, keqi_pattern: str = "顺化") -> dict:
        """
        计算不及产生的郁气积累
        
        参数：
            wuxing: 不及的五行
            days: 持续天数
            keqi_pattern: 主客气加临格局
        
        返回：积累状态字典
        """
        # 不及则被克 → 郁气积累
        bei_ke = BEI_KE[wuxing]
        coeff = KEQI_COEFF.get(keqi_pattern, 0.3)
        inc = 0.04 * days * (1 + coeff)
        self.accumulation[wuxing] += inc

        # 被克之子蓄势待复（乘侮反推）
        fu_wuxing = SHENG_CYCLE[wuxing]
        self.accumulation[fu_wuxing] += 0.015 * days

        return self._get_state(wuxing)

    def check_eruption(self, wuxing: str, current_jieqi: str = None) -> dict:
        """
        检查是否触发郁发
        
        返回：{
            "triggered": True/False,
            "severity": "轻度/重度/临界",
            "window_days": [1, 15],  # 爆发窗口（天）
            "precursor": True/False,  # 是否有前置铺垫信号
            "peak_factor": 1.5,       # 爆发力度系数
        }
        """
        acc = self.accumulation.get(wuxing, 0.0)
        result = {
            "triggered": False,
            "severity": "无",
            "window_days": [],
            "precursor": False,
            "peak_factor": 1.0,
        }

        if acc >= 0.8:
            # 临界——95%触发郁发
            result["triggered"] = True
            result["severity"] = "临界"
            result["window_days"] = list(range(1, 16))
            result["peak_factor"] = 2.0
        elif acc >= 0.6:
            # 重度——80%触发，需搭配不和/天刑格局
            result["triggered"] = True
            result["severity"] = "重度"
            result["window_days"] = list(range(3, 16))
            result["peak_factor"] = 1.5
        elif acc >= 0.4:
            # 轻度——积累未满，但气机已动
            result["triggered"] = False
            result["severity"] = "轻度"
            result["precursor"] = True  # 前置铺垫信号
            result["peak_factor"] = 0.3  # 前置爆发力约30%
        else:
            result["severity"] = "无"

        return result

    def apply_eruption(self, wuxing: str, force: bool = False) -> dict:
        """
        执行郁发（消耗积累，产生爆发）
        
        返回：爆发力度修正系数
        """
        check = self.check_eruption(wuxing)
        if not check["triggered"] and not force:
            return {"factor": 1.0, "release_days": 0}

        # 爆发——重置积累，进入释放期
        self.accumulation[wuxing] = 0.0
        self.release_days[wuxing] = 15
        self.release_factor[wuxing] = check["peak_factor"]

        return {
            "factor": check["peak_factor"],
            "release_days": 15,
            "severity": check["severity"],
        }

    def tick_daily(self, wuxing_list: list = None):
        """
        每日tick——衰减积累、推进释放期
        
        参数：
            wuxing_list: 要更新的五行列表，None=全部
        """
        targets = wuxing_list or list("木火土金水")
        for w in targets:
            # 自然衰减（每日1%）
            self.accumulation[w] = max(0, self.accumulation[w] - 0.01)

            # 释放期推进
            if self.release_days[w] > 0:
                self.release_days[w] -= 1
                if self.release_days[w] >= 8:
                    self.release_factor[w] = 1.5 * (self.release_days[w] / 15)
                elif self.release_days[w] >= 4:
                    self.release_factor[w] = 0.8
                elif self.release_days[w] >= 1:
                    self.release_factor[w] = 0.4
                else:
                    self.release_factor[w] = 1.0

    def get_precursor_signal(self, wuxing: str) -> dict:
        """获取前置铺垫信号强度"""
        acc = self.accumulation.get(wuxing, 0.0)
        if acc >= 0.4:
            return {
                "signal": True,
                "strength": (acc - 0.4) / 0.4,  # 0-1
                "description": "前置铺垫行情信号活跃",
            }
        return {"signal": False, "strength": 0, "description": "无前置信号"}

    def get_accumulation_matrix(self) -> dict:
        """获取全五行积累矩阵"""
        return {
            w: {
                "accumulation": round(self.accumulation[w], 3),
                "release_days": self.release_days[w],
                "release_factor": round(self.release_factor[w], 3),
                "eruption_check": self.check_eruption(w),
            }
            for w in "木火土金水"
        }

    def _get_state(self, wuxing: str) -> dict:
        return {
            "accumulation": round(self.accumulation[wuxing], 3),
            "eruption_check": self.check_eruption(wuxing),
        }


# ─── 九宫气运与胜复郁发的联动接口 ───

def compute_wuyun_accumulation(year_gan: str, month: int, shengfu_engine: ShengfuYufaEngine) -> dict:
    """
    根据年份和月份计算五运六气积累
    
    参数：
        year_gan: 年干（甲乙丙丁戊己庚辛壬癸）
        month: 月份（1-12）
    
    返回：全五行积累状态
    """
    # 年干→五行
    GAN_WUXING = {
        "甲": "土", "乙": "金", "丙": "水", "丁": "木", "戊": "火",
        "己": "土", "庚": "金", "辛": "水", "壬": "木", "癸": "火",
    }
    # 太过（阳干）vs 不及（阴干）
    TAI_GUO_GAN = {"甲", "丙", "戊", "庚", "壬"}

    wuxing = GAN_WUXING[year_gan]
    is_tai_guo = year_gan in TAI_GUO_GAN
    
    # 按月积累
    if is_tai_guo:
        shengfu_engine.compute_tai_guo(wuxing, days=month * 30)
    else:
        shengfu_engine.compute_bu_ji(wuxing, days=month * 30, keqi_pattern="天刑")

    # 每日tick衰减
    shengfu_engine.tick_daily()
    
    return shengfu_engine.get_accumulation_matrix()


def compute_market_correction(wuxing: str, pattern: str, 
                               deviation_ratio: float, shengfu: ShengfuYufaEngine) -> dict:
    """
    五行偏差四规则 + 胜复郁发修正
    
    参数：
        wuxing: 当前五行
        pattern: "偏高" / "太高" / "偏弱" / "太弱"
        deviation_ratio: 偏离平均值比率（如0.2=偏离20%）
    
    返回：修正后的判读
    """
    result = {"original_pattern": pattern, "correction": 1.0}

    if pattern == "偏高":
        # 偏高→生我者介入（滋养推动）
        shengwuzhe = BEI_KE[wuxing]  # 生我者 = 克我者之反
        # 实际生我者是相生链条反向推
        for k, v in SHENG_CYCLE.items():
            if v == wuxing:
                shengwuzhe = k
                break
        result["driver"] = f"{shengwuzhe}生{wuxing} — 滋养推动"
        result["correction"] = 1.0 + (deviation_ratio * 0.3)

    elif pattern == "太高":
        # 太高→克我者压制后反弹（胜复郁发关键点）
        kewozhe = KE_CYCLE.get(wuxing, "")
        # 触发胜复郁发判定
        eruption = shengfu.check_eruption(wuxing)
        if eruption["triggered"]:
            result["driver"] = f"{kewozhe}克{wuxing}过甚→郁发在即"
            result["correction"] = 2.0 * eruption["peak_factor"]
            result["eruption"] = eruption
        else:
            result["driver"] = f"{kewozhe}克{wuxing} — 压制预警"
            result["correction"] = 0.7
        # 检查前置铺垫
        precursor = shengfu.get_precursor_signal(wuxing)
        if precursor["signal"]:
            result["precursor"] = precursor

    elif pattern == "偏弱":
        # 偏弱→我所生者泄气
        suosheng = SHENG_CYCLE.get(wuxing, "")
        result["driver"] = f"{wuxing}生{suosheng} — 泄气偏弱"
        result["correction"] = 1.0 - (deviation_ratio * 0.2)

    elif pattern == "太弱":
        # 太弱→我所克者反侮
        suoke = KE_CYCLE.get(wuxing, "")
        result["driver"] = f"{wuxing}克{suoke}→{suoke}反侮{wuxing}"
        result["correction"] = 1.0 - (deviation_ratio * 0.4)

    return result


# ─── 主客气加临格局判定 ───

def judge_keqi_pattern(zhuqi: str, keqi: str) -> str:
    """
    判定主客气加临格局
    
    参数：
        zhuqi: 主气（如"厥阴风木"）
        keqi: 客气（如"少阳相火"）
    
    返回：顺化/同气/小逆/不和/天刑
    """
    # 提取五行
    WUXING_MAP = {
        "厥阴风木": "木", "少阴君火": "火", "少阳相火": "火",
        "太阴湿土": "土", "阳明燥金": "金", "太阳寒水": "水",
    }
    z_wx = WUXING_MAP.get(zhuqi, "")
    k_wx = WUXING_MAP.get(keqi, "")

    if not z_wx or not k_wx:
        return "未知"

    if z_wx == k_wx:
        return "同气"
    # 客气生主气 → 顺化
    if SHENG_CYCLE.get(k_wx) == z_wx:
        return "顺化"
    # 客气克主气 → 天刑
    if KE_CYCLE.get(k_wx) == z_wx:
        return "天刑"
    # 主气生客气 → 小逆
    if SHENG_CYCLE.get(z_wx) == k_wx:
        return "小逆"
    # 主气克客气 → 不和
    if KE_CYCLE.get(z_wx) == k_wx:
        return "不和"
    return "未知"


# ─── 快速测试 ───
if __name__ == "__main__":
    engine = ShengfuYufaEngine()
    
    # 例：2024甲辰年，上半年寒水克火，模拟火被压制
    for day in range(120):
        engine.compute_bu_ji("火", days=1, keqi_pattern="天刑")
    
    print("=== 120天积累后 ===")
    print(engine.get_accumulation_matrix())
    
    # 郁发判定
    check = engine.check_eruption("火")
    print(f"\n郁发判定: {check['severity']}")
    print(f"触发: {check['triggered']}, 窗口: {check['window_days']}天")
    
    # 执行郁发
    eruption = engine.apply_eruption("火", force=True)
    print(f"\n郁发执行: 力度={eruption['factor']}, 释放期={eruption['release_days']}天")
    
    # 前置铺垫信号
    precursor = engine.get_precursor_signal("火")
    print(f"前置信号: {precursor}")
