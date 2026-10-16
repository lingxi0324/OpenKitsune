"""
九维引擎升级模块 v2.1
新增方法：暗干穿透、奇门演卦、克应体系、四层奇门融合、混合百神优先级、三诈五假、门迫量化、中五宫寄用

用法：在 nine_dim_engine.py 末尾 import 此模块即可自动注入升级方法
"""

from typing import Optional, Dict, List, Tuple, Any
import math

# ═══════════════════════════════════════════════════════════════
# 升级方法注入
# ═══════════════════════════════════════════════════════════════

def _calc_angian(self, meta):
    """暗干穿透（法窍卷六·人盘暗干）
    
    读取明盘之外隐性天干信息：
    - 时干暗干：时柱天干隐入宫位的关联符号
    - 值使暗干：值使门转宫时携带的天干
    - 日干暗干：日干所在宫位的隐性关联
    
    Returns:
        dict: {暗干类型: {宫位: 天干, 解读: str}}
    """
    result = {
        "shigan_angian": {},     # 时干暗干
        "zhishi_angian": {},     # 值使暗干
        "riger_angian": {},      # 日干暗干
        "summary": ""           # 综合解读
    }
    
    if not hasattr(meta, 'tiangan_layout'):
        return result
    
    # 1. 获取时干
    shigan = getattr(meta, 'shigan', None) or getattr(meta, 'hour_gan', None)
    if shigan:
        # 时干所在宫位
        for palace, gan in (meta.tiangan_layout or {}).items():
            if gan == shigan:
                # 该宫位的值使门所带暗干
                men_at_palace = (meta.men_layout or {}).get(palace, "")
                zhiming = getattr(meta, 'zhiming', None) or getattr(meta, 'zhishi_men', None)
                
                result["shigan_angian"][palace] = {
                    "minggan": shigan,
                    "men": men_at_palace,
                    "暗干判": f"时干{shigan}在{palace}宫，{men_at_palace}门" 
                }
    
    # 2. 值使暗干
    zhishi = getattr(meta, 'zhiming', None) or getattr(meta, 'zhishi_men', None)
    if zhishi:
        for palace, men in (meta.men_layout or {}).items():
            if men == zhishi:
                gan_at_palace = (meta.tiangan_layout or {}).get(palace, "")
                result["zhishi_angian"][palace] = {
                    "zhishi_men": zhishi,
                    "angian_gan": gan_at_palace,
                    "暗干判": f"值使{zhishi}在{palace}宫，暗干{gan_at_palace}"
                }
    
    # 3. 综合解读拼装
    parts = []
    if result["shigan_angian"]:
        parts.append(f"时干暗干：{len(result['shigan_angian'])}处")
    if result["zhishi_angian"]:
        parts.append(f"值使暗干：{len(result['zhishi_angian'])}处")
    if parts:
        result["summary"] = "明盘读表层→暗干读隐藏→格谱读格局；" + " | ".join(parts)
    else:
        result["summary"] = "无暗干信息或信息不足"
    
    return result


