"""对corrected_scoring.py应用v4.1修正"""
import shutil
import os

# 读取源文件
with open('corrected_scoring.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 备份
shutil.copy2('corrected_scoring.py', 'corrected_scoring_v40.py.bak')

# 1. 更新文档头
code = code.replace(
    '胜复校正评分引擎 v4.0 · 四层全链路评分校正',
    '胜复校正评分引擎 v4.1 · 四层全链路评分校正'
)
code = code.replace(
    '【v4.0 八项修正 — v3.2矫枉过正，恢复信号区分度】',
    '【v4.1 六项修正 — 补全土负向信号区，提升郁发捕捉力，加宽火评分范围】'
)

v41_notes = '''
【v4.1 六项修正 — 补全土负向信号区，提升郁发捕捉力，加宽火评分范围】
  ① 土季节阻尼：冬(水旺克土)加负 -0.06/-0.04，春(木旺克土)中性，长夏保留正 +0.08
  ② 郁发释放 0.40→0.55、触发阈值 0.08→0.06（大幅提升极端反弹捕捉力）
  ③ 复气积累 0.15→0.18（被压板块积蓄更快）
  ④ 均值回归 0.02→0.015（保留正向信号不被快速拉回）
  ⑤ 太过反制 0.30→0.25（偏弱信号减反制，留更多空间）
  ⑥ 岁运太过加成 0.25→0.22（防止土在势旺时独大）
'''

code = code.replace(
    '【v3.2 七大修正 — 修复板块系统性正偏/负偏，翻正相关系数】',
    f'{v41_notes}【v3.2 七大修正 — 修复板块系统性正偏/负偏，翻正相关系数】'
)

# 2. 土季节阻尼：补全负向
# old: "土": {3: 0.06, 6: 0.06, 9: 0.06, 12: 0.06},
old_tu = '"土": {3: 0.06, 6: 0.06, 9: 0.06, 12: 0.06}'
new_tu = '"土": {1: -0.06, 2: -0.04, 6: 0.08, 7: 0.06, 8: 0.04, 11: -0.04, 12: -0.06}'
code = code.replace(old_tu, new_tu)

# 3. 郁发触发阈值 0.08→0.06
code = code.replace(
    '    if accum > 0.08 and (month - last_eruption) >= 2:',
    '    if accum > 0.06 and (month - last_eruption) >= 2:'
)

# 4. 郁发释放 0.40→0.55
code = code.replace(
    '        release = accum * 0.40',
    '        release = accum * 0.55'
)

# 5. 复气积累 0.15→0.18
code = code.replace(
    '        accumulation_inc = abs(qi_factor) * 0.15',
    '        accumulation_inc = abs(qi_factor) * 0.18'
)

# 6. 均值回归 0.02→0.015
code = code.replace(
    '    MR_STRENGTH = 0.02',
    '    MR_STRENGTH = 0.015'
)

# 7. 太过反制 0.30→0.25
code = code.replace(
    '        suppression = -excess * 0.30',
    '        suppression = -excess * 0.25'
)

# 8. 岁运太过加成 0.25→0.22
# Only change the actual score addition, not the signal display
code = code.replace(
    '            score += strength * 0.25 * keqi_mod',
    '            score += strength * 0.22 * keqi_mod'
)
# Fix signal display to match actual value
code = code.replace(
    'f"岁运太过-调{keqi_mod:.1f}+{strength*0.40*keqi_mod:.3f}"',
    'f"岁运太过-调{keqi_mod:.1f}+{strength*0.22*keqi_mod:.3f}"'
)

with open('corrected_scoring.py', 'w', encoding='utf-8') as f:
    f.write(code)

print('✅ v4.1 修正已写入 corrected_scoring.py')
print(f'总字符数: {len(code)}')
