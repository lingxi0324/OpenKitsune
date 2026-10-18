"""openkitsune-brain 长期记忆工具接入测试。

覆盖：
- OKMEM_TOOL_SCHEMAS 已合并进 MEMORY_TOOLS；
- 每个 brain_* 工具都有显式 ApprovalClass；
- MemoryHandler 能把调用分发到 Provider，并同步当前会话；
- 关闭开关时返回可读的禁用提示。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from openkitsune.memory.okmem_provider import OKMEM_TOOL_NAMES
from openkitsune.memory.public_api import MemoryRecord
from openkitsune.tools.definitions.memory import MEMORY_TOOLS
from openkitsune.tools.handlers.memory import MemoryHandler


class _StubProvider:
    session_id = "stub"

    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def recall_pipeline(
        self, user_input: str, *, scene: str = "mix", budget_chars: int = 4000
    ) -> dict:
        return {"memory_context": f"ctx:{user_input}", "scene": scene}

    async def health(self) -> dict:
        return {"status": "ok", "okmem": True}

    async def progress(self, *, session_id: str = "") -> dict:
        return {"snapshot": {"goal": "测试目标"}, "session_id": session_id}

    async def knowledge_search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return [MemoryRecord(id="fusion:1", content=f"知识:{query}", score=0.8)]

    async def proactive_review(self, *, limit: int = 30) -> dict:
        return {"total": 1, "items": [{"kind": "recall_due"}]}

    async def backfill_knowledge(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
        source: str = "memories",
        since_ts: str = "",
        last_rowid: int = 0,
    ) -> dict:
        return {
            "ok": True,
            "dry_run": dry_run,
            "source": source,
            "since_ts": since_ts,
            "last_rowid": last_rowid,
            "imported": 0,
        }

    async def record_emotion(
        self,
        label: str,
        *,
        intensity: float = 0.5,
        trigger_event: str = "",
        need_type: str = "",
        boundary: str = "",
    ) -> dict:
        return {"emotion_id": 1, "label": label, "intensity": intensity}

    async def emotion_state(self) -> dict:
        return {"label": "平静", "intensity": 0.3}

    def detect_emotion(self, text: str) -> dict:
        return {"label": "平静", "intensity": 0.2, "text": text}

    async def maintain_sessions(self, *, ttl_days: float = 7, apply: bool = False) -> dict:
        return {"ok": True, "ttl_days": ttl_days, "apply": apply, "archived": 0}

    async def save_turn(
        self,
        user_message: str = "",
        assistant_answer: str | None = None,
        *,
        session_id: str = "",
        signals: dict | None = None,
    ) -> dict:
        self.saved.append(
            {
                "user_message": user_message,
                "assistant_answer": assistant_answer,
                "session_id": session_id or self.session_id,
            }
        )
        return {"user": ["1"], "assistant": ["2"]}


def _agent(provider) -> SimpleNamespace:
    return SimpleNamespace(
        _okmem_provider=provider,
        memory_manager=SimpleNamespace(_current_session_id="s_test"),
    )


def test_brain_tools_are_in_memory_definitions() -> None:
    names = {tool["name"] for tool in MEMORY_TOOLS}
    assert set(OKMEM_TOOL_NAMES) <= names
    for tool in MEMORY_TOOLS:
        if tool["name"] not in OKMEM_TOOL_NAMES:
            continue
        assert tool["category"] == "Memory"
        assert tool["input_schema"]["type"] == "object"


def test_brain_tools_have_approval_classes() -> None:
    for name in OKMEM_TOOL_NAMES:
        assert name in MemoryHandler.TOOLS
        assert name in MemoryHandler.TOOL_CLASSES


async def test_okmem_health_dispatch_and_session_sync() -> None:
    provider = _StubProvider()
    agent = _agent(provider)
    handler = MemoryHandler(agent)

    result = await handler.handle_structured("okmem_health", {})
    payload = json.loads(result)

    assert payload["ok"] is True
    assert payload["result"]["status"] == "ok"
    assert provider.session_id == "s_test"


async def test_okmem_recall_returns_context() -> None:
    handler = MemoryHandler(_agent(_StubProvider()))
    result = await handler.handle_structured(
        "okmem_recall", {"user_input": "回顾项目决策", "scene": "task"}
    )
    payload = json.loads(result)
    assert payload["result"]["memory_context"] == "ctx:回顾项目决策"
    assert payload["result"]["scene"] == "task"


async def test_okmem_save_turn_dispatches() -> None:
    provider = _StubProvider()
    handler = MemoryHandler(_agent(provider))
    result = await handler.handle_structured(
        "okmem_save_turn",
        {"user_message": "记住：周五前完成", "assistant_answer": "好的"},
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert provider.saved[0]["user_message"] == "记住：周五前完成"
    assert provider.saved[0]["session_id"] == "s_test"


@pytest.mark.parametrize(
    ("tool_name", "params"),
    [
        ("okmem_recall", {"user_input": "回顾项目"}),
        ("okmem_knowledge_search", {"query": "河图洛书", "limit": 3}),
        ("okmem_save_turn", {"user_message": "记住这个", "assistant_answer": "好"}),
        ("okmem_proactive_review", {"limit": 5}),
        ("okmem_health", {}),
        ("okmem_progress", {"session_id": "s_test"}),
        ("okmem_backfill", {"limit": 5, "dry_run": True}),
        ("okmem_record_emotion", {"label": "疲惫", "intensity": 0.6}),
        ("okmem_emotion_state", {}),
        ("okmem_detect_emotion", {"text": "今天有点累"}),
        ("okmem_maintain_sessions", {"ttl_days": 7, "apply": False}),
    ],
)
async def test_all_brain_tools_dispatch(tool_name: str, params: dict) -> None:
    handler = MemoryHandler(_agent(_StubProvider()))
    result = await handler.handle_structured(tool_name, params)
    payload = json.loads(result)
    assert payload["ok"] is True, payload


async def test_brain_tool_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENKITSUNE_OKMEM_ENABLED", "0")
    handler = MemoryHandler(_agent(None))
    result = await handler.handle_structured("okmem_health", {})
    assert "未启用" in result
