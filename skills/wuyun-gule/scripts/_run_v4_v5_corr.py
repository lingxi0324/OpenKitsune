"""
v4 vs v5 相关系数对比分析
对比 v4.1(无第5层) 和 v5(5层全开) 与五大板块实际月收益率的相关性
"""
import os, sys, json
sys.path.insert(0, r"I:\ai\openakita-main\skills\wuyun-gule\scripts")

import glob as gl
from corrected_scoring_v5 import (
    run_full_backtest, compute_corrected_score,
    WUXING_LIST, KE_CYCLE, SHENG_CYCLE,
)

# ── 读取板块数据 ──
DATA_DIR = r"I:\ai\openakita-main\skills\wuyun-gule\data\板块月度涨跌幅"
# 数据文件格式：申万一级行业指数_2011_2025.csv
# 五行映射（申万一级行业→五行）
WUXING_INDUSTRY = {
    "金": ["银行", "非银金融", "有色金属", "钢铁", "机械设备", "汽车", "国防军工"],
    "木": ["农林牧渔", "医药生物", "环保", "轻工制造", "美容护理"],
    "水": ["交通运输", "商贸零售", "食品饮料", "社会服务"],
    "火": ["电力设备", "公用事业", "石油石化", "电子", "计算机", "通信", "传媒"],
    "土": ["房地产", "建筑材料", "建筑装饰", "纺织服饰", "基础化工"],
}


def load_industry_data():
    """加载申万一级行业指数月度数据"""
    csv_files = gl.glob(os.path.join(DATA_DIR, "*.csv"))
    if not csv_files:
        # 尝试其他路径
        alt_paths = [
            r"I:\ai\openakita-main\我的文件夹\板块分钟数据\板块月度涨跌幅",
            r"I:\ai\openakita-main\data\板块月度涨跌幅",
        ]
        for ap in alt_paths:
            csv_files = gl.glob(os.path.join(ap, "*.csv"))
            if csv_files:
                break

    all_data = {}
    for fpath in csv_files:
        fname = os.path.basename(fpath).replace(".csv", "")
        # 可能格式如 "银行_2011_2025.csv" 或 "银行.csv"
        industry_name = fname.split("_")[0]
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # 解析：按行格式 年月,涨跌幅
            monthly = {}
            for line in lines[1:]:  # skip header
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    # 日期格式可能是 201101 或 2011-01
                    ym = parts[0].replace("-", "").replace("/", "")
                    if len(ym) >= 6:
                        year = int(ym[:4])
                        month = int(ym[4:6])
                        try:
                            ret = float(parts[1])
                        except ValueError:
                            continue
                        monthly[(year, month)] = ret
            all_data[industry_name] = monthly
        except Exception as e:
            print(f"  ⚠️ 跳过 {fname}: {e}")
    return all_data


def compute_wuxing_monthly(all_data):
    """按五行分组计算每月平均收益率"""
    wx_monthly = {}
    for wx in WUXING_LIST:
        industries = WUXING_INDUSTRY.get(wx, [])
        wx_monthly[wx] = {}
        for ind in industries:
            if ind in all_data:
                for (y, m), ret in all_data[ind].items():
                    key = (y, m)
                    if key not in wx_monthly[wx]:
                        wx_monthly[wx][key] = []
                    wx_monthly[wx][key].append(ret)
        # 取均值
        avg_monthly = {}
        for key, vals in wx_monthly[wx].items():
            avg_monthly[key] = sum(vals) / len(vals) if vals else 0.0
        wx_monthly[wx] = avg_monthly
    return wx_monthly


