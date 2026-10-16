"""
2024甲辰年 · 月度回测 v4.3 — 格局修正版
=========================================
核心修正：格局(天刑/顺化/同气等)对板块的利弊判定
- 天刑 = 客气克主气 → 主气五行受压制（跌），客气五行受益（涨）
- 顺化 = 客气生主气 → 主气五行受生（涨），客气五行被耗（略跌）
- 同气 = 客气同主气 → 此五行共振放大（大涨或大跌看其他因子）
- 小逆 = 主气生客气 → 主气五行泄气（略跌）
- 不和 = 主气克客气 → 主气五行抗性（略涨）
"""
import sys, json
sys.path.insert(0, '.')
from wuyun_core import (
    get_keqi_sequence, LIUQI_WUXING, ZHUQI_STEPS,
    SHENG_CYCLE, KE_CYCLE, BEI_KE,
    get_zhuqi_at_step, get_keqi_at_step, judge_pattern
)
from three_layer_ganzhi_enhanced import (
    TIANGAN_WUXING, DIZHI_WUXING, CANG_GAN, CANG_GAN_WEIGHT, NAYIN_WUXING
)

ACTUAL = {
    "木": [-12,+8,-3,-3,-5,-10,-8,-6,+25,0,-4,-3],
    "火": [-18,+15,+8,-4,-8,-12,-15,-8,+37,+12,-7,-4],
    "土": [-8,+2,-3,0,-2,-2,-3,-5,+30,+4,-3,-1],
    "金": [+2,0,+2,-2,-1,+1,0,-1,+12,+5,+2,0],
    "水": [+3,-1,-1,0,+1,+2,+1,0,-8,-2,0,+1],
}
PLATES = ["木","火","土","金","水"]
SHENG, KE = SHENG_CYCLE, KE_CYCLE
MONTH_GZ = {1:"乙丑",2:"丙寅",3:"丁卯",4:"戊辰",5:"己巳",6:"庚午",
             7:"辛未",8:"壬申",9:"癸酉",10:"甲戌",11:"乙亥",12:"丙子"}
SITIAN_BASE = {
    "木": (-0.2, -0.1), "火": (-0.5, -0.2), "土": (-0.1, +0.3),
    "金": (+0.1, +0.1), "水": (+0.3, -0.2),
}

def get_qi(m, d=15):
    if m==1: return 0 if d>=20 else 5
    if m==2: return 0
    if m==3: return 1 if d>=21 else 0
    if m==4: return 1
    if m==5: return 2 if d>=21 else 1
    if m==6: return 2
    if m==7: return 3 if d>=23 else 2
    if m==8: return 3
    if m==9: return 4 if d>=23 else 3
    if m==10: return 4
    if m==11: return 5 if d>=22 else 4
    if m==12: return 5

def qi_effect_corrected(plate_wx: str, qi_idx: int, keqi_seq: list) -> float:
    """修正版气段影响 — 格局分主客方"""
    zhuqi = get_zhuqi_at_step(qi_idx)
    keqi = get_keqi_at_step(keqi_seq, qi_idx)
    if not zhuqi: return 0
    zwx = LIUQI_WUXING.get(zhuqi,"")
    kwx = LIUQI_WUXING.get(keqi,"") if keqi else ""
    score = 0.0
    
    # ── 主气 vs 板块 ──
    if plate_wx == zwx:               score += 0.4  # 同气
    elif SHENG.get(zwx) == plate_wx:  score += 0.4  # 主气生我
    elif SHENG.get(plate_wx) == zwx:  score += -0.3 # 我生主气=泄
    elif KE.get(zwx) == plate_wx:     score += -0.5 # 主气克我
    elif KE.get(plate_wx) == zwx:     score += 0.2  # 我克主气=抗
    
    # ── 客气 vs 板块 ──
    if kwx:
        if plate_wx == kwx:           score += 0.3  # 客同板
        elif SHENG.get(kwx) == plate_wx: score += 0.3  # 客生我
        elif KE.get(kwx) == plate_wx: score += -0.3 # 客克我
        elif SHENG.get(plate_wx) == kwx: score += -0.1 # 我生客=泄
    
    # ── 格局对板块的利弊（核心修正）──
    pat = judge_pattern(zhuqi, keqi)
    if pat == "天刑":
        # 天刑=客气克主气
        # 若板块=主气五行 → 被克=跌
        # 若板块=客气五行 → 克者=涨
        # 若板块=被客气所克 → 被克=跌
        if plate_wx == zwx:
            score += -0.3  # 主气方被克
        if plate_wx == kwx:
            score += 0.3   # 客气方受益
        if kwx and KE.get(kwx) == plate_wx:
            score += -0.2  # 被客气所克
    elif pat == "顺化":
        # 顺化=客气生主气
        if plate_wx == zwx:
            score += 0.2   # 主气方受生
        if plate_wx == kwx:
            score += -0.1  # 客气方耗气
    elif pat == "同气":
        if plate_wx == zwx:
            score += 0.2   # 共振放大
    elif pat == "小逆":
        # 主气生客气=主气泄
        if plate_wx == zwx:
            score += -0.15
    elif pat == "不和":
        # 主气克客气=主气抗
        if plate_wx == zwx:
            score += 0.15
    
    return round(score, 3)

