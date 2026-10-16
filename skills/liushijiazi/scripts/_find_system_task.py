#!/usr/bin/env python
"""Find _execute_system_task in executor.py"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

in_func = False
for i, line in enumerate(lines):
    if "def _execute_system_task" in line:
        start = max(0, i-1)
        end = min(len(lines), i+100)
        print(f"--- line {i+1}: {line} ---")
        for j in range(start, end):
            print(f"{j+1}: {lines[j]}")
        break