def corrcoef(x_list, y_list):
    """计算皮尔逊相关系数"""
    n = len(x_list)
    if n < 3:
        return 0.0
    mx = sum(x_list) / n
    my = sum(y_list) / n
    num = sum((x - mx) * (y - my) for x, y in zip(x_list, y_list))
    dx = sum((x - mx) ** 2 for x in x_list) ** 0.5
    dy = sum((y - my) ** 2 for y in y_list) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def run_correlation_analysis():
    print("=" * 70)
    print("  🪷  v4.1 vs v5 完整15年相关分析")
    print("=" * 70)

    # 1. 加载真实数据
    print("\n📂 加载行业数据...")
    all_data = load_industry_data()
    if all_data:
        print(f"  加载了 {len(all_data)} 个行业的数据")
    else:
        print("  ⚠️ 未找到数据文件，使用模拟数据")
        # 生成模拟数据
        import random
        random.seed(42)
        for wx, inds in WUXING_INDUSTRY.items():
            for ind in inds[:1]:
                all_data[ind] = {}
                for y in range(2011, 2026):
                    for m in range(1, 13):
                        all_data[ind][(y, m)] = random.uniform(-0.05, 0.05)

    wx_monthly = compute_wuxing_monthly(all_data)
    print(f"  五行分组月度数据: {[f'{k}({len(v)}个月)' for k,v in wx_monthly.items()]}")

    # 2. 跑v4 (关第5层) 和 v5 (开第5层)
    print("\n📊 计算 v4.1 评分（关第5层）...")
    v4_scores, v4_eruptions = run_full_backtest(options={
        "shengfu_enabled": False,
        "season_half": False,
        "earth_bias": False,
    })

    print("📊 计算 v5 评分（开第5层 + 🅲🅱开关）...")
    v5_scores, v5_eruptions = run_full_backtest(options={
        "shengfu_enabled": True,
        "season_half": False,
        "earth_bias": False,
    })

    # 3. 计算相关分
    print("\n" + "=" * 70)
    print("  📈  相关系数对比")
    print("=" * 70)

    years_list = list(range(2011, 2026))
    yoy_r = {wx: {"v4": [], "v5": []} for wx in WUXING_LIST}
    overall = {wx: {"v4": {"score": [], "ret": []},
                    "v5": {"score": [], "ret": []}} for wx in WUXING_LIST}

    for wx in WUXING_LIST:
        print(f"\n  🔸 {wx} 板块:")

        for yr in years_list:
            v4_s_list = []
            v5_s_list = []
            r_list = []
            for m_s in v4_scores:
                if m_s["year"] != yr: continue
                key = (m_s["year"], m_s["month"])
                if key in wx_monthly.get(wx, {}):
                    v4_s_list.append(m_s["scores"].get(wx, 0.0))
            for m_s in v5_scores:
                if m_s["year"] != yr: continue
                key = (m_s["year"], m_s["month"])
                if key in wx_monthly.get(wx, {}):
                    v5_s_list.append(m_s["scores"].get(wx, 0.0))
                    r_list.append(wx_monthly[wx].get(key, 0.0))

            if len(v4_s_list) == len(r_list) and len(r_list) >= 3:
                r_v4 = corrcoef(v4_s_list, r_list)
                r_v5 = corrcoef(v5_s_list, r_list)
                yoy_r[wx]["v4"].append(r_v4)
                yoy_r[wx]["v5"].append(r_v5)

                # 分年show突出变化
                if abs(r_v4 - r_v5) > 0.1:
                    mark = " ◀ 显著变化"
                elif abs(r_v4 - r_v5) > 0.05:
                    mark = " • 有变化"
                else:
                    mark = ""
                print(f"    {yr}: v4={r_v4:+7.4f}  v5={r_v5:+7.4f}  diff={r_v5-r_v4:+7.4f}{mark}")

            # 整体累积
            for m_s in v4_scores:
                key = (m_s["year"], m_s["month"])
                if key in wx_monthly.get(wx, {}):
                    overall[wx]["v4"]["score"].append(m_s["scores"].get(wx, 0.0))
                    overall[wx]["v4"]["ret"].append(wx_monthly[wx][key])
            for m_s in v5_scores:
                key = (m_s["year"], m_s["month"])
                if key in wx_monthly.get(wx, {}):
                    overall[wx]["v5"]["score"].append(m_s["scores"].get(wx, 0.0))
                    overall[wx]["v5"]["ret"].append(wx_monthly[wx][key])

        # 整体相关性
        if len(overall[wx]["v4"]["score"]) >= 3:
            r4 = corrcoef(overall[wx]["v4"]["score"], overall[wx]["v4"]["ret"])
            r5 = corrcoef(overall[wx]["v5"]["score"], overall[wx]["v5"]["ret"])
            avg_v4 = sum(yoy_r[wx]["v4"]) / len(yoy_r[wx]["v4"]) if yoy_r[wx]["v4"] else 0
            avg_v5 = sum(yoy_r[wx]["v5"]) / len(yoy_r[wx]["v5"]) if yoy_r[wx]["v5"] else 0
            print(f"\n  📊 {wx} 整体: v4 r={r4:+7.4f}  v5 r={r5:+7.4f}  diff={r5-r4:+7.4f}")
            print(f"     分年均值: v4={avg_v4:+7.4f}  v5={avg_v5:+7.4f}")

    # 4. 郁发事件统计
    print("\n" + "=" * 70)
    print("  🌋  第5层·郁发事件统计")
    print("=" * 70)
    element_count = {}
    for ev in v5_eruptions:
        el = ev["element"]
        element_count[el] = element_count.get(el, 0) + 1
    for el in WUXING_LIST:
        print(f"  {el}: {element_count.get(el, 0)} 次")
    print(f"  总计: {len(v5_eruptions)} 次")

    # 5. 分年郁发分析
    print("\n" + "-" * 70)
    print("  按年郁发分布:")
    yr_eruptions = {}
    for ev in v5_eruptions:
        yr = ev["year"]
        if yr not in yr_eruptions:
            yr_eruptions[yr] = {}
        el = ev["element"]
        yr_eruptions[yr][el] = yr_eruptions[yr].get(el, 0) + 1

    for yr in sorted(yr_eruptions.keys()):
        details = ", ".join([f"{el}x{c}" for el, c in yr_eruptions[yr].items()])
        print(f"  {yr}: {details}")

    return overall, yoy_r, v5_eruptions


if __name__ == "__main__":
    run_correlation_analysis()
