"""快速测试：跑四层回测并输出关键指标"""
import os, sys
sys.path.insert(0, r'I:\ai\openakita-main\skills\wuyun-gule\scripts')
os.chdir(r'I:\ai\openakita-main\skills\wuyun-gule\scripts')

from four_layer_backtest import run_backtest
from corrected_scoring import correlation_analysis
from diagnose import load_test_suite
from corrected_scoring import PLATES

# 1. 相关系数
test_data = load_test_suite()
corrs = correlation_analysis(test_data)
print("=== 相关系数 v4.0 ===")
for p in PLATES:
    mark = "🟢" if corrs[p] > 0.1 else ("🔴" if corrs[p] < -0.1 else "⚪")
    print(f"  {p}: {mark} r = {corrs[p]:.4f}")

# 2. 四层回测摘要
result = run_backtest()
print(f"\n=== 四层框架摘要 ===")
print(f"  A(胜复): {result['baseline']['strict_rate']:.1%} ({result['baseline']['strict_correct']}/{result['baseline']['strict_total']})")
print(f"  B(+资本): {result['with_capital']['strict_rate']:.1%} ({result['with_capital']['strict_correct']}/{result['with_capital']['strict_total']})")
print(f"  C(四层):   {result['four_layer']['strict_rate']:.1%} ({result['four_layer']['strict_correct']}/{result['four_layer']['strict_total']})")

# 3. 个股精度
print(f"\n  🏆 综合: {result['composite_rate']:.1f}%")
