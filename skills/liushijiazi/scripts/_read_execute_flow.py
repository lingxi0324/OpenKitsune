#!/usr/bin/env python
"""Read executor.py execute method flow to see how _system_daily_memory is called"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Show lines 103-200 (first part of execute method)
for i in range(102, min(len(lines), 210)):
    print(f"{i+1}: {lines[i]}")
