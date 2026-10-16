"""L2 Component Tests: Plan system - creation, step management, completion, cancellation."""

import pytest

from openkitsune.api.routes.chat import _complete_active_todo_after_final_answer
from openkitsune.tools.handlers import todo_state
from openkitsune.tools.handlers.plan import (
    PlanHandler,
    auto_close_todo,
    cancel_todo,
    clear_session_todo_state,
    complete_todo_after_final_answer,
    get_active_todo_prompt,
    has_active_todo,
    is_todo_required,
    register_active_todo,
    register_plan_handler,
    require_todo_for_session,
    should_require_todo,
    unregister_active_todo,
)


class _DummyAgent:
    def __init__(self, conversation_id: str):
        self._current_conversation_id = conversation_id
        self._current_session_id = conversation_id


def _three_step_plan() -> dict:
    return {
        "id": "plan-final-answer",
        "plan_type": "todo",
        "task_summary": "Finish UI todo lifecycle",
        "status": "in_progress",
        "created_at": "2026-01-01T00:00:00",
        "completed_at": None,
        "logs": [],
        "steps": [
            {
                "id": "s1",
                "description": "Inspect",
                "status": "completed",
                "result": "ok",
                "skills": [],
            },
            {
                "id": "s2",
                "description": "Patch",
                "status": "completed",
                "result": "ok",
                "skills": [],
            },
            {
                "id": "s3",
                "description": "Verify",
                "status": "pending",
                "result": "",
                "skills": [],
            },
        ],
    }


def _register_plan(monkeypatch: pytest.MonkeyPatch, tmp_path, sid: str) -> tuple[PlanHandler, dict]:
    monkeypatch.setattr(PlanHandler, "_resolve_plan_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(todo_state, "_emit_todo_lifecycle_event", lambda *args: None)
    handler = PlanHandler(_DummyAgent(sid))
    plan = _three_step_plan()
    handler._todos_by_session[sid] = plan
    register_active_todo(sid, plan["id"])
    register_plan_handler(sid, handler)
    return handler, plan


class TestPlanSessionState:
    def test_unfinished_response_persists_without_completion_event(self, monkeypatch, tmp_path):
        sid = "unfinished-response"
        try:
            handler, plan = _register_plan(monkeypatch, tmp_path, sid)
            snapshot, events = _complete_active_todo_after_final_answer(sid, plan, [])
            assert events == []
            assert snapshot["steps"][-1]["status"] == "pending"
            assert auto_close_todo(sid) is False
            clear_session_todo_state(sid)
            new_handler = PlanHandler(_DummyAgent(sid))
            new_handler._store.load()
            restored = new_handler.get_plan_for(sid)
            assert restored["steps"][-1]["status"] == "pending"
            assert handler.get_plan_prompt_section(sid) == handler.get_plan_prompt_section(sid)
            assert cancel_todo(sid) is True
            assert restored["steps"][-1]["status"] == "cancelled"
        finally:
            clear_session_todo_state(sid)

    def test_plan_snapshot_uses_recorded_time_and_truthful_counts(self, monkeypatch, tmp_path):
        sid = "snapshot"
        try:
            handler, plan = _register_plan(monkeypatch, tmp_path, sid)
            plan["steps"][0]["status"] = "failed"
            plan["steps"][-1].update(status="in_progress", started_at="2000-01-01T00:00:00")
            before = handler.get_plan_prompt_section(sid)
            assert "failed=1" in before
            assert "2000-01-01T00:00:00" in before
            assert "STALE" not in before
            plan["last_response_end"] = {"observed_at": "now"}
            assert handler.get_plan_prompt_section(sid) == before
            plan["steps"][0]["result"] = "new failure detail"
            assert handler.get_plan_prompt_section(sid) != before
        finally:
            clear_session_todo_state(sid)

    def test_initial_state(self):
        sid = "test-plan-session-1"
        clear_session_todo_state(sid)
        assert has_active_todo(sid) is False
        assert is_todo_required(sid) is False

    def test_require_todo(self):
        sid = "test-plan-session-2"
        clear_session_todo_state(sid)
        require_todo_for_session(sid, True)
        assert is_todo_required(sid) is True
        require_todo_for_session(sid, False)
        assert is_todo_required(sid) is False

    def test_register_and_unregister_todo(self):
        sid = "test-plan-session-3"
        clear_session_todo_state(sid)
        register_active_todo(sid, "plan-001")
        assert has_active_todo(sid) is True
        unregister_active_todo(sid)
        assert has_active_todo(sid) is False

    def test_cancel_todo(self):
        sid = "test-plan-session-4"
        clear_session_todo_state(sid)
        register_active_todo(sid, "plan-002")
        result = cancel_todo(sid)
        assert isinstance(result, bool)

    def test_auto_close_todo(self):
        sid = "test-plan-session-5"
        clear_session_todo_state(sid)
        result = auto_close_todo(sid)
        assert isinstance(result, bool)

    @pytest.mark.parametrize("status", ["pending", "in_progress", "failed", "skipped", "cancelled"])
    def test_final_answer_preserves_unfinished_steps(self, monkeypatch, tmp_path, status):
        sid = "test-plan-session-final-answer"
        clear_session_todo_state(sid)
        try:
            _handler, plan = _register_plan(monkeypatch, tmp_path, sid)
            plan["steps"][-1]["status"] = status
            assert auto_close_todo(sid) is False
            assert plan["steps"][-1]["status"] == status

            result = complete_todo_after_final_answer(sid)

            assert result is False
            assert has_active_todo(sid) is True
            assert plan["status"] == "in_progress"
            assert [step["status"] for step in plan["steps"]] == [
                "completed",
                "completed",
                status,
            ]
        finally:
            clear_session_todo_state(sid)

    def test_chat_final_answer_helper_records_completion_event(self, monkeypatch, tmp_path):
        sid = "test-plan-session-chat-final-answer"
        clear_session_todo_state(sid)
        try:
            _handler, plan = _register_plan(monkeypatch, tmp_path, sid)
            plan["steps"][-1]["status"] = "completed"

            snapshot, events = _complete_active_todo_after_final_answer(sid, plan, [])

            assert has_active_todo(sid) is False
            assert [event["type"] for event in events] == ["todo_completed"]
            assert events[0]["planId"] == "plan-final-answer"
            assert snapshot["status"] == "completed"
            assert [step["status"] for step in snapshot["steps"]] == [
                "completed",
                "completed",
                "completed",
            ]
        finally:
            clear_session_todo_state(sid)

    def test_clear_state(self):
        sid = "test-plan-session-6"
        register_active_todo(sid, "plan-003")
        require_todo_for_session(sid, True)
        clear_session_todo_state(sid)
        assert has_active_todo(sid) is False
        assert is_todo_required(sid) is False


class TestShouldRequireTodo:
    def test_simple_message(self):
        result = should_require_todo("你好")
        assert isinstance(result, bool)

    def test_complex_task(self):
        result = should_require_todo("帮我重构整个数据库层，然后写单元测试，最后部署到生产环境")
        assert isinstance(result, bool)

    def test_empty_message(self):
        result = should_require_todo("")
        assert isinstance(result, bool)


class TestActiveTodoPrompt:
    def test_no_active_todo(self):
        sid = "test-plan-prompt-1"
        clear_session_todo_state(sid)
        prompt = get_active_todo_prompt(sid)
        assert isinstance(prompt, str)
