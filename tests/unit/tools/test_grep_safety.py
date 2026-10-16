"""PR-A1: grep 路径黑名单与正则校验（不测真实大目录递归）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from openkitsune.tools.file import FileTool


@pytest.mark.parametrize(
    "dangerous_path",
    [
        Path.home() / ".openkitsune" / "runtime" / "sessions",
        Path.home() / ".openkitsune" / "workspaces" / "proj",
        Path("/tmp/.openkitsune/runtime_stub") if Path("/tmp").exists() else None,
    ],
)
def test_grep_path_forbidden_blocks_openkitsune_data_plane(dangerous_path):
    """含 ``.openkitsune/runtime`` / ``workspaces`` 的路径必须被拒。"""
    if dangerous_path is None:
        pytest.skip("posix /tmp unavailable")
    reason = FileTool._grep_path_forbidden(dangerous_path)
    assert reason is not None
    assert "protected" in reason.lower() or "refuse" in reason.lower()


def test_grep_path_forbidden_root():
    posix_root = Path("/")
    reason = FileTool._grep_path_forbidden(posix_root)
    assert reason is not None
    assert "root" in reason.lower()


@pytest.mark.asyncio
async def test_grep_invalid_regex_raises():
    ft = FileTool(base_path=str(Path.cwd()))
    with pytest.raises(ValueError, match="Invalid regex"):
        await ft.grep("(", path=".")
