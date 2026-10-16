import asyncio
import subprocess
import sys
import textwrap

import pytest

from openkitsune.logging.session_buffer import SessionLogBuffer


def test_finalizer_can_log_while_buffer_is_read():
    # Isolate GC and the logging singleton. A regression must time out this
    # subprocess rather than deadlocking the entire pytest worker.
    script = textwrap.dedent("""\
        import gc
        import logging
        from collections import deque
        from openkitsune.logging.handlers import SessionLogHandler
        from openkitsune.logging.session_buffer import SessionLogBuffer

        gc.disable()
        buffer = SessionLogBuffer()
        buffer.add_log("INFO", "test", "existing", session_id="test")
        logger = logging.getLogger("finalizer-regression")
        logger.propagate = False
        logger.addHandler(SessionLogHandler())

        class Finalizer:
            def __del__(self):
                logger.error("collected task", extra={"session_id": "test"})

        class CollectOnRead(deque):
            def __iter__(self):
                # Force the GC timing seen when pending asyncio tasks become
                # unreachable between tests, instead of relying on thresholds.
                gc.collect()
                return super().__iter__()

        buffer._buffers["test"] = CollectOnRead(buffer._buffers["test"])
        pending = Finalizer()
        pending.cycle = pending
        del pending
        logs = buffer.get_logs("test", include_global=False)
        assert [entry["message"] for entry in logs] == ["existing", "collected task"]
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_current_log_session_is_task_local():
    buffer = SessionLogBuffer(max_entries_per_session=10, max_sessions=10)
    buffer.clear_all()
    buffer.clear_current_session()

    async def write_log(session_id: str, message: str):
        buffer.set_current_session(session_id)
        await asyncio.sleep(0)
        buffer.add_log("INFO", "test", message)
        return buffer.get_current_session()

    current_a, current_b = await asyncio.gather(
        write_log("session-a", "from-a"),
        write_log("session-b", "from-b"),
    )

    assert current_a == "session-a"
    assert current_b == "session-b"
    assert [log["message"] for log in buffer.get_logs("session-a", include_global=False)] == [
        "from-a"
    ]
    assert [log["message"] for log in buffer.get_logs("session-b", include_global=False)] == [
        "from-b"
    ]
