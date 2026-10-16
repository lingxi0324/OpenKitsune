"""检查 judge_keqi_pattern 返回值"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shengfu_yufa import judge_keqi_pattern

print("2024年各气段主客气格局：")
for qi in range(1, 7):
    result = judge_keqi_pattern(2024, qi)
    print(f"  气{qi}: {result}")

print()
print("2025年各气段主客气格局：")
for qi in range(1, 7):
    result = judge_keqi_pattern(2025, qi)
    print(f"  气{qi}: {result}")
