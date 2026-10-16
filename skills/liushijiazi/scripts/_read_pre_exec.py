#!/usr/bin/env python
"""Read _execute_task first half - where _update_next_run is called"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Lines 800-925 to see the first half of _execute_task
for i in range(799, min(len(lines), 928)):
    print(f"{i+1}: {lines[i]}")
