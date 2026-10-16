#!/usr/bin/env python
"""Read scheduler.py run_task method - the task execution handling flow"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Find run_task method
in_run_task = False
found_lines = []
for i, line in enumerate(lines):
    if "async def run_task" in line:
        in_run_task = True
    if in_run_task:
        found_lines.append((i, line))
        if len(found_lines) > 80:
            break

for idx, (i, line) in enumerate(found_lines):
    print(f"{i+1}: {line}")
