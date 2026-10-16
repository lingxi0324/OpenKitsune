"""快速运行四层棘轮"""
import sys, os
SCRIPT_DIR = r"I:\ai\openakita-main\skills\wuyun-gule\scripts"
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

import four_layer_ratchet
results = four_layer_ratchet.run_full_validation([2024, 2025])

# 打印关键结果
for yr in [2024, 2025]:
    b = results.get(yr, {}).get("best", {})
    print(f"\n{yr}年 最优: {b.get('accuracy', 0):.2%} ({b.get('correct',0)}/{b.get('total',0)})")
    print(f"  权重: {b.get('weights', {})}")
    print(f"  板块: {b.get('plate_accuracy', {})}")

cv = results.get("cross_year", {})
print(f"\n跨年泛化: {cv.get('y2024_weights_on_2025', 0):.2%}")
