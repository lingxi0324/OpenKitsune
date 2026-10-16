"""检查corrected_scoring.py的实际版本"""
with open('corrected_scoring.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
print(f'总行数: {len(lines)}')
for i, ln in enumerate(lines[:15]):
    s = ln.rstrip()
    if s:
        print(f'L{i+1}: {s}')
# 找所有版本标记
for i, ln in enumerate(lines):
    s = ln.strip()
    if 'v' in s.lower() and ('v3' in s.lower() or 'v4' in s.lower() or 'v2' in s.lower() or 'v1' in s.lower() or 'v5' in s.lower()):
        if 'ver' in s.lower() or 'v' in s.lower():
            print(f'版本标记 L{i+1}: {s[:120]}')
# 找关键函数
print()
print('函数列表:')
for i, ln in enumerate(lines):
    s = ln.strip()
    if s.startswith('def '):
        print(f'  L{i+1}: {s}')
