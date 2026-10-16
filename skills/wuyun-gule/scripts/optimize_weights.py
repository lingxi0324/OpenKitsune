"""
四柱权重联合扫描优化器
扫描权重组合 + 阈值 + 月度放大器，找最佳精度
"""
import sys, json, itertools
sys.path.insert(0, '.')
from sizhu_predictor import compute_sizhu_score, PLATES

# 2024实际数据（月涨跌幅%）
ACTUAL = {
    "木": [-12,8,-3,-3,-5,-10,-8,-6,25,0,-4,-3],
    "火": [-18,15,8,-4,-8,-12,-15,-8,37,12,-7,-4],
    "土": [-8,2,-3,0,-2,-2,-3,-5,30,4,-3,-1],
    "金": [2,0,2,-2,-1,1,0,-1,12,5,2,0],
    "水": [3,-1,-1,0,1,2,1,0,-8,-2,0,1],
}

def classify(act, th_up=2, th_mup=0, th_mdown=0, th_down=-2):
    """实际方向"""
    if act > th_up: return 2      # 涨
    elif act > th_mup: return 1   # 微涨
    elif act >= th_mdown: return 0  # 震荡（含0）
    elif act >= th_down: return -1  # 微跌
    else: return -2               # 跌

def predict(scores, th_up=0.30, th_mup=0.05, th_mdown=-0.05, th_down=-0.30):
    """从得分预测方向"""
    if scores >= th_up: return 2
    elif scores >= th_mup: return 1
    elif scores >= th_mdown: return 0
    elif scores >= th_down: return -1
    else: return -2

def accuracy(config):
    """计算总精度"""
    w_y, w_m, w_d, w_h = config["w"]
    th_up, th_mup, th_mdown, th_down = config["t"]
    
    weights = {"year": w_y, "month": w_m, "day": w_d, "hour": w_h}
    
    total_hits = 0
    total_all = 0
    
    for p_idx, plate in enumerate(PLATES):
        for m in range(1, 13):
            score = compute_sizhu_score(plate, 2024, m, weights)
            act = ACTUAL[plate][m-1]
            
            d_pred = predict(score, th_up, th_mup, th_mdown, th_down)
            d_act = classify(act)
            
            ok = (d_pred == d_act) or \
                 (d_pred in (2,1) and d_act in (2,1)) or \
                 (d_pred in (-2,-1) and d_act in (-2,-1))
            
            if ok:
                total_hits += 1
            total_all += 1
    
    return total_hits / total_all * 100

def scan_weights():
    """权重+阈值联合扫描"""
    # 权重组合（归一化）
    w_candidates = [
        # 年,月,日,时
        (0.35,0.30,0.25,0.10),  # 均衡版
        (0.30,0.35,0.25,0.10),  # 月柱主导
        (0.25,0.40,0.25,0.10),  # 月柱更强
        (0.20,0.45,0.25,0.10),  # 月柱再强
        (0.40,0.30,0.20,0.10),  # 年柱主导
        (0.50,0.25,0.15,0.10),  # 年柱更强
        (0.35,0.25,0.25,0.15),  # 时柱更多
        (0.30,0.30,0.30,0.10),  # 三柱均分
        (0.25,0.35,0.30,0.10),  # 月日均强
        (0.20,0.40,0.30,0.10),  # 月日主导
        (0.30,0.35,0.20,0.15),  # 月时结合
        (0.35,0.30,0.15,0.20),  # 时柱实验
        (0.25,0.40,0.20,0.15),  # 月时实验
        (0.40,0.35,0.15,0.10),  # 年月中强
        (0.30,0.30,0.20,0.20),  # 四柱均匀
        (0.20,0.35,0.30,0.15),  # 月日时强
    ]
    
    # 阈值组合
    t_candidates = [
        # 涨,微涨,微跌,跌 cutoff
        (0.30,0.05,-0.05,-0.30),  # 默认
        (0.25,0.05,-0.05,-0.25),  # 略收窄
        (0.20,0.03,-0.03,-0.20),  # 更收窄
        (0.35,0.08,-0.08,-0.35),  # 更宽
        (0.15,0.02,-0.02,-0.15),  # 极窄
        (0.40,0.10,-0.10,-0.40),  # 极宽
        (0.25,0.03,-0.03,-0.25),  # 中窄
        (0.30,0.08,-0.08,-0.30),  # 中宽
    ]
    
    best = {"acc": 0, "config": None}
    results = []
    
    for i, w in enumerate(w_candidates):
        for j, t in enumerate(t_candidates):
            cfg = {"w": w, "t": t}
            acc = accuracy(cfg)
            results.append({"w": w, "t": t, "acc": round(acc, 1)})
            if acc > best["acc"]:
                best["acc"] = acc
                best["config"] = cfg
                print(f"新最优: w={w} t={t} -> acc={acc:.1f}%")
    
    # 排序展示top10
    results.sort(key=lambda x: x["acc"], reverse=True)
    print(f"\n{'='*50}")
    print(f"TOP 10 最优配置:")
    for r in results[:10]:
        print(f"  w={r['w']} t={r['t']} -> {r['acc']}%")
    
    print(f"\n最优: {best}")
    return best

def scan_with_amplifier():
    """带月柱放大因子的扫描"""
    w_candidates = [
        (0.30,0.35,0.25,0.10),  # 月柱主导
        (0.25,0.40,0.25,0.10),  # 月柱更强
        (0.20,0.45,0.25,0.10),  # 月柱最强
        (0.30,0.35,0.20,0.15),  # 月时结合
        (0.25,0.40,0.20,0.15),  # 月时强
    ]
    t_candidates = [
        (0.20,0.03,-0.03,-0.20),  # 窄
        (0.15,0.02,-0.02,-0.15),  # 极窄
        (0.25,0.05,-0.05,-0.25),  # 中
        (0.30,0.05,-0.05,-0.30),  # 默认
    ]
    amp_candidates = [1.0, 1.5, 2.0, 2.5, 3.0]
    
    # 先找到最优无放大
    best = {"acc": 0}
    print("=== 月柱放大扫描 ===")
    for a in amp_candidates:
        for w in w_candidates:
            for t in t_candidates:
                # 用放大后的月柱权重重新计算
                w_adj = list(w)
                w_adj[1] = min(w[1] * a, 0.7)  # 放大但不超过0.7
                # 重新归一化
                total = w_adj[0] + w_adj[1] + w_adj[2] + w_adj[3]
                w_norm = tuple(round(x/total, 3) for x in w_adj)
                
                cfg = {"w": w_norm, "t": t, "amp": a}
                acc = accuracy(cfg)
                if acc > best["acc"]:
                    best["acc"] = acc
                    best["config"] = cfg
                    print(f"  amp={a} w={w_norm} t={t} -> {acc:.1f}%")
    
    print(f"\n最优放大: {best}")
    return best

if __name__ == "__main__":
    print("="*50)
    print("四柱权重联合扫描优化")
    print("="*50)
    
    # 阶段1: 基础权重+阈值扫描
    print("\n=== 阶段1: 基础扫描 ===")
    best1 = scan_weights()
    
    # 阶段2: 月柱放大扫描
    print("\n=== 阶段2: 月柱放大扫描 ===")
    best2 = scan_with_amplifier()
    
    print(f"\n最终结果: {best1['acc']:.1f}% vs {best2['acc']:.1f}%")
