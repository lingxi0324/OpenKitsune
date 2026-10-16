#!/usr/bin/env python
"""Find run_task method in scheduler.py"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Search for def run_task  
for i, line in enumerate(lines):
    if "run_task" in line or "def run" in line:
        start = max(0, i-2)
        end = min(len(lines), i+60)
        print(f"--- line {i+1} ---")
        for j in range(start, end):
            print(f"{j+1}: {lines[j]}")
        print()
        break
