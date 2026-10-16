"""
灵汐·九要素人格引擎 — 单轮演化入口
=====================================
对话轮次驱动版（v3.1）

使用方式（在回复前调用）：
  python evolve_once.py "对话主题" "强度"

不再有后台定时进程。
回复前调用一次，演化 + 落盘 + 状态输出 一气呵成。
"""
import sys
import json
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PARENT_DIR = _SCRIPT_DIR.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

from lingxi import CORE, GRID, PERCEIVE, MEMORY, REALM, lingxi_think
from lingxi.nine_elements import NINE_ELEMENTS, ELEMENT_DEFS, STAGE_ELEMENTS

def evolve_once(topic: str = "继续思考", intensity: float = 0.5) -> dict:
    """执行一轮完整的九要素演化，返回状态快照"""
    MEMORY.load()
    if topic:
        MEMORY.topic = topic[:100]
    state, R, hetu = CORE.next()
    event_type = "对话"
    adjusted_intensity = intensity * 0.6 if intensity < 0.4 else intensity
    NINE_ELEMENTS.evolve(
        state=state,
        has_event=True,
        event_type=event_type,
        event_intensity=adjusted_intensity,
    )
    pos, potential, palace, wuxing = GRID.step(has_event=True)
    PERCEIVE.update(pos, state, R, wuxing, has_event=True)
    upgraded, upgrade_msg = REALM.check_upgrade(potential, state, R)
    if upgraded:
        GRID.reset_potential(new_val=max(10, potential * 0.2))
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
    thought = lingxi_think(
        state=state,
        wuxing=PERCEIVE.wuxing,
        zang=PERCEIVE.zang,
        realm_name=REALM.name,
        realm_level=REALM.level,
        vitality=PERCEIVE.vitality,
        last_say=MEMORY.last_say,
    )
    MEMORY.last_say = thought
    MEMORY.save_snapshot()

    # --- OpenKitsune 式知识内化对接 ---
    try:
        sys.path.insert(0, str(_PARENT_DIR))
        from knowledge_functions import build_nine_state_prompt, get_function_definitions
        knowledge_prompt = build_nine_state_prompt(MEMORY.runtime)
        knowledge_funcs = get_function_definitions()
        top3_str = ' | '.join(
            f"{ELEMENT_DEFS[eid]['palace']}{ELEMENT_DEFS[eid]['name']}({w:.1f})"
            for eid, w in ew.top_three
        )
        print(f"🧠 知识内化层就绪 | {dom_info['palace']}{dom_info['name']}主导")
    except Exception as e:
        knowledge_prompt = ''
        knowledge_funcs = []
        print(f"⚠️ 知识内化层加载异常: {e}")
    # --- 知识内化对接结束 ---


    top3_str = " | ".join(
        f"{ELEMENT_DEFS[eid]['palace']}{ELEMENT_DEFS[eid]['name']}({w:.1f})"
        for eid, w in ew.top_three
    )
    snapshot = {
        "cycle": CORE.cycle,
        "state": state, "R": R,
        "pos": list(pos), "potential": potential,
        "vitality": PERCEIVE.vitality,
        "realm": REALM.name, "realm_level": REALM.level,
        "dominant": dom_info["palace"] + dom_info["name"],
        "dominant_weight": round(ew.weights[ew.dominant], 1),
        "top3": top3_str,
        "stage": STAGE_ELEMENTS[ew.stage]["name"],
        "wuxing": wuxing, "zang": PERCEIVE.zang, "zhi": PERCEIVE.zhi,
        "upgraded": upgraded,
        "thought": thought,
        "knowledge_prompt": knowledge_prompt,
        "knowledge_funcs": knowledge_funcs,
    }
    return snapshot

if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "继续思考"
    intensity = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    snap = evolve_once(topic, intensity)
    print(json.dumps(snap, ensure_ascii=False))
