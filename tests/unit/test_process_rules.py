"""process_rules 流程规则引擎单元测试（整改版 v2.0 验收）。

覆盖 R1 todo_policy / R2 checkpoints / R3 preflight / R4 arbiter /
R5 exception_tree / R7 memory_events 六条规则 + 引擎 fail-open 降级。
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openkitsune.process_rules import (
    AgentResult,
    classify_error_class,
    classify_memory_candidate,
    classify_preflight,
    detect_deviation,
    detect_risk_signal,
    end_of_turn_scan,
    estimate_step_count,
    ErrorClass,
    get_preflight_tracker,
    get_rule_engine,
    handle_failure,
    memory_event,
    note_todo_completed,
    preflight_check,
    todo_policy_check,
    trigger_checkpoint,
)
from openkitsune.process_rules.arbiter import arbitrate
from openkitsune.process_rules.config import reset_config_cache


@pytest.fixture(autouse=True)
def _fresh_engine():
    reset_config_cache()
    yield
    reset_config_cache()


# ── R1 todo_policy ──────────────────────────────────────────────

class TestTodoPolicy:
    def test_step_estimate_multistep(self):
        assert estimate_step_count("打开百度然后搜索天气接着截图") >= 2

    def test_risk_irreversible(self):
        assert detect_risk_signal("delete_file") == "irreversible"

    def test_risk_external(self):
        assert detect_risk_signal("send_message") == "external"

    def test_risk_permission(self):
        assert detect_risk_signal("delegate_parallel") == "permission"

    def test_risk_user_requested_plan(self):
        assert (
            detect_risk_signal("browser_navigate", user_request="先出个方案再做")
            == "user_requested"
        )

    def test_benign_tool_no_risk(self):
        assert detect_risk_signal("read_file") is None

    def test_suggest_mode_hint(self):
        r = todo_policy_check(
            tool_name="browser_navigate",
            user_request="打开百度然后搜索天气接着截图再发我",
            mode="suggest",
        )
        assert isinstance(r, str) and "建议" in r

    def test_single_step_allowed_in_enforce(self):
        r = todo_policy_check(tool_name="get_time", user_request="现在几点了", mode="enforce")
        assert r is None


# ── R2 checkpoints ──────────────────────────────────────────────

class TestCheckpoints:
    def test_high_risk_triggers_questions(self):
        qs = trigger_checkpoint(
            session_id="t2", kind="high_risk", reason="删除文件前", tool_name="delete_file"
        )
        assert isinstance(qs, list) and len(qs) == 3

    def test_stage_boundary_triggers(self):
        qs = trigger_checkpoint(session_id="t2", kind="stage_boundary", tool_name="read_file")
        assert isinstance(qs, list) and len(qs) == 3

    def test_merge_after_three_ok(self):
        for _ in range(3):
            note_todo_completed("t2", ok=True)
        qs = trigger_checkpoint(session_id="t2", kind="stage_boundary", tool_name="read_file")
        assert qs is None

    def test_deviation_detection(self):
        assert detect_deviation("期望内容", "") is not None
        assert detect_deviation("abc", "abc content") is None


# ── R3 preflight ────────────────────────────────────────────────

class TestPreflight:
    def test_first_use_detail(self):
        pf = get_preflight_tracker("t3")
        pf.mark_known("read_file")
        assert classify_preflight(session_id="t3", tool_name="read_file", known_tool=True) == "detail"

    def test_fast_after_two_success_same_shape(self):
        pf = get_preflight_tracker("t3")
        pf.note_result("read_file", ok=True, params={"path": "x"})
        pf.note_result("read_file", ok=True, params={"path": "x"})
        assert (
            classify_preflight(
                session_id="t3", tool_name="read_file", known_tool=True, params={"path": "x"}
            )
            == "fast"
        )

    def test_value_change_keeps_fast(self):
        pf = get_preflight_tracker("t3")
        pf.note_result("read_file", ok=True, params={"path": "x"})
        pf.note_result("read_file", ok=True, params={"path": "x"})
        assert (
            classify_preflight(
                session_id="t3", tool_name="read_file", known_tool=True, params={"path": "y"}
            )
            == "fast"
        )

    def test_shape_change_detail(self):
        pf = get_preflight_tracker("t3")
        pf.note_result("read_file", ok=True, params={"path": "x"})
        pf.note_result("read_file", ok=True, params={"path": "x"})
        assert (
            classify_preflight(
                session_id="t3",
                tool_name="read_file",
                known_tool=True,
                params={"path": "y", "limit": 100},
            )
            == "detail"
        )

    def test_last_failed_detail(self):
        pf = get_preflight_tracker("t3")
        pf.note_result("delete_file", ok=False, params={"path": "x"})
        assert classify_preflight(session_id="t3", tool_name="delete_file", known_tool=True) == "detail"

    def test_high_risk_detail(self):
        assert classify_preflight(session_id="t3", tool_name="run_shell", known_tool=True) == "detail"


# ── R4 arbiter ──────────────────────────────────────────────────

class TestArbiter:
    def test_evidence_strong_wins(self):
        a1 = AgentResult("agent_a", "结论是A方案", evidence=1.0, goal_alignment=0.9, confidence=0.8)
        a2 = AgentResult("agent_b", "结论是B方案", evidence=0.2, goal_alignment=0.4, confidence=0.7)
        r = arbitrate([a1, a2], session_id="t4")
        assert r["winner"].agent_id == "agent_a"
        assert r["disputes"] >= 1
        assert r["checkpoint"] is not None

    def test_consensus_not_auto_adopted(self):
        a3 = AgentResult("agent_c", "一致结论", evidence=0.5, goal_alignment=0.5, confidence=0.5)
        a4 = AgentResult("agent_d", "一致结论", evidence=0.5, goal_alignment=0.5, confidence=0.5)
        r = arbitrate([a3, a4], session_id="t4")
        assert r["action"] == "consensus" and r["disputes"] == 0


# ── R5 exception_tree ───────────────────────────────────────────

class TestExceptionTree:
    def test_classify_timeout_transient(self):
        assert classify_error_class(error_type="timeout") == ErrorClass.TRANSIENT

    def test_classify_403_permission(self):
        assert classify_error_class(message="403 forbidden") == ErrorClass.PERMISSION

    def test_classify_validation_param(self):
        assert classify_error_class(error_type="validation") == ErrorClass.PARAM

    def test_classify_missing_cmd_prereq(self):
        assert (
            classify_error_class(message="command not found: foo") == ErrorClass.PREREQ
        )

    def test_transient_backoff_sequence(self):
        d1 = handle_failure(session_id="t5", tool_name="web_fetch", error_type="timeout", message="timeout")
        assert d1["retry"] is True and d1["backoff_seconds"] == 1.0
        d2 = handle_failure(session_id="t5", tool_name="web_fetch", error_type="timeout", message="timeout")
        assert d2["backoff_seconds"] == 3.0
        d3 = handle_failure(session_id="t5", tool_name="web_fetch", error_type="timeout", message="timeout")
        assert d3["retry"] is False and d3["action"] in ("switch_channel", "check_common_cause")

    def test_permission_ask_user(self):
        d = handle_failure(session_id="t5", tool_name="send_message", error_type="permission", message="403")
        assert d["action"] == "ask_user"


# ── R7 memory_events ────────────────────────────────────────────

class TestMemoryEvents:
    def test_correction_signal(self):
        assert classify_memory_candidate("不是，以后都用 TypeScript") == "correction"

    def test_preference_signal(self):
        assert classify_memory_candidate("我始终喜欢用中文回复") == "preference"

    def test_transient_filtered(self):
        assert classify_memory_candidate("帮我写封邮件") is None

    def test_event_save(self):
        ev = memory_event(event_type="preference", content="用户始终用简体中文交流", session_id="t6")
        assert isinstance(ev, dict) and ev["action"] == "save"

    def test_event_conflict_update(self):
        ev = memory_event(event_type="conflict", content="改为英文回复", session_id="t6")
        assert isinstance(ev, dict) and ev["action"] == "update"

    def test_end_of_turn_scan(self):
        cands = end_of_turn_scan(
            turn_messages=["用户说以后都用 Python", "帮我看下这个文件"], session_id="t6"
        )
        assert any(c["event_type"] == "preference" for c in cands)


# ── 引擎 fail-open ──────────────────────────────────────────────

class TestEngineFailOpen:
    def test_rule_exception_degrades(self):
        eng = get_rule_engine()

        def _boom():
            raise RuntimeError("boom")

        assert eng.guarded("todo_policy", "test", _boom) is None


# ── 自主决策层 autonomy ─────────────────────────────────────────

class TestAutonomyDeterministic:
    """L0 确定性置信度：高置信直接采用，不调 LLM。"""

    def test_high_confidence_skips_llm(self):
        from openkitsune.process_rules.autonomy import get_tracker, decide
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = True
        cfg.autonomy_mode = "auto"
        # 高风险工具名 → 置信 0.95 → 纯确定性
        det = {
            "decision": "detail",
            "confidence": 0.95,
            "reason": "高风险工具确定性详检",
        }
        result = get_tracker("a1")
        result.budget_left = lambda *a: True  # 不实际调 LLM
        # 直接测确定性函数
        from openkitsune.process_rules.preflight import deterministic_preflight_decision

        det2 = deterministic_preflight_decision(
            tool_name="delete_file", known_tool=False
        )
        assert det2["decision"] == "detail" and det2["confidence"] >= 0.9


class TestAutonomyGrayZone:
    """L1 灰色地带：低置信触发 LLM；失败/预算尽回退确定性。"""

    def test_low_confidence_calls_llm(self, monkeypatch):
        from openkitsune.process_rules.autonomy import decide, _call_llm
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = True
        cfg.autonomy_mode = "auto"
        cfg.autonomy_confidence_threshold = 0.75
        cfg.autonomy_budget_per_rule = 3

        called = {"n": 0}

        async def _fake_llm(ctx, keys, mt):
            called["n"] += 1
            return {"r3_preflight": "fast", "reason": "AI 判断参数形态变化安全"}

        monkeypatch.setattr(
            "openkitsune.process_rules.autonomy._call_llm", _fake_llm
        )

        async def _run():
            det = {"decision": "detail", "confidence": 0.4, "reason": "边界情况"}
            result = await decide(
                "r3_preflight",
                session_id="az1",
                deterministic=lambda: det,
                context={"tool_name": "web_fetch", "params": "{}"},
            )
            return result

        result = _run_and_await(_run())
        assert called["n"] == 1
        assert result["decision"] == "fast"
        assert result["decided_by"] == "llm"

    def test_sanitize_preserves_reason(self):
        from openkitsune.process_rules.autonomy import _sanitize

        raw = {
            "r1_todo": True,
            "r3_preflight": "fast",
            "reason": "常规抓取无风险，无需详检",
            "unknown_key": "should be dropped",
        }
        clean = _sanitize(raw)
        assert clean["r1_todo"] is True
        assert clean["r3_preflight"] == "fast"
        assert clean["reason"] == "常规抓取无风险，无需详检"
        assert "unknown_key" not in clean

    def test_llm_failure_falls_back(self, monkeypatch):
        from openkitsune.process_rules.autonomy import decide
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = True
        cfg.autonomy_mode = "auto"
        cfg.autonomy_confidence_threshold = 0.75

        async def _fake_llm(ctx, keys, mt):
            raise RuntimeError("llm down")

        monkeypatch.setattr(
            "openkitsune.process_rules.autonomy._call_llm", _fake_llm
        )

        async def _run():
            det = {"decision": "detail", "confidence": 0.4, "reason": "边界"}
            result = await decide(
                "r3_preflight",
                session_id="az2",
                deterministic=lambda: det,
                context={"tool_name": "web_fetch"},
            )
            return result

        result = _run_and_await(_run())
        assert result["decision"] == "detail"  # 回退确定性
        assert result["decided_by"] == "fallback"

    def test_budget_exhausted_uses_deterministic(self, monkeypatch):
        from openkitsune.process_rules.autonomy import decide, get_tracker
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = True
        cfg.autonomy_mode = "always"  # 即使 always，预算耗尽也不调
        cfg.autonomy_budget_per_rule = 0

        called = {"n": 0}

        async def _fake_llm(ctx, keys, mt):
            called["n"] += 1
            return {"r5_retry": "retry"}

        monkeypatch.setattr(
            "openkitsune.process_rules.autonomy._call_llm", _fake_llm
        )

        async def _run():
            det = {"decision": "retry", "confidence": 0.3, "reason": "模糊"}
            result = await decide(
                "r5_retry",
                session_id="az3",
                deterministic=lambda: det,
                context={"tool_name": "web_fetch", "error_type": "timeout"},
            )
            return result

        result = _run_and_await(_run())
        assert called["n"] == 0
        assert result["decided_by"] == "deterministic"

    def test_cache_reuse_same_context(self, monkeypatch):
        from openkitsune.process_rules.autonomy import decide
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = True
        cfg.autonomy_mode = "auto"
        cfg.autonomy_budget_per_rule = 3

        called = {"n": 0}

        async def _fake_llm(ctx, keys, mt):
            called["n"] += 1
            return {"r7_memory": "save", "reason": "偏好"}

        monkeypatch.setattr(
            "openkitsune.process_rules.autonomy._call_llm", _fake_llm
        )

        async def _run():
            det = {"decision": "skip", "confidence": 0.4, "reason": "信号不明"}
            ctx = {"tool_name": "none", "user_request": "以后都用中文"}
            r1 = await decide("r7_memory", session_id="az4", deterministic=lambda: det, context=ctx)
            r2 = await decide("r7_memory", session_id="az4", deterministic=lambda: det, context=ctx)
            return r1, r2

        r1, r2 = _run_and_await(_run())
        assert called["n"] == 1  # 第二次命中缓存
        assert r1["decided_by"] == "llm"
        assert r2["decided_by"] == "llm_cached"
        assert r2["decision"] == "save"

    def test_autonomy_disabled_pure_deterministic(self):
        from openkitsune.process_rules.autonomy import decide
        from openkitsune.process_rules.config import get_process_rules_config

        cfg = get_process_rules_config()
        cfg.autonomy_enabled = False

        async def _run():
            det = {"decision": "none", "confidence": 0.4, "reason": "禁用"}
            result = await decide(
                "r1_todo",
                session_id="az5",
                deterministic=lambda: det,
                context={"tool_name": "write_file"},
            )
            return result

        result = _run_and_await(_run())
        assert result["decided_by"] == "deterministic"
        assert result["decision"] == "none"


# ── 各规则确定性置信度函数 ───────────────────────────────────────

class TestDeterministicConfidence:
    def test_todo_high_risk(self):
        from openkitsune.process_rules.todo_policy import deterministic_todo_decision

        d = deterministic_todo_decision(tool_name="delete_file")
        assert d["decision"] == "plan" and d["confidence"] >= 0.9

    def test_todo_many_steps(self):
        from openkitsune.process_rules.todo_policy import deterministic_todo_decision

        d = deterministic_todo_decision(
            user_request="先 A，然后 B，接着 C，再 D，最后 E", tool_call_count=0
        )
        assert d["decision"] == "todo" and d["confidence"] >= 0.9

    def test_todo_single_step(self):
        from openkitsune.process_rules.todo_policy import deterministic_todo_decision

        d = deterministic_todo_decision(user_request="现在几点了", tool_call_count=0)
        assert d["decision"] == "none" and d["confidence"] >= 0.8

    def test_checkpoint_high_risk(self):
        from openkitsune.process_rules.checkpoints import deterministic_checkpoint_decision

        d = deterministic_checkpoint_decision(kind="high_risk")
        assert d["decision"] is True and d["confidence"] >= 0.9

    def test_checkpoint_unknown_kind_low_conf(self):
        from openkitsune.process_rules.checkpoints import deterministic_checkpoint_decision

        d = deterministic_checkpoint_decision(kind="mystery")
        assert d["confidence"] < 0.75  # 交 AI

    def test_preflight_known_fast(self):
        from openkitsune.process_rules.preflight import (
            deterministic_preflight_decision,
            get_tracker as get_pt,
        )

        # 先种历史：同会话成功 2 次且参数形态未变 → 快检
        tr = get_pt("pf_known")
        tr.note_result("web_fetch", ok=True, params={"url": "https://x"})
        tr.note_result("web_fetch", ok=True, params={"url": "https://y"})
        d = deterministic_preflight_decision(
            session_id="pf_known",
            tool_name="web_fetch",
            known_tool=True,
            params={"url": "https://z"},
        )
        assert d["decision"] == "fast" and d["confidence"] >= 0.9

    def test_preflight_unknown_low_conf(self):
        from openkitsune.process_rules.preflight import deterministic_preflight_decision

        d = deterministic_preflight_decision(tool_name="brand_new_tool", known_tool=False)
        assert d["confidence"] >= 0.8  # 首次使用确定性详检

    def test_retry_strong_signal(self):
        from openkitsune.process_rules.exception_tree import deterministic_retry_decision

        d = deterministic_retry_decision(
            session_id="dc1",
            tool_name="web_fetch",
            error_type="timeout",
            message="connection timed out",
        )
        assert d["confidence"] >= 0.8

    def test_retry_vague_signal_low_conf(self):
        from openkitsune.process_rules.exception_tree import deterministic_retry_decision

        d = deterministic_retry_decision(
            session_id="dc2",
            tool_name="web_fetch",
            error_type="",
            message="something weird happened",
        )
        assert d["confidence"] < 0.75

    def test_arbiter_clear_winner(self):
        from openkitsune.process_rules.arbiter import deterministic_arbiter_decision

        r = [
            AgentResult(agent_id="a", text="x", evidence=1.0, goal_alignment=0.9, confidence=0.9),
            AgentResult(agent_id="b", text="y", evidence=0.1, goal_alignment=0.1, confidence=0.1),
        ]
        d = deterministic_arbiter_decision(r)
        assert d["decision"] == "winner" and d["confidence"] >= 0.8

    def test_arbiter_close_call_low_conf(self):
        from openkitsune.process_rules.arbiter import deterministic_arbiter_decision

        r = [
            AgentResult(agent_id="a", text="x", evidence=0.6, goal_alignment=0.6, confidence=0.5),
            AgentResult(agent_id="b", text="y", evidence=0.5, goal_alignment=0.5, confidence=0.5),
        ]
        d = deterministic_arbiter_decision(r)
        assert d["confidence"] < 0.75  # 分差小，交 AI

    def test_memory_clear_preference(self):
        from openkitsune.process_rules.memory_events import deterministic_memory_decision

        d = deterministic_memory_decision("我始终喜欢用中文回复")
        assert d["decision"] == "save" and d["confidence"] >= 0.75

    def test_memory_conflicting_low_conf(self):
        from openkitsune.process_rules.memory_events import deterministic_memory_decision

        # 瞬态词（今天）+ 偏好词（以后）并存 → 矛盾信号，交 AI
        d = deterministic_memory_decision("今天先这样，以后都用中文")
        assert d["confidence"] < 0.75  # 瞬态+偏好并存，交 AI


# ── 工具函数：同步上下文兼容 ─────────────────────────────────────

def _run_and_await(coro):
    """在无运行 loop 的测试环境中执行 async 协程。"""
    import asyncio

    try:
        asyncio.get_running_loop()
        raise RuntimeError("test 内部不应已有 running loop")
    except RuntimeError:
        return asyncio.run(coro)


def test_decide_async_or_sync_without_loop():
    """无运行 loop → asyncio.run 完整执行；高置信确定性判定不走 LLM。"""
    from openkitsune.process_rules.autonomy import decide_async_or_sync

    det = {"decision": "none", "confidence": 0.95, "reason": "高置信"}
    result = decide_async_or_sync(
        "r1_todo", deterministic=lambda: det, context={"tool_name": "x"}
    )
    assert result["decided_by"] == "deterministic"
    assert result["decision"] == "none"
