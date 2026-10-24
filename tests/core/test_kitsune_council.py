"""九尾议会自主调度内核 · 单元测试（stdlib unittest，无需 pytest）"""
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, r"E:\agents\OpenKitsune-main\src")

# 假 turn_review 模块：仅在单测作用域内注入 sys.modules（patch.dict），
# 避免污染同进程其他测试文件（如集成测试的真实写盘验证）。
_FAKE_TR = types.ModuleType("openkitsune.evolution.turn_review")
_FAKE_TR.record_turn_review = Mock(return_value=True)


class _FakeTurnReviewMixin:
    """为需要复盘调用的测试类提供作用域内 fake turn_review"""

    def setUp(self):
        self._tr_patch = patch.dict(
            sys.modules, {"openkitsune.evolution.turn_review": _FAKE_TR}
        )
        self._tr_patch.start()
        _FAKE_TR.record_turn_review.reset_mock()

    def tearDown(self):
        self._tr_patch.stop()


kc = importlib.import_module("openkitsune.core.kitsune_council")
from openkitsune.core.kitsune_council import (
    CouncilMode,
    build_council_section,
    classify_request,
    parse_directive,
    review_turn,
    should_dispatch,
    verify_coverage,
)


class TestParseDirective(unittest.TestCase):
    def test_mode_off(self):
        d = parse_directive("/council off")
        self.assertIsNotNone(d)
        self.assertIs(d["mode"], CouncilMode.OFF)

    def test_mode_full(self):
        d = parse_directive("/council full")
        self.assertIs(d["mode"], CouncilMode.FULL)

    def test_mode_chinese(self):
        d = parse_directive("/议会 轻量")
        self.assertIs(d["mode"], CouncilMode.MINIMAL)

    def test_tails_override(self):
        d = parse_directive("/尾 战略+风控+伦理")
        self.assertEqual(d["tails"], {"strategy", "risk", "ethics"})

    def test_tails_override_sep(self):
        d = parse_directive("/council 尾 战略,心理")
        self.assertEqual(d["tails"], {"strategy", "psychic"})

    def test_status(self):
        d = parse_directive("/council")
        self.assertEqual(d["action"], "status")

    def test_plain_text_no_directive(self):
        self.assertIsNone(parse_directive("帮我看看这个方案怎么样"))


class TestClassify(unittest.TestCase):
    def test_minimal_greeting(self):
        p = classify_request("在吗")
        self.assertIs(p.mode, CouncilMode.MINIMAL)

    def test_decision_full(self):
        p = classify_request("要不要离职去创业？纠结很久了，利弊都想清楚一点")
        self.assertIs(p.mode, CouncilMode.FULL)
        self.assertIn("strategy", p.tail_slate)
        self.assertIn("risk", p.tail_slate)
        self.assertIn("ethics", p.tail_slate)

    def test_tech_execution(self):
        p = classify_request("帮我写一个 python 脚本处理这些日志文件，先分析再输出报告")
        self.assertIn("execution", p.tail_slate)
        self.assertIn("tools", p.tail_slate)
        self.assertTrue(p.multi_step)

    def test_emotional(self):
        p = classify_request("最近好累，心里很难过，不知道该怎么办")
        self.assertTrue(p.emotional)
        self.assertIn("psychic", p.tail_slate)
        self.assertIn("ethics", p.tail_slate)

    def test_risk_triggers(self):
        p = classify_request("帮我把这个文件夹删掉，然后覆盖发布到正式环境")
        self.assertGreaterEqual(p.risk_level, 0.6)
        self.assertIn("risk", p.tail_slate)

    def test_cross_domain(self):
        p = classify_request("用中医结合现代科学的视角分析这个体质问题")
        self.assertTrue(p.cross_domain)
        self.assertIn("creative", p.tail_slate)

    def test_directive_off_overrides(self):
        p = classify_request("/council off 之后随便聊聊")
        self.assertIs(p.mode, CouncilMode.OFF)
        self.assertEqual(p.tail_slate, set())

    def test_directive_off_with_trailing_newline(self):
        # 命令后跟换行正文（真实场景）：正则不得用 $ 锚点，否则整条失效
        p = classify_request("/council off\n帮我看看这个方案")
        self.assertIs(p.mode, CouncilMode.OFF)
        self.assertEqual(p.tail_slate, set())

    def test_directive_full_with_trailing_text(self):
        p = classify_request("/council full\n帮我规划三年目标")
        self.assertIs(p.mode, CouncilMode.FULL)

    def test_directive_tails_overrides(self):
        p = classify_request("/尾 战略,风控 帮我分析买哪辆车")
        self.assertEqual(p.tail_slate, {"strategy", "risk"})

    def test_default_auto_has_psychic_memory(self):
        p = classify_request("帮我整理这份文档")
        self.assertIn("psychic", p.tail_slate)
        self.assertIn("memory", p.tail_slate)