def _calc_yagua(self, meta):
    """奇门演卦（旨归符使演卦法）
    
    值符+值使两宫天干合为八卦，本宫地支为动爻。
    
    Returns:
        dict: {卦名, 动爻, 变卦, 六亲解读, 综合判}
    """
    result = {
        "卦名": "", "动爻": "", "变卦": "",
        "世应判": "", "综合判": ""
    }
    
    if not hasattr(meta, 'tiangan_layout') or not hasattr(meta, 'xing_layout'):
        return result
    
    # 值符星及其落宫
    zhifu = getattr(meta, 'zhifu_xing', None)
    zhishi = getattr(meta, 'zhiming', None) or getattr(meta, 'zhishi_men', None)
    
    if not zhifu or not zhishi:
        zhifu_stars = {"天蓬":"坎1","天芮":"坤2","天冲":"震3","天辅":"巽4",
                       "天禽":"中5","天心":"乾6","天柱":"兑7","天任":"艮8","天英":"离9"}
        zhifu = getattr(meta, 'zhifu_xing', None)
        if zhifu and zhifu in zhifu_stars:
            zhifu_palace = zhifu_stars[zhifu]
        else:
            return result
    
    # 查值符值使所在宫的天干
    zhifu_palace = ""
    zhishi_palace = ""
    
    for palace, star in (meta.xing_layout or {}).items():
        if star == zhifu:
            zhifu_palace = palace
    for palace, men in (meta.men_layout or {}).items():
        if men == zhishi:
            zhishi_palace = palace
    
    if not zhifu_palace or not zhishi_palace:
        return result
    
    f_tian = (meta.tiangan_layout or {}).get(zhifu_palace, "")
    s_tian = (meta.tiangan_layout or {}).get(zhishi_palace, "")
    
    if not f_tian or not s_tian:
        return result
    
    # 天干转先天卦数
    gan_to_xian = {"甲":1,"乙":8,"丙":7,"丁":6,"戊":5,"己":4,"庚":3,"辛":2,"壬":1,"癸":8}
    xian_to_gua = {
        (1,8): "否", (8,1): "泰", 
        (1,7): "讼", (7,1): "需",
        (1,6): "遁", (6,1): "大壮",
        (1,5): "姤", (5,1): "复",
        (1,4): "同人", (4,1): "师",
        (1,3): "履", (3,1): "谦",
        (1,2): "小畜", (2,1): "豫",
        (8,7): "晋", (7,8): "明夷",
        (8,6): "萃", (6,8): "升",
        (8,5): "观", (5,8): "临",
        (8,4): "比", (4,8): "剥",
        (8,3): "大有", (3,8): "蹇",
        (8,2): "夬", (2,8): "谦",
        (7,6): "未济", (6,7): "既济",
        (7,5): "鼎", (5,7): "屯",
        (7,4): "旅", (4,7): "节",
        (7,3): "大过", (3,7): "贲",
        (7,2): "革", (2,7): "蒙",
        (6,5): "蛊", (5,6): "随",
        (6,4): "井", (4,6): "需",
        (6,3): "解", (3,6): "睽",
        (6,2): "困", (2,6): "咸",
        (5,4): "咸", (4,5): "损",
        (5,3): "恒", (3,5): "益",
        (5,2): "大畜", (2,5): "无妄",
        (4,3): "丰", (3,4): "涣",
        (4,2): "噬嗑", (2,4): "井",
        (3,2): "中孚", (2,3): "归妹"
    }
    
    f_num = gan_to_xian.get(f_tian, 0)
    s_num = gan_to_xian.get(s_tian, 0)
    
    gua_name = xian_to_gua.get((f_num, s_num), "")
    if not gua_name:
        gua_name = xian_to_gua.get((s_num, f_num), "")
    
    result["卦名"] = gua_name
    
    # 动爻：值符本宫地支
    palace_dizhi = {"坎":"子","坤":"未","震":"卯","巽":"辰","乾":"戌","兑":"酉","艮":"丑","离":"午","中":"辰"}
    dong_yao = palace_dizhi.get(zhifu_palace, "初")
    result["动爻"] = dong_yao
    
    result["综合判"] = f"符使演卦得《{gua_name}》，动爻{dong_yao}"
    
    return result


def _calc_keying_system(self, meta):
    """克应体系（秘要+元灵经+演义三层）
    
    星克应+门克应+时克应 → 盘外征兆校验
    
    Returns:
        dict: {星克应, 门克应, 综合判}
    """
    result = {"星克应": {}, "门克应": {}, "时克应": {}, "综合判": ""}
    
    # 九星克应（简表）
    star_keying = {
        "天蓬": {"子": "鸡鸣犬吠宿鸟闹", "午": "童子文人送纸束"},
        "天芮": {"子": "怀孕女来紫衣人", "午": "缺唇白人来石物"},
        "天冲": {"子": "大风四起火从东", "午": "独马青鸟贵人至"},
        "天辅": {"子": "公吏铁器艺人至", "午": "僧道屠牛女人斗"},
        "天心": {"子": "云开鸡唱僧道来", "午": "黄白二物赶羊来"},
    }
    
    hour = getattr(meta, 'hour', None) or getattr(meta, 'hour_dizhi', "子")
    hour_dz = hour if len(hour) <= 2 else "子"
    
    if hasattr(meta, 'xing_layout'):
        for palace, star in (meta.xing_layout or {}).items():
            if star in star_keying and hour_dz in star_keying[star]:
                result["星克应"][star] = star_keying[star][hour_dz]
    
    parts = []
    if result["星克应"]:
        parts.append(f"星克{len(result['星克应'])}处")
    result["综合判"] = " | ".join(parts) if parts else "克应信息不足"
    
    return result

