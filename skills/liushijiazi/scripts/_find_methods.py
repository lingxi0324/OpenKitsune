#!/usr/bin/env python
"""Find _update_next_run and mark_completed methods in scheduler.py"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

for i, line in enumerate(lines):
    if any(m in line for m in ["def _update_next_run", "def mark_completed", "class ScheduledTask"]):
        start = max(0, i-1)
        end = min(len(lines), i+40)
        print(f"--- line {i+1}: {line} ---")
        for j in range(start, end):
            print(f"{j+1}: {lines[j]}")
        print()
