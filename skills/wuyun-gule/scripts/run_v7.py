#!/usr/bin/env python3
"""v7验证运行器 - 适配five_elements_monthly_returns.csv的实际列格式"""
import sys, os, csv, random, math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from corrected_scoring_v7 import (
    compute_corrected_score, calc_pearsonr, bootstrap_ci, PLATES
)

COL_MAP = {'金':1, '木':3, '水':5, '火':7, '土':9}

def load_data(csv_path):
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 11:
                continue
            parts = row[0].strip().split('-')
            if len(parts) != 2:
                continue
            year, month = int(parts[0]), int(parts[1])
            entry = {'year': year, 'month': month}
            for wx in PLATES:
                try:
                    entry[wx] = float(row[COL_MAP[wx]])
                except (ValueError, IndexError):
                    entry[wx] = None
            data.append(entry)
    print(f"[加载] {len(data)}条有效记录")
    return data

def run_val(data, enable_zk=True):
    results = {}
    for wx in PLATES:
        scores, actuals = [], []
        for d in data:
            a = d.get(wx)
            if a is None or abs(a) < 0.001 or abs(a) > 50:
                continue
            s, _ = compute_corrected_score(wx, d['year'], d['month'], {}, {}, enable_zk)
            scores.append(s); actuals.append(a)
        n = len(scores)
        r, rm, cl, ch, pp = bootstrap_ci(scores, actuals, 5000)
        results[wx] = {'n':n, 'r':round(r,4), 'm':round(rm,4),
                       'ci':[round(cl,4),round(ch,4)], 'pp':round(pp,1),
                       'sig': cl>0 or ch<0}
    return results

def print_r(rs, label):
    print(f"\n{'='*60}\n  {label}\n{'='*60}")
    print(f"{'行':>4} {'样本':>6} {'r':>8} {'中位':>8} {'95%CI':>16} {'正%':>7} {'显著':>6}")
    print("-"*60)
    for wx in PLATES:
        r = rs[wx]
        print(f"{wx:>4} {r['n']:>6} {r['r']:>8.4f} {r['m']:>8.4f} [{r['ci'][0]:.3f},{r['ci'][1]:.3f}] {r['pp']:>6.1f}% {'✅' if r['sig'] else '❌':>6}")

def leave_one_year(data):
    years = sorted(set(d['year'] for d in data))
    print(f"\n{'='*60}\n  土板块留年·v7\n{'='*60}")
    for ty in years:
        sa, aa = [], []
        for d in data:
            if d['year'] != ty: continue
            a = d.get('土')
            if a is None or abs(a) < 0.001 or abs(a) > 50: continue
            s, _ = compute_corrected_score('土', d['year'], d['month'], {}, {}, True)
            sa.append(s); aa.append(a)
        if len(sa) >= 3:
            print(f"  留{ty}: r={calc_pearsonr(sa,aa):.4f} (n={len(sa)})")

if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else ''
    if not csv_path or not os.path.exists(csv_path):
        csv_path = os.path.join(SCRIPT_DIR, '..', '..', '..', '..', 'data', 'temp', 'five_elements_monthly_returns.csv')
    if not os.path.exists(csv_path):
        print(f"找不到数据文件，请指定路径")
        sys.exit(1)
    data = load_data(csv_path)
    v7on = run_val(data, True)
    v7off = run_val(data, False)
    print_r(v7on, "v7.0 主客运分步 ON")
    print_r(v7off, "v7.0 主客运分步 OFF(v6基线)")
    print(f"\n{'='*60}\n  对比: v6 vs v7\n{'='*60}")
    print(f"{'行':>4} {'v6 r':>8} {'v7 r':>8} {'v6中位':>8} {'v7中位':>8} {'v6正%':>7} {'v7正%':>7} {'变化':>8}")
    print("-"*60)
    for wx in PLATES:
        o, n = v7off[wx], v7on[wx]
        print(f"{wx:>4} {o['r']:>8.4f} {n['r']:>8.4f} {o['m']:>8.4f} {n['m']:>8.4f} {o['pp']:>6.1f}% {n['pp']:>6.1f}% {n['r']-o['r']:>+8.4f}")
    leave_one_year(data)