def gz_effect(plate_wx: str, month: int) -> float:
    gz = MONTH_GZ.get(month,"")
    if not gz: return 0
    gan,zhi = gz[0],gz[1]
    gwx=TIANGAN_WUXING.get(gan,"")
    zwx=DIZHI_WUXING.get(zhi,"")
    s=0.0
    if gwx==plate_wx: s+=0.3
    elif SHENG.get(gwx)==plate_wx: s+=0.2
    elif KE.get(gwx)==plate_wx: s-=0.2
    if zwx==plate_wx: s+=0.2
    elif SHENG.get(zwx)==plate_wx: s+=0.15
    elif KE.get(zwx)==plate_wx: s-=0.15
    nw=NAYIN_WUXING.get(gz,"")
    if nw:
        if nw==plate_wx: s+=0.15
        elif SHENG.get(nw)==plate_wx: s+=0.1
        elif KE.get(nw)==plate_wx: s-=0.1
    if zhi in CANG_GAN:
        for qt,qw in CANG_GAN[zhi].items():
            wt=CANG_GAN_WEIGHT.get(qt,0)
            if qw==plate_wx: s+=wt*0.4
    return round(s,3)

def run() -> dict:
    keqi = get_keqi_sequence("太阳寒水")
    total=hits=0
    pd={p:{"h":0,"t":0} for p in PLATES}
    dlist=[]
    yufa={p:0.0 for p in PLATES}
    streak={p:0 for p in PLATES}
    
    for pi,plate in enumerate(PLATES):
        for mi in range(12):
            month=mi+1
            actual=ACTUAL[plate][mi]
            
            # 气段因子(45%)
            qi_s = qi_effect_corrected(plate, get_qi(month), keqi)
            # 边界月加权
            if month == 1:
                qi_s = (qi_effect_corrected(plate,5,keqi)*20 + qi_effect_corrected(plate,0,keqi)*11)/31
            elif month == 3:
                qi_s = (qi_effect_corrected(plate,0,keqi)*20 + qi_effect_corrected(plate,1,keqi)*11)/31
            elif month == 9:
                qi_s = (qi_effect_corrected(plate,3,keqi)*22 + qi_effect_corrected(plate,4,keqi)*9)/31
            
            # 司天在泉(25%)
            bh1,bh2 = SITIAN_BASE[plate]
            base_s = bh1 if month<=6 else bh2
            
            # 月干支(20%)
            gz_s = gz_effect(plate, month)
            
            # 郁发(10%)
            if mi>0:
                pv=ACTUAL[plate][mi-1]
                if pv<-5: yufa[plate]+=0.4; streak[plate]+=1
                elif pv>5: yufa[plate]-=0.3; streak[plate]=0
                else: yufa[plate]*=0.95; streak[plate]=0
            sb = min(1.0+(streak[plate]-2)*0.5, 2.5) if streak[plate]>=3 else 1.0
            yufa_s = max(min(yufa[plate]*sb*0.1, 1.0), -1.0)
            
            score = round(qi_s*0.45 + base_s*0.25 + gz_s*0.20 + yufa_s, 3)
            
            if score >= 0.2: pred="涨"
            elif score <= -0.15: pred="跌"
            else: pred="震荡"
            
            if actual>=3: ad="涨"
            elif actual<=-3: ad="跌"
            else: ad="震荡"
            
            hit=pred==ad
            if hit: hits+=1; pd[plate]["h"]+=1
            pd[plate]["t"]+=1; total+=1
            dlist.append({"板块":plate,"月":f"{month}月","分":score,
                           "推":pred,"实":ad,"实值":f"{actual:+d}%",
                           "✅" if hit else "❌":""})
    
    acc=round(hits/total*100,1)
    return {"acc":acc,"hits":hits,"total":total,
            "plate":{p:round(r["h"]/r["t"]*100,1) for p,r in pd.items()},"d":dlist}

if __name__=="__main__":
    print("="*70)
    print("🔬 v4.3 — 格局分主客方 + 天刑对主气不利！")
    print("="*70)
    r=run()
    print(f"\n📊 整体: {r['acc']}% ({r['hits']}/{r['total']})")
    for p in PLATES: print(f"  {p}: {r['plate'][p]}%")
    print(f"\n逐月:")
    for d in r["d"]:
        mk="✅" if d["推"]==d["实"] else "❌"
        print(f"  {mk} {d['板块']}·{d['月']} 推{d['推']}({d['分']:+.2f}) 实{d['实']}({d['实值']})")
    print(f"\n🏆 v4.3({r['acc']}%) vs 4.2(50%) vs 4.1(41.7%) vs v2(37%)")
    json.dump(r, open("backtest_2024_v4_3_result.json","w",encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("✅ 已保存")
