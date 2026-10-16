#!/usr/bin/env python
"""Read executor.py __init__"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Show lines 25-100
for i in range(24, min(len(lines), 120)):
    print(f"{i+1}: {lines[i]}")
