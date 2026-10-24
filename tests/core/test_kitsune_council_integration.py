"""九尾议会接入点集成测试：验证接入运行时不会造成新问题（副作用/冲突/降级）。

覆盖四类风险：
1. 接入契约：prepare_turn 产出 → builder 消费键名一致；OFF/异常 → 空 ctx 零影响
2. 真实复盘落库：after_turn 走真实 turn_review 写盘，JSON 可读、字段完整
3. 与灵汐桥接并行：互不共享可变状态，可同时挂载
4. 注入预算：FULL 议会段体积受控（不显著增加 token 成本）
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, r"E:\agents\OpenKitsune-main\src")

from openkitsune.core.kitsune_council import (
    KitsuneCouncil,
    build_council_section,
    classify_request,
    parse_directive,
)

# 与 builder.py §6.596 消费端严格一致的键契约
BUILDER_CTX_KEY = "kitsune_council"
BUILDER_SECTION_KEY = "section"
BUILDER_DISPATCH_KEY = "dispatch_hint"


class TestInjectionContract(unittest.TestCase):
    """接入契约：runtime 注入的 ctx 与 builder 消费端一致"""

    def test_ctx_keys_match_builder_contract(self):
        c = KitsuneCouncil()
        ctx = c.prepare_turn("要不要离职去创业？纠结很久了")
        self.assertIn("section", ctx)
        self.assertIn("mode", ctx)
        self.assertIn("tails", ctx)
        self.assertIn("reason", ctx)
        # builder 只消费这两个键，任何多余键不破坏现有 prompt
        self.assertTrue(ctx[BUILDER_SECTION_KEY])

    def test_dispatch_hint_present_for_complex(self):
        c = KitsuneCouncil()
        ctx = c.prepare_turn("帮我做一份全面的职业规划，分析五个方向，涉及跳槽、创业、深造，影响未来十年")
        self.assertIn(BUILDER_DISPATCH_KEY, ctx)

    def test_off_zero_impact(self):
        """OFF 时 ctx 无 section → builder 分支不触发，与未接入完全一致"""
        c = KitsuneCouncil()
        ctx = c.prepare_turn("/council off 随便聊聊")
        self.assertEqual(ctx["mode"], "off")
        self.assertNotIn("section", ctx)
        self.assertNotIn(BUILDER_DISPATCH_KEY, ctx)

    def test_minimal_no_dispatch(self):
        c = KitsuneCouncil()
        ctx = c.prepare_turn("在吗")
        self.assertEqual(ctx["mode"], "minimal")
        self.assertNotIn(BUILDER_DISPATCH_KEY, ctx)

    def test_exception_safe(self):
        """异常必须返回空 ctx（运行时 try/except 兜底的前置防线）"""
        c = KitsuneCouncil()
        with patch("openkitsune.core.kitsune_council.classify_request", side_effect=RuntimeError("boom")):
            ctx = c.prepare_turn("测试")
            self.assertEqual(ctx, {})


class TestRealReviewPersistence(unittest.TestCase):
    """真实复盘落库：走真实 turn_review + 临时 data 目录，验证写盘与可读性"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="ok_review_"))
        # 隔离 settings.project_root → 临时目录，避免污染真实 data/retrospects
        cls._patcher = patch("openkitsune.config.settings.project_root", cls._tmp)
        cls._patcher.start()
        cls.addClassCleanup(cls._patcher.stop)

    def _retro_files(self):
        d = self._tmp / "data" / "retrospects"
        return list(d.glob("*.jsonl")) if d.exists() else []

    def test_after_turn_writes_readable_jsonl(self):
        c = KitsuneCouncil()
        c.prepare_turn("帮我分析下要不要换工作")
        ok = c.after_turn(
            message="帮我分析下要不要换工作",
            reply="我理解你的纠结。先看目标与取舍：方案A稳定但发展慢，方案B有风险但上限高；建议先评估代价再做决定。",
            session_id="itg-test-session",
        )
        # after_turn 真实写盘（非 mock）
        self.assertTrue(ok)
        files = self._retro_files()
        self.assertTrue(files, "data/retrospects 目录应有复盘 jsonl")
        line = files[0].read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(line)
        # 与 RetrospectRecord.to_dict() 结构一致：六问分数编码在 retrospect_result 文本中
        self.assertIn("task_id", rec)
        self.assertIn("session_id", rec)
        self.assertIn("retrospect_result", rec)
        rr = rec["retrospect_result"]
        for key in ("六问复盘", "意图识别", "九维覆盖", "情绪接住", "方案落地",
                    "人设一致", "用户满意"):
            self.assertIn(key, rr, f"retrospect_result 缺 {key}")
        self.assertIn("itg-test-session", rec["session_id"])

    def test_off_no_write(self):
        c = KitsuneCouncil()
        c.prepare_turn("/council off x")
        before = self._retro_files()
        ok = c.after_turn(message="/council off x", reply="好", session_id="itg-off")
        self.assertFalse(ok)
        after = self._retro_files()
        self.assertEqual(before, after, "OFF 模式不应写复盘")


class TestParallelWithLingxi(unittest.TestCase):
    """与灵汐桥接并行：独立实例无共享可变状态"""

    def test_independent_instances(self):
        a = KitsuneCouncil()
        b = KitsuneCouncil()
        a.prepare_turn("要不要离职去创业？")
        self.assertIsNone(b._last_profile, "实例间不得共享状态")
        ctx_b = b.prepare_turn("在吗")
        self.assertEqual(ctx_b["mode"], "minimal")
        # a 的状态不被 b 污染
        self.assertIn("strategy", a._last_profile.tail_slate)

    def test_prepare_then_verify_uses_last_profile(self):
        c = KitsuneCouncil()
        c.prepare_turn("帮我分析下要不要换工作")
        v = c.check_coverage("直接说结论：换。")
        self.assertTrue(v.insufficient)
        self.assertIn("strategy", v.missing_tails)


class TestInjectionBudget(unittest.TestCase):
    """注入预算：议会段体积受控，不显著增加每轮 token 成本"""

    def test_full_section_length(self):
        p = classify_request("要不要离职去创业？纠结很久了")
        s = build_council_section(p)
        # FULL 段控制在 ~300 tokens 内（中文按 ~1.5 字/token 估算上限 450 字）
        self.assertLessEqual(len(s), 450)

    def test_minimal_section_length(self):
        p = classify_request("在吗")
        s = build_council_section(p)
        self.assertLessEqual(len(s), 120)


class TestCommandSurface(unittest.TestCase):
    """用户自主选择命令面"""

    def test_status_command(self):
        d = parse_directive("/council 状态")
        self.assertEqual(d["action"], "status")

    def test_all_tails(self):
        d = parse_directive("/尾 全部")
        self.assertEqual(d["tails"], {"strategy", "psychic", "creative", "risk",
                                      "execution", "ethics", "memory", "tools", "review"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
