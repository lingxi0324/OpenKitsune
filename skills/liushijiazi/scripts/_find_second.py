#!/usr/bin/env python
"""Search for _system_daily_memory method in the codebase"""
import re
from pathlib import Path

base = Path(r"I:\ai\openakita-main\src\leiwa")

found = False
for py_file in sorted(base.rglob("*.py")):
    rel = py_file.relative_to(base)
    content = py_file.read_text(encoding="utf-8", errors="replace")
    if "_system_daily_memory" in content:
        found = True
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "_system_daily_memory" in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 50)
                print(f"\n{'='*60}")
                print(f"📄 {rel} (line {i+1})")
                print(f"{'='*60}")
                for j in range(start, end):
                    marker = ">>>" if j == i else "   "
                    print(f"{marker} {j+1}: {lines[j]}")

if not found:
    # Also search for system_daily_memory (without underscore)
    for py_file in sorted(base.rglob("*.py")):
        rel = py_file.relative_to(base)
        content = py_file.read_text(encoding="utf-8", errors="replace")
        if "system_daily_memory" in content and "_system_daily_memory" not in content:
            found = True
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if "system_daily_memory" in line:
                    start = max(0, i - 2)
                    end = min(len(lines), i + 50)
                    print(f"\n{'='*60}")
                    print(f"📄 {rel} (line {i+1})")
                    print(f"{'='*60}")
                    for j in range(start, end):
                        marker = ">>>" if j == i else "   "
                        print(f"{marker} {j+1}: {lines[j]}")

if not found:
    print("❌ 未找到 _system_daily_memory")
