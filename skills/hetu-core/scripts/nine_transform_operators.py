# -*- coding: utf-8 -*-
"""九转编码算子库"""
from __future__ import annotations
import math, logging
from typing import Any, Dict
logger = logging.getLogger(__name__)
TransformResult = Dict[str, Any]

def _safe_float(v, default=0.0):
    if v is None: return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f): return default
        return f
    except: return default

def _mk(success, value, meaning="", wuxing="", error=""):
    return {"success":success,"value":round(value,6),"meaning":meaning,"wuxing":wuxing,"error":error}

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

print("Operators base loaded")

# === 一转·河图生数 (1-5) ===
HETU_SHENG = {1:("水","坎","天一生水"),2:("火","离","地二生火"),3:("木","震","天三生木"),4:("金","兑","地四生金"),5:("土","坤","天五生土")}

def t1_sheng(v):
    """一转·河图生数"""
    n = _safe_float(v)
    if n < 1 or n > 5:
        return _mk(False, n, error=f"越界:{n}")
    iv = int(round(n))
    if iv in HETU_SHENG:
        wx, g, m = HETU_SHENG[iv]
        return _mk(True, float(iv), meaning=m, wuxing=wx)
    return _mk(False, float(iv), error=f"未知:{iv}")

def t1_reverse(wx_or_g):
    s = wx_or_g.strip()
    rev = {v[0]:(k,v[1],v[2]) for k,v in HETU_SHENG.items()}
    rev.update({v[1]:(k,v[0],v[2]) for k,v in HETU_SHENG.items()})
    if s in rev:
        num, wx, m = rev[s]
        return _mk(True, float(num), meaning=m, wuxing=wx)
    return _mk(False, 0, error=f"未找到:{s}")

# === 二转·河图成数 (6-10) ===
HETU_CHENG = {6:("水","坎","地六成水"),7:("火","离","天七成火"),8:("木","震","地八成木"),9:("金","兑","天九成金"),10:("土","坤","地十成土")}

def t2_cheng(v):
    """二转·河图成数"""
    n = _safe_float(v)
    if n < 6 or n > 10:
        return _mk(False, n, error=f"越界:{n}")
    iv = int(round(n))
    if iv in HETU_CHENG:
        wx, g, m = HETU_CHENG[iv]
        return _mk(True, float(iv), meaning=m, wuxing=wx)
    return _mk(False, float(iv), error=f"未知:{iv}")

def t2_reverse(wx_or_g):
    s = wx_or_g.strip()
    rev = {v[0]:(k,v[1],v[2]) for k,v in HETU_CHENG.items()}
    rev.update({v[1]:(k,v[0],v[2]) for k,v in HETU_CHENG.items()})
    if s in rev:
        num, wx, m = rev[s]
        return _mk(True, float(num), meaning=m, wuxing=wx)
    return _mk(False, 0, error=f"未找到:{s}")

# === 三转·洛书正位 (1-9) ===
LUOSHU = {
    1:("水","坎","北","一白贪狼"),2:("土","坤","西南","二黑巨门"),
    3:("木","震","东","三碧禄存"),4:("木","巽","东南","四绿文曲"),
    5:("土","中","中","五黄廉贞"),6:("金","乾","西北","六白武曲"),
    7:("金","兑","西","七赤破军"),8:("土","艮","东北","八白左辅"),
    9:("火","离","南","九紫右弼")}

def t3_luoshu(v):
    """三转·洛书正位"""
    n = _safe_float(v)
    if n < 1 or n > 9:
        return _mk(False, n, error=f"越界:{n}")
    iv = int(round(n))
    if iv in LUOSHU:
        wx, g, d, star = LUOSHU[iv]
        return _mk(True, float(iv), meaning=f"{star}·{g}方{d}", wuxing=wx)
    return _mk(False, float(iv), error=f"未知:{iv}")

def t3_reverse(s):
    s = s.strip()
    rev = {}
    for k, v in LUOSHU.items():
        rev[v[0]] = (k, *v); rev[v[1]] = (k, *v); rev[v[2]] = (k, *v)
    rev["中宫"] = (5, *LUOSHU[5])
    if s in rev:
        e = rev[s]
        return _mk(True, float(e[0]), meaning=e[4], wuxing=e[1])
    return _mk(False, 0, error=f"未找到:{s}")

# === 四转·洛书变位 (-4~+4) ===
BW_MEAN = {-4:"阴极削弱",-3:"大力衰退",-2:"中度不足",-1:"微度稍欠",
           0:"中正平衡",1:"微度稍余",2:"中度旺盛",3:"大力亢盛",4:"阳极亢极"}
