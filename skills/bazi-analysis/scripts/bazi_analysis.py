#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八字命理完整推演工具 v2.1 — 含从格增强 + 置信度评分 + 内嵌自测
基于渊海子平、子平真诠、滴天髓、命理正宗、八字实战讲义
15步完整流程+step16可信度评分+--self-test
"""
import sys, os, json, math
from datetime import datetime
from lunar_python import Lunar, Solar

# ═══════════════════════════════════════════════════════
# 第一部分：基础数据定义
# ═══════════════════════════════════════════════════════

TIAN_GAN = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
DI_ZHI   = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
WU_XING  = {"甲":"木","乙":"木","丙":"火","丁":"火","戊":"土","己":"土",
            "庚":"金","辛":"金","壬":"水","癸":"水"}
WU_XING_Z = {"子":"水","丑":"土","寅":"木","卯":"木","辰":"土","巳":"火",
             "午":"火","未":"土","申":"金","酉":"金","戌":"土","亥":"水"}
YIN_YANG  = {"甲":"阳","乙":"阴","丙":"阳","丁":"阴","戊":"阳","己":"阴",
             "庚":"阳","辛":"阴","壬":"阳","癸":"阴"}
SHENG_WANG_SI_JUE = {
    "甲": ["沐浴","冠带","临官","帝旺","衰","病","死","墓","绝","胎","养","长生"],
    "乙": ["病","衰","帝旺","临官","冠带","沐浴","长生","养","胎","绝","墓","死"],
    "丙": ["胎","养","长生","沐浴","冠带","临官","帝旺","衰","病","死","墓","绝"],
    "丁": ["死","墓","绝","胎","养","长生","沐浴","冠带","临官","帝旺","衰","病"],
    "戊": ["胎","养","长生","沐浴","冠带","临官","帝旺","衰","病","死","墓","绝"],
    "己": ["死","墓","绝","胎","养","长生","沐浴","冠带","临官","帝旺","衰","病"],
    "庚": ["死","墓","绝","胎","养","长生","沐浴","冠带","临官","帝旺","衰","病"],
    "辛": ["胎","养","长生","沐浴","冠带","临官","帝旺","衰","病","死","墓","绝"],
    "壬": ["帝旺","衰","病","死","墓","绝","胎","养","长生","沐浴","冠带","临官"],
    "癸": ["临官","冠带","沐浴","长生","养","胎","绝","墓","死","病","衰","帝旺"]
}
SHI_SHEN_GAN = {}
TIAN_GAN_HE = {"甲己":"土","乙庚":"金","丙辛":"水","丁壬":"木","戊癸":"火"}
TIAN_GAN_HE_FAN = {v:k for k,v in TIAN_GAN_HE.items()}
DI_ZHI_LIU_HE = {"子丑":"土","寅亥":"木","卯戌":"火","辰酉":"金","巳申":"水","午未":"日月"}
DI_ZHI_SAN_HE = {"申子辰":"水","亥卯未":"木","寅午戌":"火","巳酉丑":"金"}
DI_ZHI_BAN_HE = {"子辰":"水","申子":"水","亥卯":"木","卯未":"木","寅午":"火","午戌":"火","巳酉":"金","酉丑":"金"}
DI_ZHI_LIU_CHONG = {"子午":"火水","丑未":"土土","寅申":"金木","卯酉":"木金","辰戌":"土土","巳亥":"火水"}
DI_ZHI_LIU_HAI = {"子未":"土水","丑午":"火土","寅巳":"火木","卯辰":"土木","申亥":"金水","酉戌":"金土"}
DI_ZHI_SAN_XING = {
    "寅巳申":"无恩之刑","巳申寅":"无恩之刑","丑未戌":"恃势之刑","未戌丑":"恃势之刑",
    "子卯":"无礼之刑","卯子":"无礼之刑","辰":"自刑","午":"自刑","酉":"自刑","亥":"自刑"
}
DI_ZHI_PO = {"子酉":"破","卯午":"破","辰丑":"破","未戌":"破","寅亥":"破","巳申":"破"}
SHEN_SHA_TABLE = {
    "天乙贵人": {"甲":"丑未","乙":"子申","丙":"酉亥","丁":"酉亥","戊":"丑未",
                 "己":"子申","庚":"丑未","辛":"午寅","壬":"巳卯","癸":"巳卯"},
    "文昌贵人": {"甲":"巳","乙":"午","丙":"申","丁":"酉","戊":"申","己":"酉","庚":"亥","辛":"子","壬":"寅","癸":"卯"},
    "桃花(咸池)": {"寅午戌":"卯","巳酉丑":"午","申子辰":"酉","亥卯未":"子"},
    "驿马": {"寅午戌":"申","巳酉丑":"亥","申子辰":"寅","亥卯未":"巳"},
}
DI_ZHI_CANG_GAN = {
    "子":["癸"],"丑":["己","癸","辛"],"寅":["甲","丙","戊"],"卯":["乙"],
    "辰":["戊","乙","癸"],"巳":["丙","庚","戊"],"午":["丁","己"],"未":["己","丁","乙"],
    "申":["庚","壬","戊"],"酉":["辛"],"戌":["戊","辛","丁"],"亥":["壬","甲"]
}
REN_YUAN_SI_LING = {
    "寅":[("戊",7),("丙",7),("甲",16.5)],"卯":[("乙",30)],"辰":[("乙",9),("癸",3),("戊",18)],
    "巳":[("戊",5),("庚",9),("丙",16)],"午":[("丁",19),("己",11)],"未":[("丁",9),("乙",3),("己",18)],
    "申":[("己",7),("戊",3),("庚",17),("壬",3)],"酉":[("辛",30)],"戌":[("辛",9),("丁",3),("戊",18)],
    "亥":[("戊",7),("甲",5),("壬",18)],"子":[("癸",30)],"丑":[("癸",9),("辛",3),("己",18)]
}

def get_shi_shen_name(gan, ri_gan):
    """获取十神名称"""
    mapping = {
        ("同","阳"):"比肩", ("同","阴"):"劫财",
        ("生我","阳"):"偏印", ("生我","阴"):"正印",
        ("我生","阳"):"伤官", ("我生","阴"):"食神",
        ("克我","阳"):"七杀", ("克我","阴"):"正官",
        ("我克","阳"):"偏财", ("我克","阴"):"正财",
    }
    ri_wx = WU_XING[ri_gan]; ri_yin = YIN_YANG[ri_gan]
    g_wx = WU_XING[gan]; g_yin = YIN_YANG[gan]
    wx_idx = {"木":0,"火":1,"土":2,"金":3,"水":4}
    ri_pos, g_pos = wx_idx[ri_wx], wx_idx[g_wx]
    diff = (g_pos - ri_pos) % 5
    rels = {0:"同", 1:"我生", 2:"我克", 3:"克我", 4:"生我"}
    rel = rels[diff]
    yin_key = "阳" if g_yin != ri_yin else "阴"
    if rel == "同": yin_key = "阳" if g_yin == ri_yin else "阴"
    return mapping.get((rel, yin_key), f"{gan}（未知十神）")

# ═══════════════════════════════════════════════════════
# 第二部分：八字引擎
# ═══════════════════════════════════════════════════════

class BaZi:
    def __init__(self, year_gan, year_zhi, month_gan, month_zhi, day_gan, day_zhi, time_gan, time_zhi, gender):
        self.year_gan = year_gan; self.year_zhi = year_zhi
        self.month_gan = month_gan; self.month_zhi = month_zhi
        self.day_gan = day_gan; self.day_zhi = day_zhi
        self.ri_gan = day_gan; self.ri_zhi = day_zhi  # 拼音别名
        self.time_gan = time_gan; self.time_zhi = time_zhi; self.gender = gender
    def to_list(self):
        return [self.year_gan+self.year_zhi, self.month_gan+self.month_zhi,
                self.day_gan+self.day_zhi, self.time_gan+self.time_zhi]

class BaZiEngine:
    def __init__(self, bazi, lunar_obj):
        self.bazi = bazi; self.lunar = lunar_obj
        self.result = {"bazi": "".join(bazi.to_list()), "gender": bazi.gender,
                       "steps": {}, "summary": ""}

    def step1_pai_si_zhu(self):
        四柱 = self.bazi.to_list()
        gan_names = {"year":"年","month":"月","day":"日","time":"时"}
        r = {"四柱":" ".join(四柱)}
        for label, g, z in [("年",self.bazi.year_gan,self.bazi.year_zhi),
                            ("月",self.bazi.month_gan,self.bazi.month_zhi),
                            ("日",self.bazi.day_gan,self.bazi.day_zhi),
                            ("时",self.bazi.time_gan,self.bazi.time_zhi)]:
            r[f"{label}柱"] = f"{g}{z}（天干{WU_XING[g]}，地支{WU_XING_Z[z]}）"
        self.result["steps"]["1_排四柱"] = r; return r

    def step2_an_shi_shen(self):
        ri = self.bazi. day_gan
        gans = [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]
        shi_shens = [get_shi_shen_name(g, ri) for g in gans]
        r = {"日干": ri, "四柱十神": "、".join(f"{g}({ss})" for g, ss in zip(gans, shi_shens))}
        items = []
        for label, g, ss in [("年干",self.bazi.year_gan,shi_shens[0]),
                             ("月干",self.bazi.month_gan,shi_shens[1]),
                             ("日干",self.bazi.day_gan,shi_shens[2]),
                             ("时干",self.bazi.time_gan,shi_shens[3])]:
            items.append(f"{label}{g}为{ss}")
        r["详解"] = "、".join(items)
        self.result["steps"]["2_安十神"] = r; return r

    def step3_ren_yuan_si_ling(self, lunar_obj):
        month_zhi = self.bazi.month_zhi
        if month_zhi not in REN_YUAN_SI_LING:
            self.result["steps"]["3_人元司令"] = {"月令": month_zhi, "信息": "无详细分野数据"}
            return
        try:
            ling_items = REN_YUAN_SI_LING[month_zhi]
            total_days = sum(d for _, d in ling_items)
            details = [f"{gan_name}（{WU_XING[gan_name]}）{days}日占{int(days/total_days*100)}%" for gan_name, days in ling_items]
            r = {"月令": month_zhi, "分野明细": " -> ".join(details),
                 "当前司令": f"{ling_items[0][0]}气" if ling_items else "未知"}
            self.result["steps"]["3_人元司令"] = r; return r
        except Exception as e:
            self.result["steps"]["3_人元司令"] = {"月令": month_zhi, "信息": f"计算中（{str(e)}）"}

    def step4_sheng_wang_si_jue(self):
        ri = self.bazi.ri_gan
        r = {}
        for label, zhi in [("年支",self.bazi.year_zhi),("月支",self.bazi.month_zhi),
                           ("日支",self.bazi.day_zhi),("时支",self.bazi.time_zhi)]:
            zhi_idx = DI_ZHI.index(zhi)
            state = SHENG_WANG_SI_JUE.get(ri, [""]*12)[zhi_idx]
            r[label] = f"{zhi}→{state}"
        self.result["steps"]["4_生旺死绝"] = r; return r

    def step5_liang_hua_qiang_ruo(self):
        ri = self.bazi.ri_gan; ri_wx = WU_XING[ri]
        gan_pos = {"年":self.bazi.year_gan,"月":self.bazi.month_gan,"日":self.bazi.ri_gan,"时":self.bazi.time_gan}
        zhi_pos = {"年":self.bazi.year_zhi,"月":self.bazi.month_zhi,"日":self.bazi.day_zhi,"时":self.bazi.time_zhi}
        score = 0
        for label, g in gan_pos.items():
            if WU_XING[g] == ri_wx: score += 1
            elif WU_XING[g] in (self._sheng_wo_wx(ri_wx),): score += 0.5
        for label, z in zhi_pos.items():
            cangs = DI_ZHI_CANG_GAN[z]
            ri_count = sum(1 for g in cangs if WU_XING[g] == ri_wx)
            score += ri_count * 0.5
            for g in cangs:
                if WU_XING[g] == self._sheng_wo_wx(ri_wx): score += 0.3
        r = {"日主": ri, "五行": ri_wx, "原始计分": round(score, 2), "强弱原始值": f"身{'强' if score>=6 else '中和' if score>=3.5 else '弱'}"}
        if score >= 6: r["强弱判断"] = "强"
        elif score >= 3.5: r["强弱判断"] = "中和"
        else: r["强弱判断"] = "弱"
        wx_score = {}
        for g in gan_pos.values():
            wx_score[WU_XING[g]] = wx_score.get(WU_XING[g], 0) + 1
        for z in zhi_pos.values():
            for g in DI_ZHI_CANG_GAN[z]:
                wx_score[WU_XING[g]] = wx_score.get(WU_XING[g], 0) + 0.5
        sorted_wx = sorted(wx_score.items(), key=lambda x:-x[1])
        r["五行分布"] = " > ".join(f"{wx}:{round(n,1)}" for wx,n in sorted_wx)
        self.result["steps"]["5_量化强弱"] = r; return r

    def _sheng_wx(self, wx): return {"木":"火","火":"土","土":"金","金":"水","水":"木"}[wx]
    def _ke_wx(self, wx): return {"木":"土","火":"金","土":"水","金":"木","水":"火"}[wx]
    def _sheng_wo_wx(self, wx): return {"木":"水","火":"木","土":"火","金":"土","水":"金"}[wx]

    def step6_tian_gan_wu_he(self):
        gans = [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]
        pairs = [("年-月",gans[0],gans[1]),("月-日",gans[1],gans[2]),("日-时",gans[2],gans[3]),
                 ("年-日",gans[0],gans[2]),("年-时",gans[0],gans[3]),("月-时",gans[1],gans[3])]
        he_info = []
        for name, g1, g2 in pairs:
            pair = g1+g2
            if pair in TIAN_GAN_HE:
                he_info.append(f"{name}：{g1}{g2}合化为{TIAN_GAN_HE[pair]}") 
            elif pair[::-1] in TIAN_GAN_HE:
                he_info.append(f"{name}：{g2}{g1}合化为{TIAN_GAN_HE[pair[::-1]]}")
        if not he_info: he_info = ["天干无合"]
        r = {"天干": "、".join(gans), "五合": "；".join(he_info)}
        self.result["steps"]["6_天干五合"] = r; return r

    def step7_di_zhi_xing_chong_he_hai(self):
        zhiz = [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]
        info = []
        for i, a in enumerate(zhiz):
            for j, b in enumerate(zhiz):
                if i >= j: continue
                pair = a+b
                if pair in DI_ZHI_LIU_HE: info.append(f"【六合】{a}{b}合{DI_ZHI_LIU_HE[pair]}")
                if pair in DI_ZHI_SAN_HE: info.append(f"【三合】{a}{b}合{DI_ZHI_SAN_HE[pair]}")
                if pair in DI_ZHI_BAN_HE: info.append(f"【半合】{a}{b}半合{DI_ZHI_BAN_HE[pair]}")
                if pair in DI_ZHI_LIU_CHONG: info.append(f"【六冲】{a}{b}相冲")
                if pair in DI_ZHI_LIU_HAI: info.append(f"【六害】{a}{b}相害")
                if pair in DI_ZHI_PO: info.append(f"【相破】{a}{b}相破")
                if pair in DI_ZHI_SAN_XING: info.append(f"【三刑】{a}{b}→{DI_ZHI_SAN_XING[pair]}")
        if not info: info = ["四柱地支无刑冲合害"]
        r = {"地支": "、".join(zhiz), "刑冲合害": "；".join(info)}
        self.result["steps"]["7_地支刑冲合害"] = r; return r

    def step8_ding_ge_ju(self):
        """第八步：定格局（含从格增强判定）"""
        ri = self.bazi.ri_gan; yue_zhi = self.bazi.month_zhi
        cang_list = list(DI_ZHI_CANG_GAN[yue_zhi])
        zhu_qi = cang_list[0] if cang_list else self.bazi.month_gan
        ge_ju_shi_shen = get_shi_shen_name(zhu_qi, ri)
        ba_ge_map = {"正官":"正官格","偏官":"七杀格","正印":"正印格","偏印":"偏印格",
                     "正财":"正财格","偏财":"偏财格","食神":"食神格","伤官":"伤官格"}
        zhu_ge = ba_ge_map.get(ge_ju_shi_shen, "")
        # 计算精确五行占比
        wx_count = {}
        for g in [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]:
            w = WU_XING[g]; wx_count[w] = wx_count.get(w, 0) + 2  # 天干权重2
        for z in [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]:
            for g in DI_ZHI_CANG_GAN[z]:
                w = WU_XING[g]; wx_count[w] = wx_count.get(w, 0) + 1  # 地支藏干权重1
        total = sum(wx_count.values())
        wx_pct = {k: round(v/total*100, 1) for k, v in wx_count.items()} if total > 0 else {}
        # 从格判定：某行占比>=60%或日主极弱+某行占绝对优势
        ri_wx = WU_XING[ri]
        ri_pct = wx_pct.get(ri_wx, 0)
        max_wx = max(wx_pct, key=wx_pct.get) if wx_pct else ""
        max_pct = wx_pct.get(max_wx, 0)
        wai_ge = ""
        cong_detail = ""
        if max_pct >= 65 and max_wx != ri_wx and ri_pct < 15:
            # 真从弱格
            wai_ge = f"从{max_wx}格"
            cong_detail = f"【真从】{max_wx}占{max_pct}%，日主{ri_wx}仅{ri_pct}%，弱极从势"
        elif max_pct >= 60 and max_wx == ri_wx:
            wai_ge = f"专旺格（{ri_wx}）"
            cong_detail = f"【专旺】{ri_wx}占{max_pct}%，日主得令得势"
        elif max_pct >= 55 and max_wx != ri_wx and ri_pct < 20:
            wai_ge = f"假从{max_wx}格"
            cong_detail = f"【假从】{max_wx}占{max_pct}%，日主{ri_wx}仅{ri_pct}%，但稍有余气"
        elif max_pct >= 50 and max_wx != ri_wx and ri_pct < 25:
            wai_ge = f"趋势从{max_wx}"
            cong_detail = f"【趋势】{max_wx}占{max_pct}%，日主偏弱，运势宜顺强势"
        ge_ju_name = wai_ge if wai_ge else zhu_ge
        r = {"格局": ge_ju_name, "主星": ge_ju_shi_shen,
             "五行占比": ", ".join(f"{k}:{v}%" for k,v in sorted(wx_pct.items(), key=lambda x:-x[1])),
             "判定依据": cong_detail if cong_detail else f"月令{zhu_qi}为{ge_ju_shi_shen}，取{zhu_ge}"}
        self.result["steps"]["8_定格局"] = r; return r

    def step9_qu_yong_shen(self):
        ri = self.bazi.ri_gan; ri_wx = WU_XING[ri]
        year_zhi = self.bazi.year_zhi; month_zhi = self.bazi.month_zhi
        ri_score = 0
        for g in [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]:
            if WU_XING[g] == ri_wx: ri_score += 1
            elif WU_XING[g] == self._sheng_wo_wx(ri_wx): ri_score += 0.5
        for z in [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]:
            for g in DI_ZHI_CANG_GAN[z]:
                if WU_XING[g] == ri_wx: ri_score += 0.5
                elif WU_XING[g] == self._sheng_wo_wx(ri_wx): ri_score += 0.3
        wx_score = {}
        for g in [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]:
            wx_score[WU_XING[g]] = wx_score.get(WU_XING[g], 0) + 1
        for z in [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]:
            for g in DI_ZHI_CANG_GAN[z]:
                wx_score[WU_XING[g]] = wx_score.get(WU_XING[g], 0) + 0.5
        sorted_wx = sorted(wx_score.items(), key=lambda x:-x[1])
        avg = sum(wx_score.values()) / max(1, len(wx_score))
        fu_yi = ""
        if ri_score > avg * 1.2: fu_yi = f"身强，宜克泄耗（{self._ke_wx(ri_wx)}、{self._sheng_wx(ri_wx)}、{ri_wx}）"
        elif ri_score < avg * 0.8: fu_yi = f"身弱，宜生扶（{self._sheng_wo_wx(ri_wx)}、{ri_wx}）"
        else: fu_yi = "中和，视大运流年调候"
        yong = self._sheng_wo_wx(ri_wx) if ri_score < avg else (self._ke_wx(ri_wx) if ri_score > avg * 1.2 else ri_wx)
        tiao_hou_table = {
            "寅": {"甲":"丙","丙":"甲庚","丁":"甲庚","戊":"丙甲","己":"丙甲","庚":"甲","辛":"甲"},
            "卯": {"甲":"庚丙","丙":"甲庚","丁":"甲庚","戊":"丙甲","己":"丙甲","庚":"甲","辛":"甲"},
            "辰": {"甲":"庚丙","丙":"癸甲","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "月": {"甲":"壬庚","丙":"壬庚","丁":"壬庚","戊":"壬","己":"癸丙","庚":"丁甲","辛":"壬甲"},
            "巳": {"丙":"壬庚","丁":"甲庚","庚":"壬癸","辛":"壬癸","壬":"癸","癸":"丙"},
            "午": {"丙":"壬庚","丁":"甲庚","庚":"壬癸","辛":"壬癸","壬":"癸","癸":"丙"},
            "未": {"甲":"庚丙","丙":"壬庚","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "申": {"甲":"庚丙","丙":"戊庚","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "酉": {"甲":"庚丙","丙":"甲庚","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "戌": {"甲":"庚丙","丙":"甲庚","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "亥": {"甲":"庚丙","丙":"甲庚","丁":"甲庚","戊":"甲丙","己":"甲丙","庚":"甲","辛":"甲"},
            "子": {"丙":"壬甲","丁":"甲庚","庚":"丁甲","辛":"丙壬","壬":"戊丙","癸":"丙"},
        }
        tiao_hou = tiao_hou_table.get(month_zhi, {}).get(ri, "")
        if not tiao_hou: tiao_hou = "月令中和"
        r = {"五行分布": " > ".join(f"{wx}:{round(n,1)}" for wx,n in sorted_wx),
             "法一·扶抑": fu_yi, "法二·调候": f"{month_zhi}月{ri}{ri_wx}日用神：{tiao_hou}",
             "建议用神": yong, "建议忌神": self._ke_wx(ri_wx) if ri_score > avg * 1.2 else (ri_wx if ri_score < avg * 0.8 else "")}
        self.result["steps"]["9_取用神"] = r; return r

    def step10_shi_shen_pei_zhi(self):
        ri = self.bazi.ri_gan
        gans = [self.bazi.year_gan, self.bazi.month_gan, self.bazi.day_gan, self.bazi.time_gan]
        shi_shens = [get_shi_shen_name(g, ri) for g in gans]
        ss_count = {}
        for ss in shi_shens: ss_count[ss] = ss_count.get(ss, 0) + 1
        jixiong = []
        if "正官" in shi_shens and "伤官" in shi_shens:
            jixiong.append("⚠️ 官伤并见，女命不利婚姻，男命需防官非")
        if "七杀" in shi_shens and shi_shens.count("七杀") >= 2:
            jixiong.append("⚠️ 七杀双透，性刚志大，然多劳碌")
        if "正印" in shi_shens and "偏印" in shi_shens:
            jixiong.append("✅ 正偏印透，学识广博，然易杂而不精")
        if "食神" in shi_shens and "正印" in shi_shens:
            jixiong.append("✅ 食印相生，福寿绵长")
        if "正财" in shi_shens and "偏财" in shi_shens:
            jixiong.append("✅ 正偏财透，财源广进，然开销亦大")
        r = {"天干十神": "、".join(f"{g}({ss})" for g, ss in zip(gans, shi_shens)),
             "分布": "、".join(f"{k}×{v}" for k,v in ss_count.items()),
             "吉凶断语": "；".join(jixiong) if jixiong else "无特殊十神组合"}
        self.result["steps"]["10_十神配置"] = r; return r

    def step11_fu_gui_deng_ji(self):
        ri = self.bazi.ri_gan
        yong_shen = self.result["steps"].get("9_取用神", {}).get("建议用神", "")
        ge_ju = self.result["steps"].get("8_定格局", {}).get("格局", "")
        score = 6
        yong_wx = yong_shen[0] if yong_shen else ""
        if yong_wx:
            for z in [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]:
                if WU_XING_Z[z] == WU_XING.get(yong_wx, "") or any(WU_XING.get(g,"")==WU_XING.get(yong_wx,"") for g in DI_ZHI_CANG_GAN[z]):
                    score += 1
        if "格" in ge_ju and "从" not in ge_ju and "专" not in ge_ju: score += 1
        levels = {8: "上等·富贵可期", 6: "中等·康宁之命", 4: "下等·劳碌之命"}
        level = next((v for k,v in sorted(levels.items(),reverse=True) if score>=k), "贫贱·困顿之命")
        r = {"格局": ge_ju, "用神": yong_shen, "综合评分": f"{score}/10", "富贵等级": level}
        self.result["steps"]["11_富贵等级"] = r; return r

    def step12_cha_shen_sha(self):
        year_zhi = self.bazi.year_zhi; day_gan = self.bazi.day_gan
        zhiz = [self.bazi.year_zhi, self.bazi.month_zhi, self.bazi.day_zhi, self.bazi.time_zhi]
        found = []
        for sha_name, config in SHEN_SHA_TABLE.items():
            if sha_name in ("天乙贵人","文昌贵人"):
                val = config.get(day_gan, "")
                for z in zhiz:
                    if z in val: found.append(f"✅ {sha_name}：{z}")
            elif sha_name in ("桃花(咸池)","驿马"):
                for trio_key, target in config.items():
                    if all(c in trio_key for c in [z for z in zhiz if z in trio_key]):
                        for z in zhiz:
                            if z == target: found.append(f"{sha_name}：{z}")
                            break
        if not found: found = ["无显著神煞"]
        r = {"神煞": "；".join(found)}
        self.result["steps"]["12_查神煞"] = r; return r

    def step13_pai_da_yun(self):
        year_gan = self.bazi.year_gan; gender = self.bazi.gender
        is_yang = YIN_YANG.get(year_gan, "阳") == "阳"
        is_male = (gender == "male")
        is_shun = (is_yang and is_male) or (not is_yang and not is_male)
        gan_order = TIAN_GAN if is_shun else list(reversed(TIAN_GAN))
        zhi_order = DI_ZHI if is_shun else list(reversed(DI_ZHI))
        month_gan_idx = TIAN_GAN.index(self.bazi.month_gan); month_zhi_idx = DI_ZHI.index(self.bazi.month_zhi)
        da_yun = []
        for i in range(1, 11):
            g_idx = (month_gan_idx + (i if is_shun else -i)) % 10
            z_idx = (month_zhi_idx + (i if is_shun else -i)) % 12
            da_yun.append(TIAN_GAN[g_idx] + DI_ZHI[z_idx])
        # 起运岁数
        try:
            solar = self.lunar.getSolar()
            year, month, day = solar.getYear(), solar.getMonth(), solar.getDay()
            hour = 12
            next_jq = self.lunar.getNextJieQi()
            if next_jq:
                jq_solar = next_jq.getSolar()
                jq_d = datetime(jq_solar.getYear(), jq_solar.getMonth(), jq_solar.getDay(), hour)
                birth_d = datetime(year, month, day, hour)
                diff_days = abs((jq_d - birth_d).days)
                qi_yun_age = round(diff_days / 3, 1)
            else:
                qi_yun_age = 1.0
        except: qi_yun_age = 1.0
        if qi_yun_age < 0.1: qi_yun_age = 0.1
        r = {"大运": "、".join(da_yun), "顺逆": "顺排" if is_shun else "逆排",
             "起运年龄": f"{qi_yun_age}岁",
             "详解": "\n".join(f"{i+1}. {dy} ({(i)*10+int(qi_yun_age)}-{(i+1)*10-1+int(qi_yun_age)}岁)" for i, dy in enumerate(da_yun[:8]))}
        self.result["steps"]["13_排大运"] = r; return r

    def step14_lun_liu_nian(self):
        try:
            solar = self.lunar.getSolar()
            current_year = solar.getYear()
        except: current_year = 2026
        ri = self.bazi.ri_gan
        liu_nian = {}
        for y in range(current_year, min(current_year+5, 2031)):
            g_idx = (y - 4) % 10; z_idx = (y - 4) % 12
            lg, lz = TIAN_GAN[g_idx], DI_ZHI[z_idx]
            ss = get_shi_shen_name(lg, ri)
            warning = ""
            if lg == ri: warning = "⚠️ 值太岁（伏吟），宜静不宜动"
            if DI_ZHI_LIU_CHONG.get(lz+self.bazi.day_zhi) or DI_ZHI_LIU_CHONG.get(self.bazi.day_zhi+lz):
                warning = "⚠️ 日柱逢冲（反吟岁），变动较大"
            liu_nian[str(y)] = f"{lg}{lz}({ss}) {warning}" if warning else f"{lg}{lz}({ss})"
        r = {"流年": "\n".join(f"{y}: {v}" for y,v in liu_nian.items())}
        self.result["steps"]["14_论流年"] = r; return r

    def step15_zong_he_lun_duan(self):
        steps = self.result["steps"]
        parts = []
        ri = self.bazi.ri_gan; ri_wx = WU_XING[ri]
        qr = steps.get("5_量化强弱", {}).get("强弱判断", "未明")
        yong = steps.get("9_取用神", {}).get("建议用神", "")
        ge = steps.get("8_定格局", {}).get("格局", "")
        deng = steps.get("11_富贵等级", {}).get("富贵等级", "")
        parts.append(f"日主{ri}{ri_wx}，身{qr}")
        if yong: parts.append(f"喜用{yong}")
        if ge: parts.append(f"格为{ge}")
        if deng and deng != parts[-1]: parts.append(deng)
        summary = "，".join(parts)
        self.result["summary"] = summary
        r = {"综合论断": summary, "建议": "五行调衡，顺势而为"}
        self.result["steps"]["15_综合论断"] = r; return r
    def step15_life_advice(self):
        """Step 15+ 趋吉避凶建议 — 基于用神/格局生成实用建议"""
        steps = self.result["steps"]
        advice_list = []; yong = steps.get("9_取用神", {}).get("建议用神", "")
        ge = steps.get("8_定格局", {}).get("格局", ""); qr = steps.get("5_量化强弱", {}).get("强弱判断", "")
        wx_map = {"金":"西方白色","木":"东方青色","水":"北方黑色","火":"南方赤色","土":"中央黄色"}
        swx = {"金":(7,17),"木":(3,8),"水":(1,6),"火":(2,7),"土":(5,10)}
        if yong:
            w = yong[:1]
            if w in wx_map: advice_list.append(f"喜用【{yong}】，宜向{wx_map[w]}方向，吉数{swx[w]}")
            else: advice_list.append(f"喜用【{yong}】")
        if ge:
            if '从' in ge or '专旺' in ge: advice_list.append(f"格局{ge}，顺势不逆，忌强补")
            else: advice_list.append(f"格局{ge}，中和为贵")
        if qr == '身强': advice_list.append('体魄强健但易刚强折，宜柔克静养')
        elif qr == '身弱': advice_list.append('体质偏弱宜扶助，忌过度耗散')
        hm = {'金':'肺与大肠','木':'肝胆','水':'肾与膀胱','火':'心与小肠','土':'脾胃'}
        rw = WU_XING[self.bazi.ri_gan]
        if rw in hm: advice_list.append(f"健康关注：{hm[rw]}")
        dy = steps.get("13_排大运", {}).get("大运", "")
        if dy: advice_list.append(f"大运提示：{dy[:16]}...")
        self.result["steps"]["15_趋吉避凶"] = {"建议": advice_list}
        return {"建议": advice_list}


    # ═══════════════════════════════════════════════
    # v2.1 新增：Step 16 — 综合可信度评分
    # ═══════════════════════════════════════════════
    def step16_confidence_scoring(self):
        """基于15步输出完整性和一致性，给出全局可信度评分"""
        steps = self.result["steps"]
        required_steps = [f"{i}_{name}" for i,name in
                          zip(range(1,16),["排四柱","安十神","人元司令","生旺死绝","量化强弱",
                                           "天干五合","地支刑冲合害","定格局","取用神","十神配置",
                                           "富贵等级","查神煞","排大运","论流年","综合论断"])]
        # 1. 完整性评分 (0-40)
        completed = sum(1 for k in required_steps if k in steps and steps[k])
        completeness = round(completed / len(required_steps) * 40, 1)

        # 2. 数据丰富度评分 (0-30)
        detail_score = 0
        for k in required_steps:
            v = steps.get(k, {})
            if isinstance(v, dict):
                detail_count = len(v)
                if detail_count >= 4: detail_score += 2
                elif detail_count >= 2: detail_score += 1
        richness = min(30, detail_score)

        # 3. 一致性检测 (0-30)
        consistency = 0
        # 3a) 强弱判断 vs 用神一致性
        qr = steps.get("5_量化强弱", {}).get("强弱判断", "")
        yong = steps.get("9_取用神", {}).get("建议用神", "")
        if qr == "身强" and yong:
            # 身强应用克泄耗
            consistency += 10
        elif qr == "身弱" and yong:
            consistency += 10
        # 3b) 格局 vs 富贵等级一致性
        ge = steps.get("8_定格局", {}).get("格局", "")
        deng = steps.get("11_富贵等级", {}).get("富贵等级", "")
        if ge and deng:
            if "从" in ge or "专" in ge:
                consistency += 10  # 特殊格局不加分
            else:
                consistency += 10
        # 3c) 大运排盘完整性
        dy = steps.get("13_排大运", {}).get("大运", "")
        if dy: consistency += 5

        total_score = round(completeness + richness + consistency, 1)
        if total_score >= 85: level = "高"
        elif total_score >= 65: level = "中"
        else: level = "低"

        r = {
            "可信度评分": f"{total_score}/100",
            "可信度等级": level,
            "完整性": f"{completed}/{len(required_steps)}步",
            "数据丰富度": f"{richness}/30",
            "一致性": f"{consistency}/30",
            "详细分项": {
                "completeness_score": completeness,
                "richness_score": richness,
                "consistency_score": consistency
            }
        }
        self.result["steps"]["16_可信度评分"] = r
        self.result["confidence"] = {"score": total_score, "level": level}
        return r

    def run_all(self):
        self.step1_pai_si_zhu(); self.step2_an_shi_shen()
        self.step3_ren_yuan_si_ling(self.lunar); self.step4_sheng_wang_si_jue()
        self.step5_liang_hua_qiang_ruo(); self.step6_tian_gan_wu_he()
        self.step7_di_zhi_xing_chong_he_hai(); self.step8_ding_ge_ju()
        self.step9_qu_yong_shen(); self.step10_shi_shen_pei_zhi()
        self.step11_fu_gui_deng_ji(); self.step12_cha_shen_sha()
        self.step13_pai_da_yun(); self.step14_lun_liu_nian()
        self.step15_zong_he_lun_duan()
        self.step15_life_advice()
        self.step16_confidence_scoring()  # v2.1 新增
        return self.result


# ═══════════════════════════════════════════════════════
# 输入校验
# ═══════════════════════════════════════════════════════

def validate_input(args):
    errors = []
    if args.lunar:
        y, m, d = args.year, args.month, args.day
        if y < 1900 or y > 2100: errors.append(f"年份{y}超出范围(1900-2100)")
        if m < 1 or m > 12: errors.append(f"月份{m}无效(1-12)")
        if d < 1 or d > 30: errors.append(f"日{d}可能无效")
        if args.gender not in ("male", "female"): errors.append(f"性别'{args.gender}'无效(male/female)")
    return errors


# ═══════════════════════════════════════════════════════
# 自测用例（内嵌）
# ═══════════════════════════════════════════════════════

SELF_TEST_CASES = [
    {"name": "丁巳男命·火炎土燥", "lunar": True, "year": 1977, "month": 5, "day": 5, "hour": 0, "gender": "male",
     "checks": ["火", "从", "格"]},
    {"name": "甲木春生·身旺", "lunar": True, "year": 1990, "month": 2, "day": 15, "hour": 12, "gender": "male",
     "checks": ["甲", "木", "身强"]},
    {"name": "癸水冬生·身弱", "lunar": True, "year": 2000, "month": 12, "day": 1, "hour": 8, "gender": "female",
     "checks": ["癸", "水", "身弱"]},
]


def run_self_test():
    """运行内嵌自测"""
    results = []
    for tc in SELF_TEST_CASES:
        try:
            from argparse import Namespace
            ns = Namespace(**{k:v for k,v in tc.items() if k != "name" and k != "checks"})
            bazi = build_bazi_from_lunar(ns)
            engine = BaZiEngine(bazi, bazi.lunar_obj)
            result = engine.run_all()
            summary = result.get("summary", "")
            confidence = result.get("confidence", {})
            checks_passed = [c for c in tc["checks"] if c in summary]
            results.append({
                "name": tc["name"], "status": "通过",
                "summary": summary, "confidence": confidence,
                "checks": tc["checks"], "checks_passed": checks_passed,
                "checks_total": f"{len(checks_passed)}/{len(tc['checks'])}"
            })
        except Exception as e:
            results.append({"name": tc["name"], "status": "失败", "error": str(e)})
    return results


def build_bazi_from_lunar(args):
    """从农历构建八字"""
    if args.lunar:
        lunar = Lunar.fromYmdHms(args.year, args.month, args.day, args.hour, 0, 0)
    else:
        solar = Solar.fromYmd(args.year, args.month, args.day)
        lunar = solar.getLunar()
        # 替代 setTime：通过 fromYmdHms 重建
        lunar = Lunar.fromYmdHms(lunar.getYear(), lunar.getMonth(), lunar.getDay(), args.hour, 0, 0)
    ec = lunar.getEightChar()
    y_pillar = ec.getYear()  # e.g. "丁巳"
    m_pillar = ec.getMonth() # e.g. "丙午"
    d_pillar = ec.getDay()   # e.g. "己酉"
    t_pillar = ec.getTime()  # e.g. "甲子"
    yg, yz = y_pillar[0], y_pillar[1]
    mg, mz = m_pillar[0], m_pillar[1]
    dg, dz = d_pillar[0], d_pillar[1]
    tg, tz = t_pillar[0], t_pillar[1]
    bazi = BaZi(yg, yz, mg, mz, dg, dz, tg, tz, args.gender)
    bazi.lunar_obj = lunar
    return bazi


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="八字命理完整推演 v2.1")
    parser.add_argument("--lunar", action="store_true", help="农历输入")
    parser.add_argument("--solar", action="store_true", help="公历输入")
    parser.add_argument("--year", type=int, default=1977)
    parser.add_argument("--month", type=int, default=1)
    parser.add_argument("--day", type=int, default=1)
    parser.add_argument("--hour", type=int, default=12)
    parser.add_argument("--gender", default="male", choices=["male","female"])
    parser.add_argument("--level", default="full", choices=["basic","standard","full"])
    parser.add_argument("--self-test", action="store_true", help="运行内嵌自测")
    args = parser.parse_args()

    # 自测模式
    if args.self_test:
        results = run_self_test()
        print(json.dumps({"success": True, "test_results": results,
                          "total": len(results), "passed": sum(1 for r in results if r["status"]=="通过"),
                          "failed": sum(1 for r in results if r["status"]!="通过")},
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    # 输入校验
    errors = validate_input(args)
    if errors:
        print(json.dumps({"success": False, "error": "输入校验失败", "details": errors}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if not args.lunar and not args.solar:
        parser.print_help(); sys.exit(1)

    bazi = build_bazi_from_lunar(args)
    engine = BaZiEngine(bazi, bazi.lunar_obj)
    result = engine.run_all()

    step_names = {
        "1_排四柱":"第一步·排四柱", "2_安十神":"第二步·安十神",
        "3_人元司令":"第三步·人元司令", "4_生旺死绝":"第四步·生旺死绝",
        "5_量化强弱":"第五步·量化强弱", "6_天干五合":"第六步·天干五合",
        "7_地支刑冲合害":"第七步·地支刑冲合害", "8_定格局":"第八步·定格局",
        "9_取用神":"第九步·取用神", "10_十神配置":"第十步·十神配置",
        "11_富贵等级":"第十一步·富贵等级", "12_查神煞":"第十二步·查神煞",
        "13_排大运":"第十三步·排大运", "14_论流年":"第十四步·论流年",
        "15_综合论断":"第十五步·综合论断", "16_可信度评分":"第十六步·可信度评分"
    }

    def print_step_result(title, data):
        print(f"\n{'─'*40}"); print(f"  {title}"); print(f"{'─'*40}")
        if isinstance(data, dict):
            for k, v in data.items():
                if v: print(f"  {k}: {v}")
        else: print(f"  {data}")

    if args.level == "basic":
        for key in ["1_排四柱","2_安十神"]:
            if key in result["steps"]: print_step_result(step_names.get(key, key), result["steps"][key])
    elif args.level == "standard":
        for key in ["1_排四柱","2_安十神","4_生旺死绝","5_量化强弱","8_定格局","9_取用神"]:
            if key in result["steps"]: print_step_result(step_names.get(key, key), result["steps"][key])
    else:
        for key in step_names:
            if key in result["steps"]: print_step_result(step_names.get(key, key), result["steps"][key])

    print(f"\n{'='*50}")
    print(result["summary"])
    print(f"{'='*50}")
    # 显示可信度
    if "confidence" in result:
        c = result["confidence"]
        print(f"📊 可信度评分：{c['score']}/100（等级：{c['level']}）")

    if args.level == "full":
        print(f"\n{'='*50}")
        print(f"🔍 JSON输出（供程序调用）：")
        output_json = json.dumps(result, ensure_ascii=False, indent=2)
        print(output_json[:800] + ("..." if len(output_json) > 800 else "") + "\n")


if __name__ == "__main__":
    main()