def _calc_four_layer(self, year, month, day, hour):
    """四层奇门融合（年/月/日/时）
    
    四层叠加：年干→大运底色，月干→当年重点，日干→当下事件，时干→事体本质
    
    Returns:
        dict: {年层, 月层, 日层, 时层, 四层综合判}
    """
    result = {"年层": {}, "月层": {}, "日层": {}, "时层": {}, "四层综合判": ""}
    
    # 年家奇门：年干支定局
    year_gan = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"][(year - 4) % 10]
    month_gan = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"][(month + 1) % 10]
    day_gan = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"][(day + 3) % 10]
    hour_gan = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"][((hour + 1) // 2) % 10]
    
    # 查四天干在盘中的落宫
    if hasattr(self, 'meta') and hasattr(self.meta, 'tiangan_layout'):
        layout = self.meta.tiangan_layout
    else:
        meta = getattr(self, '_last_meta', None)
        if not meta or not hasattr(meta, 'tiangan_layout'):
            layout = {}
        else:
            layout = meta.tiangan_layout
    
    for palace, gan in (layout or {}).items():
        if gan == year_gan:
            result["年层"] = {"天干": year_gan, "落宫": palace, "解读": f"年干{year_gan}在{palace}宫→大运底色"}
        if gan == month_gan:
            result["月层"] = {"天干": month_gan, "落宫": palace, "解读": f"月干{month_gan}在{palace}宫→当年重点"}
        if gan == day_gan:
            result["日层"] = {"天干": day_gan, "落宫": palace, "解读": f"日干{day_gan}在{palace}宫→当下事件"}
        if gan == hour_gan:
            result["时层"] = {"天干": hour_gan, "落宫": palace, "解读": f"时干{hour_gan}在{palace}宫→事体本质"}
    
    # 四层综合
    layers = [result["年层"], result["月层"], result["日层"], result["时层"]]
    active = [l for l in layers if l]
    palaces = [l.get("落宫","") for l in active if l.get("落宫")]
    
    if len(set(palaces)) <= 2:
        result["四层综合判"] = f"四层同源（{len(set(palaces))}处汇聚）→结论可靠性高"
    else:
        result["四层综合判"] = f"四层分散（{len(set(palaces))}处不同）→需混合百神优先级裁决"
    
    return result


def _calc_baishen_priority(self, meta):
    """混合百神优先级（宝鉴）
    
    四层嵌套：值符(0.4)→直使(0.3)→九星(0.2)→八神(0.1)
    符号冲突时按权重裁决
    
    Returns:
        dict: {优先级链, 冲突裁决, 综合判}
    """
    result = {"优先级链": [], "冲突裁决": "", "综合判": ""}
    
    # 值符→级别①
    zhifu = getattr(meta, 'zhifu_xing', None)
    zhifu_nature = getattr(meta, 'zhifu_nature', None) or "平"
    
    # 值使→级别②
    zhishi = getattr(meta, 'zhiming', None) or getattr(meta, 'zhishi_men', None)
    zhishi_nature = getattr(meta, 'zhishi_nature', None) or "平"
    
    # 九星→级别③
    star_natures = []
    if hasattr(meta, 'xing_wangshuai'):
        for star, status in (meta.xing_wangshuai or {}).items():
            star_natures.append(f"{star}({status})")
    
    # 八神→级别④
    shen_overall = getattr(meta, 'shen_overall_nature', "平")
    
    result["优先级链"] = [
        f"①值符{zhifu}(权重0.4)",
        f"②直使{zhishi}(权重0.3)",
        f"③九星({'; '.join(star_natures[:3])})(权重0.2)",
        f"④八神({shen_overall})(权重0.1)"
    ]
    
    natures = [zhifu_nature, zhishi_nature]
    if "凶" in natures and "吉" in natures:
        result["冲突裁决"] = "符使冲突→以值符①定性为准，直使②为过程性补充"
    elif "凶" in natures:
        result["冲突裁决"] = "值符为凶→整体偏凶，参九星八神修正"
    elif "吉" in natures:
        result["冲突裁决"] = "值符为吉→整体偏吉"
    else:
        result["冲突裁决"] = "中性→参九星旺衰断"
    
    result["综合判"] = result["冲突裁决"]
    return result