BW_LS = {-4:1,-3:2,-2:3,-1:4,0:5,1:6,2:7,3:8,4:9}
BW_WX = {1:"水",2:"土",3:"木",4:"木",5:"土",6:"金",7:"金",8:"土",9:"火"}

def t4_bianwei(v):
    """四转·洛书变位"""
    n = _safe_float(v)
    n = _clamp(n, -4.0, 4.0)
    iv = int(round(n))
    m = BW_MEAN.get(iv, "未知")
    ls = BW_LS.get(iv, 5)
    wx = BW_WX.get(ls, "土")
    return _mk(True, float(iv), meaning=m, wuxing=wx)

# === 五转·阴阳消长 (-1.0~+1.0) ===
YY_LEVELS = [(-1.0,-0.9,"纯阴·太阴"),(-0.9,-0.6,"重阴·少阴之极"),(-0.6,-0.3,"偏阴·阴盛"),
             (-0.3,-0.05,"微阴·阴偏"),(-0.05,0.05,"中正·平衡"),(0.05,0.3,"微阳·阳偏"),
             (0.3,0.6,"偏阳·阳盛"),(0.6,0.9,"重阳·少阳之极"),(0.9,1.0,"纯阳·太阳")]

def t5_yinyang(v):
    """五转·阴阳消长"""
    if isinstance(v, str):
        s = v.strip()
        if s in ("阳","纯阳","太阳"): return _mk(True, 1.0, meaning="纯阳·太阳", wuxing="火")
        if s in ("阴","纯阴","太阴"): return _mk(True, -1.0, meaning="纯阴·太阴", wuxing="水")
        if s == "平衡": return _mk(True, 0.0, meaning="中正·平衡", wuxing="土")
    n = _safe_float(v)
    n = _clamp(n, -1.0, 1.0)
    for lo, hi, m in YY_LEVELS:
        if lo <= n < hi:
            if n > 0.3: wx = "火"
            elif n > 0.05: wx = "木"
            elif n > -0.05: wx = "土"
            elif n > -0.3: wx = "金"
            else: wx = "水"
            return _mk(True, n, meaning=m, wuxing=wx)
    return _mk(True, n, meaning="纯阳·太阳", wuxing="火")

# === 六转·三才层次 (0.0~1.0) ===
SC_LEVELS = [(0.0,0.2,"地之极·纯形","土"),(0.2,0.4,"地偏人·形为主","金"),
             (0.4,0.6,"人之中·形神兼","土"),(0.6,0.8,"人偏天·神为主","木"),
             (0.8,1.0,"天之极·纯神","火")]

def t6_sancai(v):
    """六转·三才层次"""
    n = _safe_float(v)
    n = _clamp(n, 0.0, 1.0)
    for lo, hi, m, wx in SC_LEVELS:
        if lo <= n < hi:
            return _mk(True, n, meaning=m, wuxing=wx)
    return _mk(True, n, meaning="天之极·纯神", wuxing="火")

# === 七转·四象方向 (0-3) ===
SIXIANG = {0:("青龙","东","木","震"),1:("朱雀","南","火","离"),
           2:("白虎","西","金","兑"),3:("玄武","北","水","坎")}

def t7_sixiang(v):
    """七转·四象方向"""
    n = _safe_float(v)
    if n < 0 or n > 3:
        return _mk(False, n, error=f"越界:{n}")
    iv = int(round(n))
    if iv in SIXIANG:
        ss, d, wx, g = SIXIANG[iv]
        return _mk(True, float(iv), meaning=f"{ss}·{d}方·{g}宫", wuxing=wx)
    return _mk(False, float(iv), error=f"未知:{iv}")

def t7_reverse(s):
    s = s.strip()
    rev = {}
    for k, v in SIXIANG.items():
        rev[v[0]] = (k, *v); rev[v[1]] = (k, *v); rev[v[2]] = (k, *v); rev[v[3]] = (k, *v)
    if s in rev:
        e = rev[s]
        return _mk(True, float(e[0]), meaning=f"{e[0]}·{e[1]}", wuxing=e[2])
    return _mk(False, 0, error=f"未找到:{s}")

# === 八转·八卦辨象 (0-7) ===
BAGUA = {0:("乾","天","金","西北"),1:("兑","泽","金","西"),2:("离","火","火","南"),
         3:("震","雷","木","东"),4:("巽","风","木","东南"),5:("坎","水","水","北"),
         6:("艮","山","土","东北"),7:("坤","地","土","西南")}

