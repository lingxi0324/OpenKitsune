"""检查 batch_corrected_predict 输出格式"""
import sys, os
sys.path.insert(0, r'I:\ai\openakita-main\skills\wuyun-gule\scripts')
os.chdir(r'I:\ai\openakita-main\skills\wuyun-gule\scripts')

from corrected_scoring import batch_corrected_predict, PLATES

result = batch_corrected_predict(2024)
print(f"类型: {type(result)}")

if isinstance(result, dict):
    keys = sorted(result.keys())
    print(f"字典键数: {len(keys)}")
    print(f"第一个键: {keys[0]}, 值类型: {type(result[keys[0]])}")
    print(f"示例值: {result[keys[0]]}")
elif isinstance(result, list):
    print(f"列表长度: {len(result)}")
    print(f"第一个元素类型: {type(result[0])}")
    if hasattr(result[0], '__iter__'):
        print(f"第一个元素内容: {list(result[0])}")
    else:
        print(f"第一个元素内容: {result[0]}")

# 同时观察一下评分分布
scores_by_plate = {p: [] for p in PLATES}
if isinstance(result, list):
    for month_data in result:
        if isinstance(month_data, dict) and 'month' in month_data:
            for p in PLATES:
                scores_by_plate[p].append(month_data.get(p, 0))
elif isinstance(result, dict):
    for k, v in result.items():
        for p in PLATES:
            scores_by_plate[p].append(v.get(p, 0))
else:
    print(f"末知的格式: {result}")

print(f"\n各板块评分统计:")
for p in PLATES:
    vals = scores_by_plate[p]
    if vals:
        print(f"  {p}: 范围 [{min(vals):+.4f}, {max(vals):+.4f}], 均值 {sum(vals)/len(vals):+.4f}")