def _calc_sanzha_wujia(self, meta):
    """三诈五假·行动策略建议（演义）
    
    Returns:
        dict: {诈格, 假格, 行动建议}
    """
    result = {"诈格": "", "假格": "", "行动建议": ""}
    
    # 检查三奇+三门+特定八神
    sanqi_gans = ["乙","丙","丁"]
    sanmen_gates = ["开","休","生"]
    special_shens = {"太阴": "真诈", "九地": "重诈", "六合": "休诈"}
    
    has_sanqi = False
    has_sanmen = False
    shen_type = ""
    
    if hasattr(meta, 'tiangan_layout'):
        for palace, gan in (meta.tiangan_layout or {}).items():
            if gan in sanqi_gans:
                has_sanqi = True
                break
    
    if hasattr(meta, 'men_layout'):
        for palace, gate in (meta.men_layout or {}).items():
            if gate in sanmen_gates:
                has_sanmen = True
                break
    
    if hasattr(meta, 'shen_layout'):
        for palace, shen in (meta.shen_layout or {}).items():
            if shen in special_shens:
                shen_type = special_shens[shen]
    
    if has_sanqi and has_sanmen and shen_type:
        result["诈格"] = f"{shen_type}（三奇+三门+{shen_type}）"
    
    # 五假
    wujia_map = {
        "景门": ("九天", "天假", "进谒干求"),
        "杜门": ("九地", "地假", "潜伏隐伏"),
        "伤门": ("九地", "神假", "埋葬"),
        "惊门": ("九天", "人假", "捕逃亡"),
        "死门": ("九地", "鬼假", "超亡荐度"),
    }
    
    if hasattr(meta, 'men_layout'):
        du_men_gans = ["丁","己","癸"]
        for palace, gate in (meta.men_layout or {}).items():
            gate_clean = gate.replace("门","")
            if gate_clean in wujia_map:
                shen_needed, jia_name, action = wujia_map[gate_clean]
                if hasattr(meta, 'shen_layout'):
                    for sp, sv in (meta.shen_layout or {}).items():
                        if sv == shen_needed:
                            # 检查有丁己癸在盘
                            has_du_gan = False
                            if hasattr(meta, 'tiangan_layout'):
                                for gp, gv in (meta.tiangan_layout or {}).items():
                                    if gv in du_men_gans:
                                        has_du_gan = True
                                        break
                            if has_du_gan or gate_clean not in ["杜","伤","死"]:
                                result["假格"] = f"{jia_name}（{gate}门+{shen_needed}→{action}）"
    
    advices = []
    if result["诈格"]:
        advices.append(f"诈格{result['诈格']}→主动策略推荐")
    if result["假格"]:
        advices.append(f"假格{result['假格']}→特定策略推荐")
    result["行动建议"] = " | ".join(advices) if advices else "无三诈五假→常规应对"
    
    return result


def _calc_menpo_quantified(self, meta):
    """门迫量化体系（符应经）
    
    宫克门=门迫(吉门被迫吉事减半)
    门克宫=宫迫(凶门受迫凶上加凶)
    门宫比和=同五行(吉加吉凶加凶)
    
    Returns:
        dict: {门迫表, 量化判}
    """
    result = {"门迫表": {}, "量化判": ""}
    
    wx_map = {"坎":"水","坤":"土","震":"木","巽":"木","中":"土","乾":"金","兑":"金","艮":"土","离":"火"}
    gate_wx = {"休":"水","生":"土","伤":"木","杜":"木","景":"火","死":"土","惊":"金","开":"金"}
    gate_rank = {"休":"吉","生":"吉","伤":"凶","杜":"平","景":"平","死":"凶","惊":"凶","开":"吉"}
    
    menpo_data = []
    if hasattr(meta, 'men_layout'):
        for palace, gate in (meta.men_layout or {}).items():
            gate_name = gate.replace("门","")
            p_wx = wx_map.get(palace, "")
            g_wx = gate_wx.get(gate_name, "")
            if not p_wx or not g_wx:
                continue
            
            # 五行生克
            shengke_map = {
                ("水","水"): "比和", ("火","火"): "比和", ("木","木"): "比和",
                ("金","金"): "比和", ("土","土"): "比和",
                ("水","火"): "宫克门", ("水","金"): "门克宫",
                ("火","土"): "宫克门", ("火","木"): "门克宫",
                ("木","土"): "宫克门", ("木","火"): "门克宫",
                ("金","木"): "宫克门", ("金","水"): "门克宫",
                ("土","水"): "宫克门", ("土","金"): "门克宫",
            }
            # 逆查
            relation = ""
            for (a,b),v in shengke_map.items():
                if a==p_wx and b==g_wx:
                    relation = v
                    break
            
            severity = 0.0
            gate_type = gate_rank.get(gate_name, "平")
            if relation == "宫克门":
                severity = -0.4 if gate_type == "吉" else -0.2
            elif relation == "门克宫":
                severity = -0.5 if gate_type == "凶" else -0.2
            elif relation == "比和":
                severity = 0.1 if gate_type == "吉" else -0.2
            
            menpo_data.append({
                "宫位": palace, "门": gate_name,
                "宮五行": p_wx, "门五行": g_wx,
                "关系": relation,
                "吉凶": gate_type,
                "量化影响": round(severity, 2)
            })
            result["门迫表"][palace] = f"{gate_name}门⊥{p_wx}→{relation}({severity:+.2f})"
    
    total_impact = sum(d["量化影响"] for d in menpo_data)
    result["量化判"] = f"门迫叠加影响{total_impact:+.2f}，{'偏利' if total_impact > 0 else '偏弊'}"
    
    return result


