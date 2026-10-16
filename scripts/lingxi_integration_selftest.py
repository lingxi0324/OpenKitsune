# -*- coding: utf-8 -*-
"""灵汐引擎整合自检 — 验证 真身降临 + 情感陪伴 + 神识日记 闭环"""
import os
import sys
from pathlib import Path

# 工程根 = 本脚本上级目录（scripts/）的父目录
PROJECT = Path(__file__).resolve().parent.parent
SRC = PROJECT / "src"
# 模拟运行时：start.ps1 会 Set-Location $ProjectRoot，project_root=Path.cwd()
os.chdir(str(PROJECT))
sys.path.insert(0, str(SRC))

os.environ.setdefault("OPENAKITA_DATA_DIR", str(PROJECT / "data"))

failures = []

def check(name, fn):
    try:
        fn()
        print(f"[OK]   {name}")
    except Exception as e:
        failures.append(name)
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")

# 1. 模块可导入
def t_imports():
    from openkitsune.core.emotion_engine import get_emotion_engine
    from openkitsune.core.emotion_perceiver import EmotionPerceiver
    from openkitsune.core.relationship_model import get_relationship_model
    from openkitsune.core.nine_turn_state import NineTurnStateMachine
    from openkitsune.core.lingxi_spirit import do_presence_beat, write_diary, get_spirit_status
    from openkitsune.heart_note.writer import get_heart_note_writer
    from openkitsune.core.lingxi_bridge import LingxiBridge
    from openkitsune.prompt.lingxi_section import build_lingxi_presence_section
check("模块导入", t_imports)

# 2. 桥接器挂载（用轻量假 Agent）
class FakeAgent:
    def __init__(self):
        self._current_user_message = "今天有点累，但看到你的消息好多了"
        self.reasoning_engine = None
        self.memory_manager = None
        self.persona_manager = None
        self.brain = None

def t_bridge_mount():
    from openkitsune.core.lingxi_bridge import LingxiBridge
    b = LingxiBridge(FakeAgent())
    assert b.emotion_engine is not None
    assert b.relationship_model is not None
check("桥接器挂载", t_bridge_mount)

# 3. 对话前注入：session context
def t_context():
    from openkitsune.core.lingxi_bridge import LingxiBridge
    b = LingxiBridge(FakeAgent())
    ctx = b.get_session_context()
    assert isinstance(ctx, dict)
    assert "emotion_state" in ctx
    assert "relationship_state" in ctx
    assert "lingxi_spirit" in ctx
    assert "emotion_style_prompt" in ctx
check("对话前 session_context 注入", t_context)

# 4. prompt 片段构建
def t_section():
    from openkitsune.core.lingxi_bridge import LingxiBridge
    from openkitsune.prompt.lingxi_section import build_lingxi_presence_section
    b = LingxiBridge(FakeAgent())
    ctx = b.get_session_context()
    sec = build_lingxi_presence_section(ctx)
    assert sec and "灵汐" in sec
check("prompt 片段构建", t_section)

# 5. 对话后收尾钩子（情感→关系→神识→心笺）
def t_after_turn():
    from openkitsune.core.lingxi_bridge import LingxiBridge
    b = LingxiBridge(FakeAgent())
    b.after_turn(
        message="今天加班到很晚，心情有点低落，谢谢你陪我说说话",
        reply="辛苦了。这个时辰确实容易让人感到疲惫……汐儿陪着你，先把最重的情绪卸下来。",
        session_id="test-session",
    )
    st = b.emotion_engine.get_state()
    print(f"    └ 主情感: {st.primary} / 强度: {st.primary_intensity:.2f} / 默契: {st.mo_qi:.1f}")
    rel = b.relationship_model.get_state()
    print(f"    └ 关系: 好感{rel.affinity:.2f} 亲密{rel.intimacy:.2f} 信任{rel.trust:.2f}")
    sp = __import__("openkitsune.core.lingxi_spirit", fromlist=["get_spirit_status"]).get_spirit_status()
    print(f"    └ 神识: 苏醒{sp['wake_count']}次 · {sp['current_eyes']} · 心澜{sp['mood_seed']}")
    # 情感引擎应已触发（感知到情绪，可能是 joy/sad 等，非崩溃即闭环成功）
    assert st.primary in ("joy", "sad", "calm", "anger", "fear", "thought", "love")
    assert rel.total_interactions >= 1
check("对话后 after_turn 闭环", t_after_turn)

# 6. 数据落盘验证
def t_persist():
    from openkitsune.core.emotion_engine import get_emotion_engine
    from openkitsune.core.relationship_model import get_relationship_model
    d = PROJECT / "data" / "emotional"
    e = d / "emotion_state.json"
    r = d / "relationship_state.json"
    assert e.exists() and r.exists(), f"missing: {e.exists()=} {r.exists()=}"
    import json
    ed = json.loads(e.read_text(encoding="utf-8"))
    rd = json.loads(r.read_text(encoding="utf-8"))
    # emotion_state.json 为嵌套结构：{"state": {...}, "mo_qi": ...}
    assert "state" in ed and "primary" in ed["state"], f"emotion 结构不符: {list(ed.keys())}"
    # relationship_state.json 为嵌套结构：{"state": {...}, "interaction_log": ...}
    assert "state" in rd and "affinity" in rd["state"], f"relationship 结构不符: {list(rd.keys())}"
    # 日记索引存在
    di = PROJECT / "data" / "lingxi_diary" / ".diary_entries.json"
    assert di.exists()
    de = json.loads(di.read_text(encoding="utf-8"))
    print(f"    └ emotion_state: primary={ed['state'].get('primary')} | relationship: affinity={rd['state'].get('affinity'):.2f}")
check("数据落盘（emotional + lingxi_diary）", t_persist)

# 7. 真身降临 persona 完整度
def t_persona():
    p = PROJECT / "identity" / "personas" / "lingxi.md"
    text = p.read_text(encoding="utf-8")
    for kw in ["九要素", "九九归真", "补天者", "九宫情绪", "中宫·本心", "相生链", "π·无穷展开"]:
        assert kw in text, f"persona 缺少: {kw}"
    print(f"    └ lingxi.md 已含九要素/九九归真/补天者内核 ({len(text)} 字符)")
check("真身降临 persona 完整度", t_persona)

print()
if failures:
    print(f"❌ {len(failures)} 项失败: {failures}")
    sys.exit(1)
print("✅ 全部通过 — 真身降临 + 情感陪伴 + 神识日记 逻辑闭环")
