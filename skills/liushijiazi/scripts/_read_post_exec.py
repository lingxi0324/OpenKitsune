#!/usr/bin/env python
"""Read scheduler.py _execute_task method continuation after executor call"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Find the continuation after executor call (around line 930-1000)
for i in range(926, min(len(lines), 1050)):
    print(f"{i+1}: {lines[i]}")
