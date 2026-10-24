"""desktop_open（打开文件/目录/网址）共享实现测试。"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="desktop automation is Windows-only"
)

# CI 只装 [dev] extras：Windows runner 上也跳过（缺少 mss/pyautogui 等）。
pytest.importorskip(
    "openkitsune.tools.desktop",
    reason="desktop automation requires Windows + desktop extras (mss/pyautogui/pywinauto)",
    exc_type=ImportError,
)


@pytest.fixture()
def open_env(monkeypatch):
    """拦截 ShellExecute / 前台激活 / 活动记录，返回采集容器。"""
    import openkitsune.tools.desktop.open_target as mod

    calls: dict = {"startfile": [], "activity": [], "activated": []}

    monkeypatch.setattr(mod.os, "startfile", lambda t: calls["startfile"].append(t))
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mod, "_activate_opened_window", calls["activated"].append)
    monkeypatch.setattr(
        mod,
        "collect_active_context",
        lambda: {"title": "Active Window", "location": "C:/tmp"},
    )
    monkeypatch.setattr(
        mod,
        "record_activity",
        lambda kind, **fields: calls["activity"].append({"kind": kind, **fields}),
    )
    return mod, calls


def test_open_url_prefixes_scheme(open_env):
    mod, calls = open_env

    result = mod.open_target("www.example.com")

    assert result["ok"] is True
    assert result["kind"] == "url"
    assert result["target"] == "https://www.example.com"
    assert calls["startfile"] == ["https://www.example.com"]
    assert calls["activity"][0]["kind"] == "open"
    assert calls["activity"][0]["target"] == "https://www.example.com"


def test_open_https_url_kept_as_is(open_env):
    mod, calls = open_env

    result = mod.open_target("https://example.com/a?b=1")

    assert result["kind"] == "url"
    assert calls["startfile"] == ["https://example.com/a?b=1"]
    assert result["active_window"]["title"] == "Active Window"


def test_open_file_and_directory(open_env, tmp_path):
    mod, calls = open_env
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")

    file_result = mod.open_target(f'"{file_path}"')
    dir_result = mod.open_target(str(tmp_path))

    assert file_result["kind"] == "file"
    assert file_result["target"] == str(file_path.resolve())
    assert dir_result["kind"] == "dir"
    assert dir_result["target"] == str(tmp_path.resolve())
    assert calls["startfile"] == [str(file_path.resolve()), str(tmp_path.resolve())]
    assert [item["detail"] for item in calls["activity"]] == ["file", "dir"]
    assert calls["activated"] == ["note.txt", tmp_path.name]


def test_open_missing_path_does_not_launch(open_env):
    mod, calls = open_env

    result = mod.open_target("D:/definitely/not/here.txt")

    assert result["ok"] is False
    assert "Path not found" in result["error"]
    assert calls["startfile"] == []
    assert calls["activity"] == []


def test_open_empty_target_rejected(open_env):
    mod, calls = open_env

    result = mod.open_target("   ")

    assert result["ok"] is False
    assert result["error"] == "target is required"
    assert calls["startfile"] == []


@pytest.mark.asyncio
async def test_handler_open_delegates_and_validates(monkeypatch):
    import openkitsune.tools.desktop.open_target as mod
    from openkitsune.tools.desktop.tools import DesktopToolHandler

    seen: list[str] = []
    monkeypatch.setattr(
        mod, "open_target", lambda target: seen.append(target) or {"ok": True}
    )

    handler = DesktopToolHandler()
    empty = await handler.handle("desktop_open", {"target": ""})
    ok = await handler.handle("desktop_open", {"target": "C:/tmp"})

    assert empty == {"error": "target is required"}
    assert ok == {"ok": True}
    assert seen == ["C:/tmp"]
