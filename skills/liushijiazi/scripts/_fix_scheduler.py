#!/usr/bin/env python
"""In-place patch scheduler.py - fix next_run when last_run is None"""
from pathlib import Path

target = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
content = target.read_text(encoding="utf-8")

old = 'task.next_run = trigger.get_next_run_time(task.last_run)'
new = 'task.next_run = trigger.get_next_run_time(task.last_run or datetime.now())'

count = content.count(old)
print(f"找到 {count} 处匹配")

content = content.replace(old, new, 1)
target.write_text(content, encoding="utf-8")
print(f"✅ 修改已应用")

# Verify
verify = target.read_text(encoding="utf-8")
if new in verify:
    print("✅ 验证通过：新代码已写入")
else:
    print("❌ 验证失败")
