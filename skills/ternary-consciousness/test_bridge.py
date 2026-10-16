import sys, os, json
sys.path.insert(0, r'I:\ai\openakita-main\skills\ternary-consciousness')
from ternary.nine_bridge import sync_consciousness_to_nine, grid_to_nine_coords, get_ternary_snapshot
print('=== Nine Bridge Test ===')
result = sync_consciousness_to_nine()
print(f'Grid: {result["grid"]}')
print(f'Coords: {json.dumps(result["九维坐标"])}')
print(f'Nine-match: {result.get("九转匹配")}')
print(f'Tide: {result.get("潮汐")}')
print('OK: Bridge integration valid')
