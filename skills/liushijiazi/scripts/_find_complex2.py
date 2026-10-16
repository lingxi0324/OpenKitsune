#!/usr/bin/env python
"""Find _execute_complex_task and _execute_complex_task_core"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

for i, line in enumerate(lines):
    if "def _execute_complex_task" in line:
        start = max(0, i-1)
        end = min(len(lines), i+120)
        print(f"--- line {i+1}: {line} ---")
        for j in range(start, end):
            print(f"{j+1}: {lines[j]}")
        break