def t8_bagua(v):
    """八转·八卦辨象"""
    n = _safe_float(v)
    if n < 0 or n > 7:
        return _mk(False, n, error=f"越界:{n}")
    iv = int(round(n))
    if iv in BAGUA:
        gua, nat, wx, d = BAGUA[iv]
        return _mk(True, float(iv), meaning=f"{gua}卦·{nat}·{d}", wuxing=wx)
    return _mk(False, float(iv), error=f"未知:{iv}")

def t8_reverse(s):
    s = s.strip().replace("卦", "")
    rev = {}
    for k, v in BAGUA.items():
        rev[v[0]] = (k, *v); rev[v[1]] = (k, *v); rev[v[2]] = (k, *v); rev[v[3]] = (k, *v)
    if s in rev:
        e = rev[s]
        return _mk(True, float(e[0]), meaning=f"{e[0]}卦", wuxing=e[2])
    return _mk(False, 0, error=f"未找到:{s}")

# === 九转·归元转化 (0.0~1.0) ===
GY_LEVELS = [(0.0,0.15,"混沌归一","土"),(0.15,0.35,"阴阳初分","水"),
             (0.35,0.55,"三才既立","木"),(0.55,0.75,"万象纷呈","火"),
             (0.75,0.90,"盛极而返","金"),(0.90,1.0,"归元返本","土")]

def t9_guiyuan(v):
    """九转·归元转化"""
    n = _safe_float(v)
    n = _clamp(n, 0.0, 1.0)
    for lo, hi, m, wx in GY_LEVELS:
        if lo <= n < hi:
            return _mk(True, n, meaning=m, wuxing=wx)
    return _mk(True, n, meaning="归元返本", wuxing="土")

# === 算子注册表 ===
REGISTRY = {
    "1_sheng":   {"func":t1_sheng,   "name":"河图生数","range":"1-5"},
    "2_cheng":   {"func":t2_cheng,   "name":"河图成数","range":"6-10"},
    "3_luoshu":  {"func":t3_luoshu,  "name":"洛书正位","range":"1-9"},
    "4_bianwei": {"func":t4_bianwei, "name":"洛书变位","range":"-4-+4"},
    "5_yinyang": {"func":t5_yinyang, "name":"阴阳消长","range":"-1-1"},
    "6_sancai":  {"func":t6_sancai,  "name":"三才层次","range":"0-1"},
    "7_sixiang": {"func":t7_sixiang, "name":"四象方向","range":"0-3"},
    "8_bagua":   {"func":t8_bagua,   "name":"八卦辨象","range":"0-7"},
    "9_guiyuan": {"func":t9_guiyuan, "name":"归元转化","range":"0-1"},
}

def chain_run(ids, values):
    """链式运算"""
    if len(ids) != len(values):
        return {"error":f"不匹配:{len(ids)}vs{len(values)}"}
    r = {}
    for tid, val in zip(ids, values):
        if tid not in REGISTRY:
            r[tid] = _mk(False, 0, error=f"未知算子:{tid}")
            continue
        try:
            r[tid] = REGISTRY[tid]["func"](val)
        except Exception as e:
            r[tid] = _mk(False, 0, error=str(e))
    return r

def chain_full(values):
    """全九转顺序运算"""
    ids = ["1_sheng","2_cheng","3_luoshu","4_bianwei",
           "5_yinyang","6_sancai","7_sixiang","8_bagua","9_guiyuan"]
    return chain_run(ids, values)

def list_ops():
    return [{"id":k,"name":v["name"],"range":v["range"]} for k,v in REGISTRY.items()]

def apply_all(v):
    """对同一个值应用九转"""
    return chain_full([v]*9)

# === 自测 ===
def self_test():
    tests = {"1_sheng":[1,3,5,0,6],"2_cheng":[6,8,10,5,11],
             "3_luoshu":[1,5,9,0,10],"4_bianwei":[-4,0,4,-5,5],
             "5_yinyang":[-1.0,0.0,1.0],"6_sancai":[0.0,0.5,1.0],
             "7_sixiang":[0,1,2,3,4],"8_bagua":[0,3,5,7,8],
             "9_guiyuan":[0.0,0.5,1.0]}
    passed = 0; failed = 0
    for tid, vals in tests.items():
        func = REGISTRY[tid]["func"]
        for val in vals:
            try:
                r = func(val)
                if r["success"]: passed += 1
                else: failed += 1
            except: failed += 1
    return {"pass":passed, "fail":failed, "total":passed+failed,
            "rate":f"{passed/(passed+failed)*100:.0f}%" if passed+failed>0 else "0%"}

if __name__ == "__main__":
    import json
    r = self_test()
    p = r.get('pass',0)
    fl = r.get('fail',0)
    rt = r.get('rate','0%')
    print('='*50)
    print(f"  九转算子自测: 通过{p} 失败{fl} 通过率{rt}")
    print('='*50)
