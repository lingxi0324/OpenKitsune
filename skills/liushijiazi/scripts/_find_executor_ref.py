#!/usr/bin/env python
"""Find how scheduler creates executor"""
from pathlib import Path

f = Path(r"I:\ai\openakita-main\src\leiwa\scheduler\scheduler.py")
lines = f.read_text(encoding="utf-8").split("\n")

# Find executor references
for i, line in enumerate(lines):
    if any(kw in line for kw in ["executor", "TaskExecutor", "_executor", "self.executor"]):
        ctx_start = max(0, i-2)
        ctx_end = min(len(lines), i+3)
        for j in range(ctx_start, ctx_end):
            print(f"{j+1}: {lines[j]}")
        print("---")
