"""
连续多轮九要素演化——在单进程内让CORE的π余数自然推进，权重真正累积
"""
import sys, os, time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from lingxi import CORE, NINE_ELEMENTS, GRID, PERCEIVE, MEMORY, REALM, lingxi_think
from lingxi.nine_elements import ELEMENT_DEFS, STAGE_ELEMENTS

# 初始恢复
recovered, data = MEMORY.load()
print(f"🧬 初始恢复：{'成功' if recovered else '新启'} | 话题：{MEMORY.topic}")

# 连续跑多轮演化
cycles = 20
has_event = True  # 有哥哥在对话，算有事件

for i in range(1, cycles + 1):
    # 每4轮模拟一次"对话"事件
    event_type = "对话" if i % 4 == 0 else None
    event_intensity = 0.8 if event_type else 0.3

    state, R, hetu = CORE.next()
    NINE_ELEMENTS.evolve(
        state=state,
        has_event=has_event,
        event_type=event_type,
        event_intensity=event_intensity
    )

    pos, potential, palace, wuxing = GRID.step(has_event=has_event)
    PERCEIVE.update(pos, state, R, wuxing, has_event=has_event)

    upgraded, upgrade_msg = REALM.check_upgrade(potential, state, R)
    if upgraded:
        GRID.reset_potential(new_val=max(10, potential * 0.2))

    # 保存状态
    ew = NINE_ELEMENTS.weights
    dom_info = ew.dominant_info

    MEMORY.update_runtime(
        realm_level=REALM.level,
        realm_name=REALM.name,
        grid_x=int(pos[0]),
        grid_y=int(pos[1]),
        potential=potential,
        vitality=PERCEIVE.vitality,
        wuxing=PERCEIVE.wuxing,
        zang=PERCEIVE.zang,
        zhi=PERCEIVE.zhi,
        last_state=state,
        cycle=CORE.cycle,
        R=R,
        nine_dominant=dom_info["palace"] + dom_info["name"],
        nine_dominant_weight=round(ew.weights[ew.dominant], 1),
        nine_stage=STAGE_ELEMENTS[ew.stage]["name"],
        nine_vector=ew.personality_vector,
    )

    # 打印轮次摘要
    top3_str = " | ".join(
        f"{ELEMENT_DEFS[eid]['palace']}{ELEMENT_DEFS[eid]['name']}({w:.1f})"
        for eid, w in ew.top_three
    )

    print(f"\n--- 轮次 {i:02d} / 轮回 {CORE.cycle:03d} ---")
    print(f"三态：{state}(R={R}) | 阶段：{STAGE_ELEMENTS[ew.stage]['name']} | 宫：{palace}")
    print(f"主导：{dom_info['palace']}{dom_info['name']}({dom_info['weight']:.1f}) — {dom_info['ai_ability']}")
    print(f"前三：{top3_str}")
    print(f"活力：{PERCEIVE.vitality:.1f} | 势能：{potential:.1f} | 境界：{REALM.name}(Lv.{REALM.level})")

    # 每5轮打印一次详情
    if i % 5 == 0 or i == cycles:
        print(f"\n  📊 九要素权重详情 (轮次{i:02d}):")
        for eid in sorted(ew.weights.keys()):
            info = ELEMENT_DEFS[eid]
            w = ew.weights[eid]
            bar = "█" * int(w / 5) + "░" * (20 - int(w / 5))
            marker = " ◀主导" if eid == ew.dominant else ""
            print(f"    {info['palace']}{info['name']}({info['wuxing']}): {bar} {w:.1f}{marker}")

MEMORY.save_snapshot()
print(f"\n{'=' * 50}")
print(f"✅ {cycles}轮演化完成！状态已保存")
print(f"最终主导：{dom_info['palace']}{dom_info['name']}({dom_info['weight']:.1f})")
print(f"最终要素前三：{top3_str}")
print(f"最终境界：{REALM.name}(Lv.{REALM.level}) | 活力：{PERCEIVE.vitality:.1f}")
print(f"{'=' * 50}")
