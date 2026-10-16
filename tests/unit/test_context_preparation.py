"""上下文准备（任务快照 prepare/restore）测试：防 KV 清理失忆。"""

import asyncio
import json
import unittest.mock as mock
from pathlib import Path

from openkitsune.core._context_preparation import (
    TaskContextSnapshot,
    is_restore_block,
    prepare_task_context,
    restore_task_context,
)
from openkitsune.core._context_runtime import ContextManager


def _estimate(messages) -> int:
    total = 0
    for msg in messages:
        c = msg.get("content", "")
        total += max(1, len(c) // 2 if isinstance(c, str) else 5)
    return max(total, 1)


def _m(role, content):
    return {"role": role, "content": content}


def _make_cm(tmp_path, monkeypatch):
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "context_preparation_dir", "ctx_prep_test")
    monkeypatch.setattr(settings, "context_preparation_keep", 3)
    # 清理共享持久化目录（测试间隔离）
    prep_dir = Path(settings.data_dir) / settings.context_preparation_dir
    if prep_dir.exists():
        for p in prep_dir.glob("*.json"):
            p.unlink(missing_ok=True)
    cm = ContextManager(brain=None)
    cm.last_compaction_spans = [{"start_index": 0, "end_index": 2, "op": "DROP"}]
    cm.last_compaction_source = [
        _m("user", "核心目标：完成端口扫描报告"),
        _m("assistant", "loading loading"),
        _m("assistant", "扫描完成，端口 4317 开放"),
        _m("user", "继续分析剩余服务"),
    ]
    return cm


def test_prepare_task_context_extracts_goal_and_tail() -> None:
    messages = [
        _m("user", "核心目标：完成端口扫描报告"),
        _m("assistant", "loading"),
        _m("assistant", "扫描完成，端口 4317 开放"),
        _m("user", "继续分析剩余服务"),
    ]
    spans = [{"start_index": 0, "end_index": 2, "op": "DROP"}]
    snap = prepare_task_context(
        messages, spans, estimate_tokens=_estimate,
        tail_protect_fraction=0.4, recent_protect=1,
    )
    assert "端口扫描" in snap.task_goal
    assert len(snap.recent_process) >= 2  # 尾部进程原文备份
    assert snap.compacted_spans[0]["start_index"] == 0


def test_restore_block_has_marker_and_goal() -> None:
    snap = TaskContextSnapshot(
        task_goal="完成端口扫描报告",
        progress_summary="assistant: 扫描完成，端口 4317 开放",
        recent_process=[_m("assistant", "扫描完成，端口 4317 开放")],
        compacted_spans=[{"start_index": 0, "end_index": 2}],
    )
    block = restore_task_context(snap)
    assert block["role"] == "system"
    assert "[任务上下文恢复]" in block["content"]
    assert "端口扫描" in block["content"]
    assert is_restore_block(block) is True
    assert is_restore_block(_m("user", "普通输入")) is False


def test_cm_prepare_persists_and_restore_roundtrip(tmp_path, monkeypatch) -> None:
    cm = _make_cm(tmp_path, monkeypatch)
    saved = cm.prepare_task_context(session_id="s1")
    assert saved is not None
    assert saved["task_goal"]
    # 快照文件已落盘
    base = Path(cm._brain and "" or ".")  # 占位
    from openkitsune.config import settings

    prep_dir = Path(settings.data_dir) / settings.context_preparation_dir
    files = list(prep_dir.glob("s1_*.json"))
    assert len(files) == 1

    block = cm.restore_task_context(session_id="s1")
    assert block is not None
    assert "[任务上下文恢复]" in block["content"]
    # 快照内容与恢复块一致
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["snapshot_id"] == saved["snapshot_id"]


def test_cm_restore_none_when_missing(tmp_path, monkeypatch) -> None:
    cm = _make_cm(tmp_path, monkeypatch)
    assert cm.restore_task_context(session_id="nonexistent") is None


def test_cm_prepare_returns_none_without_spans(tmp_path, monkeypatch) -> None:
    cm = _make_cm(tmp_path, monkeypatch)
    cm.last_compaction_spans = []
    assert cm.prepare_task_context() is None


def test_gap_drain_prepares_snapshot_before_stop(tmp_path, monkeypatch) -> None:
    cm = _make_cm(tmp_path, monkeypatch)
    cm.gap_evict_pending = True
    cm.kv_gap_evict_callback = mock.MagicMock(
        return_value={"ok": True, "action": "gap_pause_stop"}
    )
    asyncio.run(cm.drain_gap_kv_evict())
    # stop 前已固话快照 + 恢复标记已置位（下次请求自动注入恢复卡）
    from openkitsune.config import settings

    prep_dir = Path(settings.data_dir) / settings.context_preparation_dir
    assert len(list(prep_dir.glob("default_*.json"))) == 1
    assert cm.context_preparation_pending is True
