"""desktop_state（实时桌面清单）与截图分析缩放测试。"""

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


def _state_payload() -> dict:
    return {
        "ok": True,
        "context_id": "agent",
        "screen_size": {"width": 1920, "height": 1080},
        "pointer": {"x": 10, "y": 20},
        "active_window": {
            "title": "Active",
            "process_name": "active.exe",
            "class_name": "ActiveClass",
            "bbox": [0, 0, 800, 600],
            "is_focused": True,
        },
        "windows": [
            {
                "title": f"W{i}",
                "process_name": "p.exe",
                "bbox": [i, 0, i + 50, 50],
                "is_visible": True,
            }
            for i in range(5)
        ],
        "capabilities": {"mss": "ok", "pyautogui": "ok"},
        "screenshot": {"ok": False, "path": "", "width": 0, "height": 0},
        "errors": [],
    }


def test_state_refresh_clears_cache_and_trims_windows(monkeypatch):
    import openkitsune.tools.desktop.state as state_mod
    from openkitsune.tools.desktop.tools import DesktopToolHandler

    calls = {"clear": 0, "kwargs": None}

    def fake_clear():
        calls["clear"] += 1

    def fake_collect(**kwargs):
        calls["kwargs"] = kwargs
        return _state_payload()

    monkeypatch.setattr(state_mod, "clear_state_cache", fake_clear)
    monkeypatch.setattr(state_mod, "clear_prompt_context_cache", fake_clear)
    monkeypatch.setattr(state_mod, "collect_state", fake_collect)

    payload = DesktopToolHandler()._collect_state_payload(
        {"refresh": True, "max_windows": 2}
    )

    assert calls["clear"] == 2
    assert payload["success"] is True
    assert payload["windows_total"] == 5
    assert len(payload["windows"]) == 2
    assert calls["kwargs"]["include_screenshot"] is False


def test_state_without_refresh_keeps_cache(monkeypatch):
    import openkitsune.tools.desktop.state as state_mod
    from openkitsune.tools.desktop.tools import DesktopToolHandler

    calls = {"clear": 0}

    def fake_clear():
        calls["clear"] += 1

    monkeypatch.setattr(state_mod, "clear_state_cache", fake_clear)
    monkeypatch.setattr(state_mod, "clear_prompt_context_cache", fake_clear)
    monkeypatch.setattr(state_mod, "collect_state", lambda **kwargs: _state_payload())

    DesktopToolHandler()._collect_state_payload({"refresh": False})

    assert calls["clear"] == 0


def test_state_result_is_rendered_for_llm(monkeypatch):
    import openkitsune.tools.desktop.state as state_mod
    from openkitsune.tools.desktop.tools import DesktopToolHandler
    from openkitsune.tools.handlers.desktop import DesktopHandler

    monkeypatch.setattr(state_mod, "clear_state_cache", lambda: None)
    monkeypatch.setattr(state_mod, "clear_prompt_context_cache", lambda: None)
    monkeypatch.setattr(state_mod, "collect_state", lambda **kwargs: _state_payload())

    payload = DesktopToolHandler()._collect_state_payload({"max_windows": 3})
    text = DesktopHandler.__new__(DesktopHandler)._format_result("desktop_state", payload)

    assert "桌面状态(实时)" in text
    assert "屏幕: 1920x1080 指针: 10,20" in text
    assert "活动窗口: Active" in text
    assert "可见窗口: 5（显示 3）" in text
    assert "bbox=[0, 0, 50, 50]" in text


def test_resize_for_analysis_caps_large_screenshots():
    from PIL import Image

    from openkitsune.tools.desktop.capture import ScreenCapture

    capture = ScreenCapture()
    large = Image.new("RGB", (1920, 1080))
    resized = capture.resize_for_analysis(large)
    assert resized.size == (1280, 720)

    small = Image.new("RGB", (640, 480))
    assert capture.resize_for_analysis(small).size == (640, 480)

    ultra = Image.new("RGB", (3840, 2160))
    assert capture.resize_for_analysis(ultra).size == (1280, 720)


def test_activity_log_orders_and_feeds_state():
    from openkitsune.tools.desktop import state as state_mod

    state_mod.clear_activity()
    try:
        state_mod.record_activity("open", target=r"C:\tmp\demo", detail="dir")
        state_mod.record_activity("click", x=12, y=34, window="Demo")

        recent = state_mod.recent_activity(5)
        assert [item["kind"] for item in recent] == ["click", "open"]
        assert recent[1]["target"] == r"C:\tmp\demo"

        payload = state_mod.stable_state(screen_size={"width": 100, "height": 100})
        assert payload["activity"][0]["kind"] == "click"
    finally:
        state_mod.clear_activity()


def test_state_renders_recent_activity():
    from openkitsune.tools.desktop import state as state_mod
    from openkitsune.tools.desktop.tools import DesktopToolHandler
    from openkitsune.tools.handlers.desktop import DesktopHandler

    state_mod.clear_activity()
    monkeypatch_target = state_mod.collect_state
    state_mod.collect_state = lambda **kwargs: {
        **_state_payload(),
        "activity": [
            {"kind": "open", "target": r"C:\demo", "ts": "2026-10-22T10:00:00Z"},
            {"kind": "focus", "target": "Trae CN", "ts": "2026-10-22T09:59:00Z"},
        ],
    }
    try:
        payload = DesktopToolHandler()._collect_state_payload({"refresh": False})
        text = DesktopHandler.__new__(DesktopHandler)._format_result("desktop_state", payload)
        assert "最近活动" in text
        assert r"C:\demo" in text
        assert "Trae CN" in text
    finally:
        state_mod.collect_state = monkeypatch_target
        state_mod.clear_activity()


def test_open_api_rejects_empty_target():
    import asyncio

    from openkitsune.api.routes.desktop import OpenTargetBody, desktop_open

    result = asyncio.run(desktop_open(OpenTargetBody(target="   ")))
    assert result["ok"] is False


def test_click_api_rejects_out_of_bounds_without_clicking():
    import asyncio

    from openkitsune.api.routes.desktop import DesktopClickBody, desktop_click

    result = asyncio.run(desktop_click(DesktopClickBody(x=-1, y=-1)))
    assert result["ok"] is False
    assert "out of screen bounds" in result["error"]

