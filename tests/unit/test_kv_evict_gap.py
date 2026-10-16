"""推理间隙驱逐（drain_gap_kv_evict）测试。"""

import asyncio
import unittest.mock as mock

import pytest

from openkitsune.core._context_runtime import ContextManager


class _FakeBrain:
    pass


def _make_cm():
    cm = ContextManager(brain=_FakeBrain())
    cm.last_compaction_spans = [{"start_index": 0, "end_index": 2, "op": "DROP"}]
    cm.last_compaction_source = [
        {"role": "user", "content": "目标"},
        {"role": "assistant", "content": "结论"},
    ]
    return cm


def test_no_pending_is_noop() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = False
    cm.kv_gap_evict_callback = mock.MagicMock()
    result = asyncio.run(cm.drain_gap_kv_evict())
    assert result is None
    cm.kv_gap_evict_callback.assert_not_called()


def test_no_callback_is_noop() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = True
    cm.kv_gap_evict_callback = None
    assert asyncio.run(cm.drain_gap_kv_evict()) is None


def test_drain_clears_pending_on_stop() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = True
    cm.kv_gap_evict_callback = mock.MagicMock(
        return_value={"ok": True, "action": "gap_pause_stop", "coverage": 0.5}
    )
    result = asyncio.run(cm.drain_gap_kv_evict())
    assert result["action"] == "gap_pause_stop"
    assert cm.gap_evict_pending is False
    # 载荷携带 spans + 源消息（供真实 tokenizer 换算；经 asyncio.to_thread
    # 以位置参数传递）
    args, _kwargs = cm.kv_gap_evict_callback.call_args
    payload = args[0]
    assert payload["spans"][0]["start_index"] == 0
    assert payload["messages"][0]["role"] == "user"


def test_drain_restores_pending_when_busy() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = True
    cm.kv_gap_evict_callback = mock.MagicMock(
        return_value={"ok": True, "action": "skip_busy"}
    )
    asyncio.run(cm.drain_gap_kv_evict())
    assert cm.gap_evict_pending is True  # 忙碌：等下一间隙窗口


def test_drain_survives_callback_error() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = True

    def boom(payload):
        raise RuntimeError("server down")

    cm.kv_gap_evict_callback = boom
    try:
        assert asyncio.run(cm.drain_gap_kv_evict()) is None
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"drain 不得抛错: {exc}")
    assert cm.gap_evict_pending is False  # 失败后不再反复尝试


def test_low_coverage_pending_cleared() -> None:
    cm = _make_cm()
    cm.gap_evict_pending = True
    cm.kv_gap_evict_callback = mock.MagicMock(
        return_value={"ok": True, "action": "skip_low_coverage"}
    )
    asyncio.run(cm.drain_gap_kv_evict())
    assert cm.gap_evict_pending is False
