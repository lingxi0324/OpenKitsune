"""Fix-3 回归测试：受控操作死胡同 — 用户确认后让 LLM 重新规划。

涵盖两层：
1. 后端 `_handle_pending_risk_answer`：classification.action=None 且 decision=
   CONFIRM 时返回 `_RiskAuthorizedReplay`，并写入 session 授权 metadata。
2. agent `_consume_risk_authorization`：检测授权 + 单次消费 + TTL。
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openkitsune.agent.safety.destructive_intent import consume_risk_authorization as _consume_risk_authorization


# ---------------------------------------------------------------------------
# _consume_risk_authorization
# ---------------------------------------------------------------------------


class _StubSession:
    """Minimal session stub with metadata read/write."""

    def __init__(self, metadata: dict | None = None):
        self._meta = dict(metadata or {})
        self.messages_added: list[tuple[str, str]] = []

    def get_metadata(self, key: str):
        return self._meta.get(key)

    def set_metadata(self, key: str, value):
        if value is None:
            self._meta.pop(key, None)
        else:
            self._meta[key] = value

    def add_message(self, role: str, content: str, **_kwargs):
        self.messages_added.append((role, content))


def test_consume_authorization_returns_true_on_match():
    msg = "请用 run_powershell 执行 ls"
    session = _StubSession(
        metadata={
            "risk_authorized_replay": {
                "expires_at": time.time() + 30,
                "confirmation_id": "conf-1",
                "original_message": msg,
            }
        }
    )

    assert _consume_risk_authorization(session, msg) is True
    # single-use: stamp consumed
    assert session.get_metadata("risk_authorized_replay") is None


def test_consume_authorization_returns_false_on_message_mismatch():
    session = _StubSession(
        metadata={
            "risk_authorized_replay": {
                "expires_at": time.time() + 30,
                "confirmation_id": "conf-1",
                "original_message": "请删除 a.txt",
            }
        }
    )

    assert _consume_risk_authorization(session, "请删除 b.txt") is False
    # stamp NOT consumed (because it's still potentially valid for the right msg)
    assert session.get_metadata("risk_authorized_replay") is not None


def test_consume_authorization_returns_false_when_expired():
    session = _StubSession(
        metadata={
            "risk_authorized_replay": {
                "expires_at": time.time() - 1,
                "confirmation_id": "conf-1",
                "original_message": "x",
            }
        }
    )

    assert _consume_risk_authorization(session, "x") is False
    # expired stamp cleared
    assert session.get_metadata("risk_authorized_replay") is None


def test_consume_authorization_handles_missing_stamp():
    session = _StubSession()
    assert _consume_risk_authorization(session, "x") is False


def test_consume_authorization_handles_none_session():
    assert _consume_risk_authorization(None, "x") is False


def test_consume_authorization_handles_empty_message():
    session = _StubSession(
        metadata={
            "risk_authorized_replay": {
                "expires_at": time.time() + 30,
                "original_message": "",
            }
        }
    )
    assert _consume_risk_authorization(session, "") is False


# ---------------------------------------------------------------------------
# _handle_pending_risk_answer + _RiskAuthorizedReplay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_risk_confirm_with_no_action_returns_authorized_replay():
    """CONFIRM + action=None ⇒ _RiskAuthorizedReplay (let LLM replan)."""
    from openkitsune.api.routes import chat as chat_mod
    from openkitsune.core.confirmation_state import get_confirmation_store

    store = get_confirmation_store()
    conv = "conv-fix3-1"
    store.clear(conv)

    original_msg = "请把 plan.md 删除掉"
    classification = {
        "risk_level": "high",
        "operation_kind": "execute",
        "target_kind": "shell_command",
        "access_mode": "execute",
        "requires_confirmation": True,
        "reason": "execute_or_shell_risk",
        "action": None,  # 关键：无受控执行入口
        "parameters": {},
    }
    pending = store.create(
        conversation_id=conv,
        original_message=original_msg,
        classification=classification,
        request_id="req-fix3-1",
    )

    # session_manager mock — 写授权 metadata 应能成功
    fake_session = _StubSession()

    fake_sm = MagicMock()
    fake_sm.get_session.return_value = fake_session

    fake_app_state = SimpleNamespace(session_manager=fake_sm)
    fake_request = SimpleNamespace(app=SimpleNamespace(state=fake_app_state))

    result = await chat_mod._handle_pending_risk_answer(
        request=fake_request,
        conversation_id=conv,
        answer="确认继续",
        as_stream=True,
    )

    assert isinstance(result, chat_mod._RiskAuthorizedReplay)
    assert result.original_message == original_msg
    assert result.confirmation_id == pending.confirmation_id

    stamp = fake_session.get_metadata("risk_authorized_replay")
    assert stamp is not None
    assert stamp["original_message"] == original_msg
    assert stamp["confirmation_id"] == pending.confirmation_id
    assert stamp["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_pending_risk_confirm_with_action_still_executes_controlled():
    """CONFIRM + action 非空 ⇒ 走原有 execute_controlled_action 路径。"""
    from openkitsune.api.routes import chat as chat_mod
    from openkitsune.core.confirmation_state import get_confirmation_store

    store = get_confirmation_store()
    conv = "conv-fix3-2"
    store.clear(conv)

    classification = {
        "risk_level": "high",
        "operation_kind": "delete",
        "target_kind": "security_user_allowlist",
        "access_mode": "write",
        "requires_confirmation": True,
        "reason": "policy_allowlist_delete",
        "action": "remove_security_allowlist_entry",
        "parameters": {"index": 0},
    }
    store.create(
        conversation_id=conv,
        original_message="删除 security user_allowlist 第 0 条",
        classification=classification,
        request_id="req-fix3-2",
    )

    fake_session = _StubSession()
    fake_sm = MagicMock()
    fake_sm.get_session.return_value = fake_session
    fake_app_state = SimpleNamespace(session_manager=fake_sm)
    fake_request = SimpleNamespace(app=SimpleNamespace(state=fake_app_state))

    # 应返回 StreamingResponse / dict — 不是 _RiskAuthorizedReplay
    result = await chat_mod._handle_pending_risk_answer(
        request=fake_request,
        conversation_id=conv,
        answer="确认继续",
        as_stream=False,
    )
    assert not isinstance(result, chat_mod._RiskAuthorizedReplay)
    assert isinstance(result, dict)
    assert result.get("status") == "ok"


def test_format_controlled_action_result_neutral_on_error():
    """result.status != 'ok' 时不再说"已按确认执行"，避免欺骗用户。"""
    from openkitsune.api.routes import chat as chat_mod
    from openkitsune.core.confirmation_state import ConfirmationDecision

    err_result = {
        "status": "error",
        "error": "no_controlled_entry",
        "message": "该操作尚无受控执行入口",
    }
    text = chat_mod._format_controlled_action_result(
        ConfirmationDecision.CONFIRM,
        err_result,
        original_message="rm -rf /",
    )

    assert "已按确认执行" not in text
    assert "受控操作未能执行" in text
