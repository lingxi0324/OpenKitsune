#!/usr/bin/env python
"""Read executor.py from line 1014 onwards to see the rest of _system_daily_memory"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Show from line 1014
for i in range(1013, min(len(lines), 1100)):
    print(f"{i+1}: {lines[i]}")