class TestBuildSection(unittest.TestCase):
    def test_off_empty(self):
        p = classify_request("/council off x")
        self.assertEqual(build_council_section(p), "")

    def test_minimal_one_line(self):
        p = classify_request("在吗")
        s = build_council_section(p)
        self.assertIn("议会·轻量", s)

    def test_full_contains_multi_path(self):
        p = classify_request("要不要离职去创业？纠结很久了")
        s = build_council_section(p)
        self.assertIn("九尾议会·FULL", s)
        self.assertIn("多路径推演", s)

    def test_full_risk_note(self):
        p = classify_request("帮我把这个文件夹删掉，覆盖发布到正式环境")
        s = build_council_section(p)
        self.assertIn("风控优先", s)

    def test_none_safe(self):
        self.assertEqual(build_council_section(None), "")


class TestVerifyCoverage(unittest.TestCase):
    def test_covered(self):
        p = classify_request("帮我分析下要不要换工作")
        v = verify_coverage(p, "我理解你的纠结，先看目标与取舍：方案A稳定但发展慢，方案B有风险但上限高；建议先评估代价再做决定。")
        self.assertTrue(v.checked)
        self.assertFalse(v.insufficient)

    def test_missing(self):
        p = classify_request("帮我分析下要不要换工作")
        v = verify_coverage(p, "直接说结论：换。")
        self.assertTrue(v.insufficient)
        self.assertIn("strategy", v.missing_tails)

    def test_minimal_skipped(self):
        p = classify_request("在吗")
        v = verify_coverage(p, "在的，有什么可以帮你？")
        self.assertFalse(v.checked)


class TestReviewTurn(_FakeTurnReviewMixin, unittest.TestCase):
    def tearDown(self):
        super().tearDown()
        _FAKE_TR.record_turn_review.reset_mock()

    def test_writes_record(self):
        p = classify_request("帮我分析下要不要换工作")
        ok = review_turn(p, task_id="t1", session_id="s1", response_text="考虑风险与代价，建议先列出候选路径再决定。")
        self.assertTrue(ok)
        _FAKE_TR.record_turn_review.assert_called_once()
        kwargs = _FAKE_TR.record_turn_review.call_args.kwargs
        self.assertIn("intent_ok", kwargs)
        self.assertIn("nine_tail_coverage", kwargs)
        self.assertIn("improvement", kwargs)

    def test_off_skipped(self):
        p = classify_request("/council off x")
        ok = review_turn(p, task_id="t2", session_id="s2", response_text="好")
        self.assertFalse(ok)
        _FAKE_TR.record_turn_review.assert_not_called()

    def test_minimal_skipped(self):
        p = classify_request("在吗")
        ok = review_turn(p, task_id="t3", session_id="s3", response_text="在的")
        self.assertFalse(ok)

    def test_improvement_mentions_missing(self):
        p = classify_request("帮我分析下要不要换工作")
        review_turn(p, task_id="t4", session_id="s4", response_text="换吧。")
        kwargs = _FAKE_TR.record_turn_review.call_args.kwargs
        self.assertIn("覆盖不足", kwargs["improvement"])


class TestShouldDispatch(unittest.TestCase):
    def test_complex_decision(self):
        p = classify_request("帮我做一份全面的职业规划，分析五个方向，涉及跳槽、创业、深造，影响未来十年")
        self.assertTrue(should_dispatch(p))

    def test_simple_no(self):
        p = classify_request("在吗")
        self.assertFalse(should_dispatch(p))


class TestCouncilInstance(_FakeTurnReviewMixin, unittest.TestCase):
    def test_prepare_turn_ctx(self):
        c = kc.KitsuneCouncil()
        ctx = c.prepare_turn("要不要离职去创业？纠结很久了")
        self.assertEqual(ctx["mode"], "full")
        self.assertIn("section", ctx)
        self.assertTrue(ctx["tails"])

    def test_prepare_turn_off(self):
        c = kc.KitsuneCouncil()
        ctx = c.prepare_turn("/council off x")
        self.assertEqual(ctx["mode"], "off")
        self.assertNotIn("section", ctx)

    def test_after_turn_wires(self):
        c = kc.KitsuneCouncil()
        c.prepare_turn("帮我分析下要不要换工作")
        ok = c.after_turn(message="帮我分析下要不要换工作", reply="考虑风险与代价。", session_id="sx")
        self.assertTrue(ok)
        _FAKE_TR.record_turn_review.assert_called_once()

    def tearDown(self):
        super().tearDown()
        _FAKE_TR.record_turn_review.reset_mock()


if __name__ == "__main__":
    unittest.main(verbosity=2)