def _calc_zhongwu_ji(self, meta, season="default"):
    """中五宫寄用新法（阴符经释秘·霍斐然）
    
    season: 'default'|'spring'|'summer'|'autumn'|'winter'
    
    Returns:
        dict: {寄法, 所寄之宫, 所借之门, 说明}
    """
    dun_type = getattr(meta, 'dun_type', "阳遁")
    
    # 默认寄法
    result = {"寄法": "", "寄宫": "", "借门": "", "说明": ""}
    
    if season == "default":
        if "阳" in str(dun_type):
            result["寄法"] = "阳遁寄坤"
            result["寄宫"] = "坤2"
            result["借门"] = "死门"
        else:
            result["寄法"] = "阴遁寄艮"
            result["寄宫"] = "艮8"
            result["借门"] = "生门"
    elif season == "spring":
        result["寄法"] = "四季寄法·春"
        result["寄宫"] = "震3"
        result["借门"] = "伤门"
    elif season == "summer":
        result["寄法"] = "四季寄法·夏"
        result["寄宫"] = "离9"
        result["借门"] = "景门"
    elif season == "autumn":
        result["寄法"] = "四季寄法·秋"
        result["寄宫"] = "兑7"
        result["借门"] = "惊门"
    elif season == "winter":
        result["寄法"] = "四季寄法·冬"
        result["寄宫"] = "坎1"
        result["借门"] = "休门"
    
    result["说明"] = f"{result['寄法']}：中宫借{result['寄宫']}{result['借门']}"
    return result


def _calc_enhanced_rolling(self, frames, four_layer_mode=True):
    """时空滚动推演法·增强版
    
    升级：在原有basic rolling基础上加入四层奇门融合和应期三法
    
    Args:
        frames: 多帧数据 [{time, data}, ...]
        four_layer_mode: 是否启用四层奇门
    
    Returns:
        dict: {滚动链, 四层穿插, 应期判, 结论}
    """
    result = {"滚动链": [], "四层穿插": {}, "应期判": "", "结论": ""}
    
    if not frames or len(frames) < 2:
        return result
    
    # 1. 基本滚动链
    for i, frame in enumerate(frames):
        time_str = frame.get("time", f"帧{i+1}")
        data = frame.get("data", {})
        result["滚动链"].append({"帧": i+1, "时间": time_str, "摘要": str(data)[:80]})
    
    # 2. 四层穿插（如果启用）
    if four_layer_mode and len(frames) >= 3:
        # 用首帧做年家，中帧做月家，末帧做时家
        first = frames[0]
        last = frames[-1]
        
        # 提取年
        import re
        year_match = re.search(r'(\d{4})', str(first.get("time","")))
        month_match = re.search(r'\d{4}-(\d{2})', str(first.get("time","")))
        day_match = re.search(r'\d{4}-\d{2}-(\d{2})', str(last.get("time","")))
        hour_match = re.search(r'(\d{2}):', str(last.get("time","")))
        
        year = int(year_match.group(1)) if year_match else 2026
        month = int(month_match.group(1)) if month_match else 6
        day = int(day_match.group(1)) if day_match else 13
        hour = int(hour_match.group(1)) if hour_match else 12
        
        four_layer = _calc_four_layer(self, year, month, day, hour)
        result["四层穿插"] = four_layer
    
    # 3. 应期判断
    result["应期判"] = "多帧滚动→关键拐点帧为应期所在，结合前值符所在宫位出空或逢合之月日断"
    
    return result


# ═══════════════════════════════════════════════════════════════
# 注入代码
# ═══════════════════════════════════════════════════════════════

def inject_upgrades(engine_class):
    """注入升级方法到 NineDimEngine 类"""
    engine_class.calc_angian = _calc_angian
    engine_class.calc_yagua = _calc_yagua
    engine_class.calc_keying_system = _calc_keying_system
    engine_class.calc_four_layer = _calc_four_layer
    engine_class.calc_baishen_priority = _calc_baishen_priority
    engine_class.calc_sanzha_wujia = _calc_sanzha_wujia
    engine_class.calc_menpo_quantified = _calc_menpo_quantified
    engine_class.calc_zhongwu_ji = _calc_zhongwu_ji
    engine_class.calc_enhanced_rolling = _calc_enhanced_rolling
    return engine_class
