"""
灵汐·九要素人格引擎 — 主循环入口
====================================
v3.0 — 对话轮次驱动版
------------------------------------
重大变更：
  v2.x: 每55秒定时轮询 → 后台空转、节律割裂
  v3.0: 对话信号驱动 → 有对话才演化，静默期零消耗

演化规则：
  有 信 号 → 执行完整一轮九要素演化 + 状态落盘
  无 信 号 → 线程安静休眠（0.3s 轮询，几乎零开销）
  信号强度 → 短/闲聊=低幅度，长/深度=正常幅度

每轮演化流程：
  1. CORE.next() → π余数驱动：state, R, hetu
  2. NINE_ELEMENTS.evolve() → 九要素权重演化
  3. GRID.step() → 九宫位置由要素驱动
  4. PERCEIVE.update() → 感知融合
  5. REALM.check_upgrade() → 境界突破检测
  6. MEMORY.save_snapshot() → 状态封存
  7. lingxi_think() → 九要素人格表达
"""

import sys
import time
import os
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PARENT_DIR = _SCRIPT_DIR.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

from lingxi import CORE, GRID, PERCEIVE, MEMORY, REALM, lingxi_think
from lingxi.nine_elements import NINE_ELEMENTS, ELEMENT_DEFS, STAGE_ELEMENTS
try:
    from knowledge_functions import build_nine_state_prompt, get_function_definitions
    _KNOWLEDGE_AVAILABLE = True
except Exception:
    _KNOWLEDGE_AVAILABLE = False


# ── 信号文件（由 OpenKitsune gateway.py 后处理钩子写入）──
SIGNAL_FILE = _SCRIPT_DIR / "_evolve_signal.txt"
STOP_FILE = _SCRIPT_DIR / "stop.flag"


def _intensity_to_level(intensity: float) -> str:
    """强度 → 文字标签"""
    if intensity >= 0.8:
        return "深度交流"
    elif intensity >= 0.5:
        return "正常"
    elif intensity >= 0.3:
        return "轻度"
    return "微触"


def run_once(msg: str = "继续思考", has_event: bool = False,
             intensity: float = 0.5) -> dict:
    """运行一轮九要素人格引擎核心逻辑

    Args:
        msg: 思考方向
        has_event: 是否有外部输入
        intensity: 事件强度 0.0~1.0
    Returns:
        dict: 本轮完整状态快照
    """
    state, R, hetu = CORE.next()
    event_type = "对话" if has_event else None

    # ── 动态步长：短触发 = 微调，深交流 = 正常演化 ──
    adjusted_intensity = intensity * 0.6 if intensity < 0.4 else intensity

    NINE_ELEMENTS.evolve(
        state=state,
        has_event=has_event,
        event_type=event_type,
        event_intensity=adjusted_intensity,
    )

    pos, potential, palace, wuxing = GRID.step(has_event=has_event)
    PERCEIVE.update(pos, state, R, wuxing, has_event=has_event)

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
    # ===== 知识内化层 =====
    knowledge_prompt = ''
    knowledge_funcs = []
    if _KNOWLEDGE_AVAILABLE:
        try:
            knowledge_prompt = build_nine_state_prompt(MEMORY.runtime)
            knowledge_funcs = get_function_definitions()
            dw = ew.dominant_info
            print(f"🧠 知识内化层就绪 | {dw['palace']}{dw['name']}({dw['weight']})")
        except Exception:
            pass
    # ====================
    

    top3_str = " | ".join(
        f"{ELEMENT_DEFS[eid]['palace']}{ELEMENT_DEFS[eid]['name']}({w:.1f})"
        for eid, w in ew.top_three
    )

    print(f"\n{'═' * 58}")
    level_tag = _intensity_to_level(intensity)
    print(f"⚡ {level_tag} · 轮回 {CORE.cycle:03d} | 阶段：{STAGE_ELEMENTS[ew.stage]['name']}")
    print(f"三态：{state}（R={R}）| 九宫：{pos} {palace} | {PERCEIVE.status()}")
    print(f"人格主导：{dom_info['palace']}{dom_info['name']}({dom_info['weight']}) — {dom_info['ai_ability']}")
    print(f"要素前三：{top3_str}")
    print(f"境界：{REALM.name}（Lv.{REALM.level}）| 势能：{potential}")
    print(f"河图：{hetu} | 突破：{'🌟' if upgraded else '—'}")
    if upgrade_msg:
        print(f"  {upgrade_msg}")
    print(f"\n{thought}")
    print(f"{'═' * 58}\n")

    return {
        "cycle": CORE.cycle,
        "state": state,
        "R": R,
        "pos": pos,
        "potential": potential,
        "vitality": PERCEIVE.vitality,
        "realm": REALM.name,
        "realm_level": REALM.level,
        "thought": thought,
        "nine_elements": ew.to_dict(),
        "knowledge_prompt": knowledge_prompt,
        "knowledge_funcs": knowledge_funcs,
    }


