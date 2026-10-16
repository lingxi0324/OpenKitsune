#!/usr/bin/env python
"""Find _execute_complex_task method"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Find _execute_complex_task
for i, line in enumerate(lines):
    if "_execute_complex_task" in line or "_execute_complex_task_core" in line:
        start = max(0, i-1)
        end = min(len(lines), i+80)
        print(f"--- line {i+1}: {line} ---")
        for j in range(start, end):
            print(f"{j+1}: {lines[j]}")
        break
