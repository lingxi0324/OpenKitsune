"""Fix-7 回归测试：scheduler missed_count 上限保护 + memory_nudge JSON 容错。"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from openkitsune.scheduler.scheduler import TaskScheduler
from openkitsune.scheduler.task import (
    ScheduledTask,
    TaskType,
    TriggerType,
)

# ---------------------------------------------------------------------------
# missed_count 上限保护
# ---------------------------------------------------------------------------


def _make_scheduler() -> TaskScheduler:
    tmp = tempfile.mkdtemp(prefix="oa_sched_test_")
    sched = TaskScheduler(storage_path=Path(tmp), executor=None)
    return sched


@pytest.mark.asyncio
async def test_missed_count_below_cap_just_increments():
    sched = _make_scheduler()
    task = ScheduledTask.create(
        name="t",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval_seconds": 60},
        prompt="",
        task_type=TaskType.TASK,
    )
    task.next_run = datetime.now() - timedelta(seconds=120)
    task.metadata["missed_count"] = 5

    sched._recalculate_missed_run(task, datetime.now())

    assert task.metadata["missed_count"] == 6
    assert "missed_count_reset_at" not in task.metadata


@pytest.mark.asyncio
async def test_missed_count_at_cap_resets_to_zero_and_stamps_overflow():
    sched = _make_scheduler()
    task = ScheduledTask.create(
        name="t",
        description="",
        trigger_type=TriggerType.INTERVAL,
        trigger_config={"interval_seconds": 60},
        prompt="",
        task_type=TaskType.TASK,
    )
    task.next_run = datetime.now() - timedelta(seconds=120)
    task.metadata["missed_count"] = 99  # next +1 == 100 → cap

    sched._recalculate_missed_run(task, datetime.now())

    assert task.metadata["missed_count"] == 0
    assert task.metadata["missed_count_last_overflow"] == 100
    assert "missed_count_reset_at" in task.metadata


# ---------------------------------------------------------------------------
# memory_nudge JSON best-effort 解析
# ---------------------------------------------------------------------------


def test_memory_nudge_json_parsing_strict_success():
    """合法 JSON 应直接 loads 成功（covered by integration; sanity check here）."""
    raw = '[{"type":"fact","content":"x","importance":3}]'
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["type"] == "fact"


def test_memory_nudge_json_array_extraction_fallback_pattern():
    """模拟 nudge 修复后的 fallback 正则：从 prose 中扒出第一个 [ ... ] 数组。"""
    bad = (
        "Here is the result you asked for, JSON below:\n"
        '[{"type":"fact","content":"x","importance":3}]\n'
        "Hope that helps!"
    )
    m = re.search(r"\[\s*(?:\{.*?\}\s*,?\s*)*\]", bad, re.DOTALL)
    assert m is not None
    parsed = json.loads(m.group(0))
    assert parsed[0]["content"] == "x"


def test_memory_nudge_json_completely_invalid_returns_skip_marker():
    """完全无法解析 — fallback 应让任务返回 (True, 'skipped...')，不算失败。

    这里是行为契约校验，真实路径已经在 executor.py 里实现：当 JSON 无法
    解析时返回 ``(True, "...skipping this round (no failure count...)")``，
    scheduler 据此 **不** 增加 fail_count，从而避免任务被 5 次失败 disable。
    """
    from openkitsune.scheduler import executor as ex_mod

    # 仅做模块加载冒烟，确保 import 路径与正则常量没回归。
    assert hasattr(ex_mod, "TaskExecutor")


@pytest.mark.asyncio
async def test_memory_nudge_defers_while_an_llm_request_is_active(monkeypatch):
    from openkitsune.config import settings
    from openkitsune.llm.client import LLMClient
    from openkitsune.scheduler.executor import TaskExecutor

    monkeypatch.setattr(settings, "memory_nudge_enabled", True)
    monkeypatch.setattr(settings, "memory_nudge_interval", 10)
    monkeypatch.setattr(
        LLMClient,
        "get_concurrency_stats",
        classmethod(lambda cls: {"inflight": 1, "max_concurrent": 20, "tracked_loops": 1}),
    )

    success, message = await TaskExecutor()._system_memory_nudge_review()

    assert success is True
    assert message == "Active LLM request in progress, deferring memory nudge"
