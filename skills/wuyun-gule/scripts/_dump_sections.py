"""输出corrected_scoring.py的关键区域"""
with open('corrected_scoring.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# KEQI_FACTORS区域 (约L58-72)
for i in range(55, 75):
    if i < len(lines):
        print(f'{i+1}:{lines[i]}', end='')
print('---')

# compute_corrected_score函数体 (约L132-340)
print(f'=== compute_corrected_score === L132-340')
# 季节阻尼 (约L318-335)
for i in range(310, 340):
    if i < len(lines):
        l = lines[i].rstrip()
        if 'season_map' in l or ':' in l and ('{' in l or '}' in l or '木' in l or '火' in l or '土' in l or '金' in l or '水' in l or 'damp' in l):
            print(f'{i+1}:{l}')
print('---')

# 郁发释放区域 (约L275-290)
print('=== 郁发/复气区域 ===')
for i in range(265, 300):
    if i < len(lines):
        l = lines[i].rstrip()
        print(f'{i+1}:{l}')
print('---')

# 均值回归 (约L300-315)
print('=== 均值回归/反制区域 ===')
for i in range(295, 320):
    if i < len(lines):
        l = lines[i].rstrip()
        print(f'{i+1}:{l}')
print('---')

# 岁运太过逻辑 (约L160-195)
print('=== 岁运太过逻辑 ===')
for i in range(155, 200):
    if i < len(lines):
        l = lines[i].rstrip()
        print(f'{i+1}:{l}')