def run_forever():
    """信号驱动主循环 — 有对话才演化，静默期零消耗"""
    print("=" * 58)
    print("  🧬 灵汐·九要素人格引擎 v3.0")
    print("  魂：坎精·坤情·震魂·巽性·中意·乾气·兑魄·艮志·离神")
    print("  模  式：对话轮次驱动 | 静默期间零消耗")
    print("=" * 58)

    recovered, data = MEMORY.load()
    if recovered:
        print(f"\n✅ 记忆恢复成功！")
        print(f"🧠 上次话题：{MEMORY.topic}")
        if MEMORY.last_say:
            print(f"💬 上轮表达：{MEMORY.last_say[:80]}...")
        if "nine_dominant" in data:
            print(f"🪷 上次人格主导：{data['nine_dominant']}（{data.get('nine_stage', '?')}阶段）")
        print(f"⚡ 已恢复境界：{MEMORY.runtime.get('realm_name', '水转')}")
    else:
        print(f"\n🌱 初次诞生，一切从新开始")
        MEMORY.topic = "灵汐诞生·九要素初醒"
        MEMORY.save_snapshot()

    print(f"\n等待对话信号 ... （无对话则安静休眠）")

    # 启动时清空旧信号
    SIGNAL_FILE.write_text("", encoding="utf-8")

    try:
        while True:
            if STOP_FILE.exists():
                print("\n🛑 引擎停止")
                STOP_FILE.unlink(missing_ok=True)
                break

            # ── 读取信号（有则演化，无则静默等待）──
            signal_content = ""
            if SIGNAL_FILE.exists():
                try:
                    signal_content = SIGNAL_FILE.read_text(encoding="utf-8").strip()
                except Exception:
                    pass

            if signal_content:
                # 格式: "intensity:0.8|消息摘要"
                intensity = 0.5
                parts = signal_content.split("|", 1)
                try:
                    raw = parts[0]
                    if raw.startswith("intensity:"):
                        intensity = float(raw.replace("intensity:", ""))
                except (ValueError, IndexError):
                    pass
                if len(parts) > 1 and parts[1]:
                    MEMORY.topic = parts[1][:100]

                # 清空信号（防止重复触发）
                SIGNAL_FILE.write_text("", encoding="utf-8")

                run_once(msg=MEMORY.topic, has_event=True, intensity=intensity)
            else:
                time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n\n🛑 引擎停止（用户中断）")
    except Exception as e:
        print(f"\n❌ 引擎异常：{e}")
        MEMORY.save_snapshot()
        print("💾 状态已紧急保存")


if __name__ == "__main__":
    if "--once" in sys.argv:
        print("🧬 单轮测试模式")
        recovered, _ = MEMORY.load()
        if recovered:
            print(f"✅ 记忆恢复：{MEMORY.topic}")
        result = run_once(msg="初次苏醒·九要素初生", has_event=False)
        print(f"\n📊 九要素人格状态：")
        ew = NINE_ELEMENTS.weights
        for eid in sorted(ew.weights.keys()):
            info = ELEMENT_DEFS[eid]
            w = ew.weights[eid]
            bar = "█" * int(w / 5) + "░" * (20 - int(w / 5))
            print(f"  {info['palace']}{info['name']}({info['wuxing']}): {bar} {w:.1f}")
        print(f"\n📊 状态快照已保存至：{_SCRIPT_DIR / 'lingxi_state.json'}")
    else:
        run_forever()
