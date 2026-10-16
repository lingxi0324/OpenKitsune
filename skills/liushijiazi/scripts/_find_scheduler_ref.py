#!/usr/bin/env python
"""Find how executor accesses scheduler"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\executor.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Show class definition and __init__
for i, line in enumerate(lines):
    if any(kw in line for kw in ["class TaskExecutor", "def __init__", "self.scheduler", "self._scheduler", "executor."]):
        print(f"{i+1}: {line}")
