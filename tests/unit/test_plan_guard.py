"""plan_guard 代码 Hook 层测试。

覆盖：
- Hook 层新增的 block 决策聚合；
- R8 四条硬约束：固定计划结构 / 步骤工具门禁 / 显式自检证据 / 进度报告。
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openkitsune.agent.hooks import CallbackHook, HookEvent, HookExecutor, HookResult
from openkitsune.process_rules import plan_guard
from openkitsune.process_rules.config import get_process_rules_config, reset_config_cache


@pytest.fixture(autouse=True)
def _fresh_state():
    reset_config_cache()
    plan_guard.reset_guard_state()
    yield
    reset_config_cache()
    plan_guard.reset_guard_state()


def _plan(*, structured=True, status="in_progress", active=True, steps=None):
    if steps is None:
        steps = [
            {
                "id": "step_1",
                "description": "抓取页面",
                "status": "in_progress" if active else "pending",
                "tool": "browser_navigate",
                "expected": "拿到首页 HTML" if structured else "",
                "done_when": "返回内容非空" if structured else "",
                "result": "",
            },
            {
                "id": "step_2",
                "description": "汇总输出",
                "status": "pending",
                "expected": "生成摘要" if structured else "",
                "done_when": "摘要包含标题" if structured else "",
                "result": "",
            },
        ]
    return {
        "id": "plan_t1",
        "plan_type": "todo",
        "task_summary": "测试计划",
        "status": status,
        "steps": steps,
    }


# ── Hook 层能力 ─────────────────────────────────────────────────


class TestHookLayer:
    def test_hook_result_defaults_backward_compatible(self):
        result = HookResult(hook_id="h", event="e", success=True)
        assert result.decision == "allow" and result.feedback == ""

    def test_callback_can_return_block_decision(self):
        async def _run():
            executor = HookExecutor()
            executor.register_callback(
                "guard",
                [HookEvent.PLAN_CREATED],
                lambda event, ctx: {"decision": "block", "feedback": "结构不合规"},
            )
            return await executor.execute_first_blocking(HookEvent.PLAN_CREATED, {})

        blocked = asyncio.run(_run())
        assert blocked is not None
        assert blocked.decision == "block"
        assert blocked.feedback == "结构不合规"

    def test_no_block_returns_none(self):
        async def _run():
            executor = HookExecutor()
            executor.register_callback("noop", [HookEvent.PLAN_TURN_END], lambda e, c: None)
            return await executor.execute_first_blocking(HookEvent.PLAN_TURN_END, {})

        assert asyncio.run(_run()) is None


# ── 诉求 1：固定结构计划 ────────────────────────────────────────


class TestPlanStructure:
    def test_rejects_missing_expected_in_enforce(self):
        decision = plan_guard.validate_plan_structure(_plan(structured=False))
        assert decision.blocked
        assert decision.code == "plan_format_invalid"
        assert "expected" in decision.message

    def test_accepts_structured_plan(self):
        decision = plan_guard.validate_plan_structure(_plan(structured=True))
        assert decision.action == "allow"

    def test_plan_file_exempt_from_expected(self):
        plan = _plan(structured=False)
        plan["plan_type"] = "plan_file"
        decision = plan_guard.validate_plan_structure(plan, require_expected=False)
        assert decision.action == "allow"

    def test_duplicate_step_ids_rejected(self):
        plan = _plan()
        plan["steps"][1]["id"] = "step_1"
        decision = plan_guard.validate_plan_structure(plan)
        assert decision.blocked and "重复" in decision.message

    def test_observe_mode_only_warns(self):
        cfg = get_process_rules_config()
        cfg.plan_guard_mode = "observe"
        decision = plan_guard.validate_plan_structure(_plan(structured=False))
        assert decision.action == "warn"


# ── 诉求 2：工具调用绑定步骤 ────────────────────────────────────


class TestToolGate:
    def test_no_plan_allows(self):
        assert plan_guard.gate_tool_call(None, tool_name="write_file").action == "allow"

    def test_plan_tool_always_allowed(self):
        plan = _plan(active=False)
        decision = plan_guard.gate_tool_call(plan, tool_name="update_todo_step")
        assert decision.action == "allow"

    def test_no_active_step_blocks_mutation(self):
        plan = _plan(active=False)
        decision = plan_guard.gate_tool_call(plan, tool_name="write_file")
        assert decision.blocked and decision.code == "step_not_active"

    def test_matching_declared_tool_allowed(self):
        plan = _plan()
        decision = plan_guard.gate_tool_call(
            plan, session_id="s1", tool_name="browser_navigate", tool_input={}
        )
        assert decision.action == "allow"

    def test_other_mutating_tool_blocked(self):
        plan = _plan()
        decision = plan_guard.gate_tool_call(
            plan, session_id="s2", tool_name="send_message", tool_input={}
        )
        assert decision.blocked and decision.code == "tool_out_of_plan"

    def test_same_family_tool_allowed(self):
        plan = _plan()
        decision = plan_guard.gate_tool_call(
            plan, session_id="s2b", tool_name="browser_screenshot", tool_input={}
        )
        assert decision.action == "allow"

    def test_readonly_other_tool_only_warns(self):
        plan = _plan()
        decision = plan_guard.gate_tool_call(
            plan, session_id="s3", tool_name="read_file", tool_input={}
        )
        assert decision.action == "warn" and decision.code == "tool_out_of_plan"

    def test_plan_file_target_allowed(self):
        plan = _plan(active=False)
        plan["plan_type"] = "plan_file"
        plan["plan_file"] = "data/plans/demo.plan.md"
        decision = plan_guard.gate_tool_call(
            plan,
            tool_name="write_file",
            tool_input={"path": "data/plans/demo.plan.md"},
        )
        assert decision.action == "allow"

    def test_unstructured_plan_downgrades_to_warn(self):
        plan = _plan(structured=False, active=False)
        decision = plan_guard.gate_tool_call(plan, tool_name="write_file")
        assert decision.action == "warn"


# ── 诉求 3：显式自检证据 ────────────────────────────────────────


class TestStepSelfcheck:
    def test_completed_without_result_blocked(self):
        decision = plan_guard.validate_step_update(
            _plan(), step_id="step_1", status="completed", result=""
        )
        assert decision.blocked and decision.code == "evidence_missing"

    def test_plain_result_rejected_for_structured_plan(self):
        decision = plan_guard.validate_step_update(
            _plan(), step_id="step_1", status="completed", result="已经弄好了"
        )
        assert decision.blocked and decision.code == "selfcheck_format_missing"

    def test_structured_evidence_accepted(self):
        decision = plan_guard.validate_step_update(
            _plan(),
            step_id="step_1",
            status="completed",
            result="actual=页面返回 200 且包含 <html> | verdict=PASS",
        )
        assert decision.action == "allow"

    def test_verdict_conflict_rejected(self):
        decision = plan_guard.validate_step_update(
            _plan(),
            step_id="step_1",
            status="completed",
            result="actual=连接超时 | verdict=FAIL",
        )
        assert decision.blocked and decision.code == "verdict_conflict"

    def test_unstructured_plan_only_warns(self):
        decision = plan_guard.validate_step_update(
            _plan(structured=False), step_id="step_1", status="completed", result="done"
        )
        assert decision.action == "warn"

    def test_selfcheck_prompt_contains_contract(self):
        prompt = plan_guard.build_selfcheck_prompt(
            _plan(), tool_name="browser_navigate", success=True, result_text="<html>ok</html>"
        )
        assert "STEP-CHECK step_1" in prompt
        assert "verdict=PASS|FAIL|DEVIATE" in prompt
        assert "证据摘录" in prompt


# ── 诉求 4：确定性进度汇报 ──────────────────────────────────────


class TestProgressReport:
    def test_report_counts_and_unclosed_warning(self):
        plan = _plan()
        plan["steps"][1]["status"] = "completed"
        plan["steps"][1]["result"] = "actual=摘要生成 | verdict=PASS"
        report = plan_guard.build_progress_report(plan)
        assert "1/2" in report
        assert "计划未闭合" in report
        assert "✅" in report

    def test_completed_plan_has_no_unclosed_warning(self):
        plan = _plan(status="completed", active=False)
        for step in plan["steps"]:
            step["status"] = "completed"
        report = plan_guard.build_progress_report(plan)
        assert "计划未闭合" not in report

    def test_stale_step_detected(self):
        plan = _plan()
        plan["steps"][0]["started_at"] = (datetime.now() - timedelta(minutes=40)).isoformat()
        stale = plan_guard.detect_stale_steps(plan)
        assert stale == ["step_1"]
        report = plan_guard.build_progress_report(plan)
        assert "停滞提醒" in report

    def test_premature_completion_warning(self):
        plan = _plan()
        warning = plan_guard.detect_premature_completion(plan, "任务已完成，全部搞定")
        assert warning and "未闭合" in warning

    def test_no_warning_when_plan_complete(self):
        plan = _plan(status="completed", active=False)
        for step in plan["steps"]:
            step["status"] = "completed"
        assert plan_guard.detect_premature_completion(plan, "任务已完成") is None


# ── Hook 适配器 ─────────────────────────────────────────────────


class TestPlanGuardHookAdapter:
    def test_hook_maps_block_decision(self):
        ex = HookExecutor()
        ex.register(CallbackHook("plan_guard", [HookEvent.PLAN_CREATED], plan_guard._handle_hook))

        blocked = asyncio.run(
            ex.execute_first_blocking(
                HookEvent.PLAN_CREATED,
                {"plan": _plan(structured=False), "require_expected": True},
            )
        )
        assert blocked is not None and blocked.decision == "block"

    def test_turn_end_returns_report(self):
        ex = HookExecutor()
        ex.register(
            CallbackHook("plan_guard", [HookEvent.PLAN_TURN_END], plan_guard._handle_hook)
        )

        results = asyncio.run(
            ex.execute(HookEvent.PLAN_TURN_END, {"plan": _plan(), "response_text": ""})
        )
        assert results and "计划进度" in results[0].feedback


# ── 正式 HookExecutor 集成 ──────────────────────────────────────


class TestInstalledHookLayer:
    def test_install_is_idempotent(self):
        from openkitsune.agent.hooks import HookExecutor

        ex = HookExecutor()
        plan_guard.install_plan_guard(ex)
        plan_guard.install_plan_guard(ex)
        assert ex.handler_count == 1

    def test_tool_gate_through_executor(self):
        import asyncio

        decision = asyncio.run(
            plan_guard.run_tool_gate_hook(
                _plan(active=False), session_id="s9", tool_name="write_file", tool_input={}
            )
        )
        assert decision and "in_progress" in decision

    def test_turn_end_through_executor(self):
        import asyncio

        report = asyncio.run(plan_guard.run_turn_end_report(_plan()))
        assert "计划进度" in report


# ── PlanHandler 接入 ───────────────────────────────────────────


class TestTodoHandlerIntegration:
    def _handler(self, tmp_path):
        from openkitsune.tools.handlers.todo_handler import PlanHandler
        from openkitsune.tools.handlers.todo_store import TodoStore

        handler = PlanHandler(object())
        handler.plan_dir = tmp_path
        handler._store = TodoStore(tmp_path / "todo_store.json")
        return handler

    def test_create_todo_requires_expected(self, tmp_path):
        import asyncio

        handler = self._handler(tmp_path)
        rejected = asyncio.run(
            handler._create_todo(
                {
                    "task_summary": "缺字段计划",
                    "steps": [{"id": "step_1", "description": "做点事"}],
                }
            )
        )
        assert "计划结构不合规" in rejected

    def test_structured_plan_can_be_created(self, tmp_path):
        import asyncio

        handler = self._handler(tmp_path)
        created = asyncio.run(
            handler._create_todo(
                {
                    "task_summary": "合规计划",
                    "steps": [
                        {
                            "id": "step_1",
                            "description": "读取配置",
                            "expected": "拿到配置",
                            "done_when": "文件包含 database 段",
                        }
                    ],
                }
            )
        )
        assert "Created todo" in created

    def test_completion_requires_evidence(self, tmp_path):
        import asyncio

        handler = self._handler(tmp_path)
        asyncio.run(
            handler._create_todo(
                {
                    "task_summary": "证据计划",
                    "steps": [
                        {
                            "id": "step_1",
                            "description": "读取配置",
                            "expected": "拿到配置",
                            "done_when": "文件包含 database 段",
                        }
                    ],
                }
            )
        )
        asyncio.run(handler._update_step({"step_id": "step_1", "status": "in_progress"}))
        blocked = asyncio.run(
            handler._update_step({"step_id": "step_1", "status": "completed", "result": "弄好了"})
        )
        assert "缺少结构化自检证据" in blocked
        ok = asyncio.run(
            handler._update_step(
                {
                    "step_id": "step_1",
                    "status": "completed",
                    "result": "actual=文件含 database 段 | verdict=PASS",
                }
            )
        )
        assert "状态已更新" in ok

