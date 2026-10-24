"""桌面宏核心引擎（DesktopController.macro）与 desktop_macro 工具委派测试。

只验证组合编排 / 白名单 / 重复 / 中止 / 聚焦 / 兜底释放，不触发真实鼠标键盘。
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="desktop automation is Windows-only"
)

# CI 只装 [dev] extras，不装 desktop extras（mss/pyautogui/pywinauto）：
# Windows runner 上也必须跳过，而不是让运行时 import 失败。
pytest.importorskip(
    "openkitsune.tools.desktop",
    reason="desktop automation requires Windows + desktop extras (mss/pyautogui/pywinauto)",
    exc_type=ImportError,
)


# ---------------------------------------------------------------------------
# 假原语：记录调用并返回 ActionResult 形结果
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, success=True, action="", message="ok", error=None, **extra):
        self._success = success
        self._action = action
        self._message = message
        self._error = error
        self._extra = extra

    def to_dict(self):
        payload = {
            "success": self._success,
            "action": self._action,
            "message": self._message,
            **self._extra,
        }
        if self._error:
            payload["error"] = self._error
        return payload


class _FakeMouse:
    def __init__(self, records):
        self._records = records

    def get_position(self):
        self._records.append(("mouse.position", {}))
        return (50, 60)

    def get_screen_size(self):
        return (1920, 1080)

    def move_to(self, x, y, duration=None):
        self._records.append(("mouse.move_to", {"x": x, "y": y}))
        return _FakeResult(action="move_to", message="moved")

    def move_relative(self, dx, dy, duration=None, raw=False):
        self._records.append(("mouse.move_relative", {"dx": dx, "dy": dy}))
        return _FakeResult(action="move_relative", message="moved")

    def hover(self, x, y, pause=0.3):
        self._records.append(("mouse.hover", {"x": x, "y": y}))
        return _FakeResult(action="hover", message="hovered")

    def click(self, x, y, button="left", clicks=1, modifiers=None):
        self._records.append(
            ("mouse.click", {"x": x, "y": y, "button": button, "clicks": clicks})
        )
        return _FakeResult(action="click", message="clicked")

    def drag(self, from_x, from_y, to_x, to_y, duration=0.5, button="left", modifiers=None):
        self._records.append(
            ("mouse.drag", {"from": (from_x, from_y), "to": (to_x, to_y), "button": button})
        )
        return _FakeResult(action="drag", message="dragged")

    def scroll(self, amount, x=None, y=None, modifiers=None):
        self._records.append(("mouse.scroll", {"amount": amount}))
        return _FakeResult(action="scroll", message="scrolled")

    def hscroll(self, clicks, x=None, y=None):
        self._records.append(("mouse.hscroll", {"clicks": clicks}))
        return _FakeResult(action="hscroll", message="hscrolled")

    def mouse_down(self, x, y=None, button="left"):
        self._records.append(("mouse.down", {"button": button}))
        return _FakeResult(action="down", message="down")

    def mouse_up(self, x, y=None, button="left"):
        self._records.append(("mouse.up", {"button": button}))
        return _FakeResult(action="up", message="up")


class _FakeKeyboard:
    def __init__(self, records):
        self._records = records

    def type_text(self, text, method="auto"):
        self._records.append(("keyboard.type_text", {"text": text, "method": method}))
        return _FakeResult(action="type", message=f"Typed {len(text)} characters")

    def press(self, key):
        self._records.append(("keyboard.press", {"key": key}))
        return _FakeResult(action="press", message="pressed")

    def press_multiple(self, key, presses=1):
        self._records.append(("keyboard.press_multiple", {"key": key, "presses": presses}))
        return _FakeResult(action="press", message="pressed")

    def hotkey(self, *keys):
        self._records.append(("keyboard.hotkey", {"keys": keys}))
        return _FakeResult(action="hotkey", message="hotkey")

    def key_down(self, key):
        self._records.append(("keyboard.key_down", {"key": key}))
        return _FakeResult(action="key_down", message="down")

    def key_up(self, key):
        self._records.append(("keyboard.key_up", {"key": key}))
        return _FakeResult(action="key_up", message="up")

    def release_all(self):
        self._records.append(("keyboard.release_all", {}))
        return _FakeResult(action="release_all", message="released")

    def select_all(self):
        self._records.append(("keyboard.select_all", {}))
        return _FakeResult(action="select_all", message="selected")


def _make_core(monkeypatch=None):
    from openkitsune.tools.desktop.controller import DesktopController

    records: list[tuple] = []
    ctrl = DesktopController()
    ctrl._mouse = _FakeMouse(records)
    ctrl._keyboard = _FakeKeyboard(records)
    return ctrl, records


def _activation_success(title):
    from openkitsune.tools.desktop.types import ActionResult

    return ActionResult(success=True, action="switch_window", target=title, message="ok")


def _activation_failure(title):
    from openkitsune.tools.desktop.types import ActionResult

    return ActionResult(
        success=False, action="switch_window", target=title, error="window not found"
    )


# ---------------------------------------------------------------------------
# 核心引擎 DesktopController.macro
# ---------------------------------------------------------------------------


def test_macro_runs_steps_in_order_and_repeats():
    ctrl, records = _make_core()
    result = ctrl.macro(
        [
            {"tool": "desktop_key", "params": {"action": "press", "key": "enter"}},
            {"tool": "desktop_mouse", "params": {"action": "click", "x": 10, "y": 20}},
        ],
        repeat=2,
    )

    assert result["success"] is True
    assert result["steps_completed"] == 4
    assert [r["tool"] for r in result["results"]] == [
        "desktop_key",
        "desktop_mouse",
        "desktop_key",
        "desktop_mouse",
    ]
    assert all(r["success"] for r in result["results"])
    # 结束兜底释放：release_all + left/right/middle
    assert ("keyboard.release_all", {}) in records
    assert ("mouse.up", {"button": "left"}) in records
    assert ("mouse.up", {"button": "right"}) in records
    assert ("mouse.up", {"button": "middle"}) in records


def test_macro_supports_all_whitelisted_tools():
    ctrl, records = _make_core()
    result = ctrl.macro(
        [
            {"tool": "desktop_type", "params": {"text": "abc", "method": "paste"}},
            {"tool": "desktop_press", "params": {"key": "space", "times": 2}},
            {"tool": "desktop_hotkey", "params": {"keys": ["ctrl", "c"]}},
            {"tool": "desktop_key", "params": {"action": "type", "text": "hi"}},
            {"tool": "desktop_key", "params": {"action": "down", "key": "w"}},
            {"tool": "desktop_key", "params": {"action": "up", "key": "w"}},
            {"tool": "desktop_key", "params": {"action": "release_all"}},
            {"tool": "desktop_mouse", "params": {"action": "move", "x": 5, "y": 6}},
            {"tool": "desktop_mouse", "params": {"action": "move_relative", "dx": 1, "dy": 2}},
            {"tool": "desktop_mouse", "params": {"action": "hover", "x": 7, "y": 8}},
            {"tool": "desktop_mouse", "params": {"action": "drag", "x": 0, "y": 0, "to_x": 9, "to_y": 9}},
            {"tool": "desktop_mouse", "params": {"action": "double_click", "x": 1, "y": 2}},
            {"tool": "desktop_mouse", "params": {"action": "right_click", "x": 1, "y": 2}},
            {"tool": "desktop_mouse", "params": {"action": "middle_click", "x": 1, "y": 2}},
            {"tool": "desktop_mouse", "params": {"action": "scroll", "direction": "up", "amount": 2}},
            {"tool": "desktop_scroll", "params": {"direction": "down", "amount": 3}},
            {"tool": "desktop_click", "params": {"x": 3, "y": 4, "button": "left", "clicks": 1}},
            {"tool": "desktop_wait", "params": {"ms": 0}},
        ],
        sleep_fn=lambda _s: None,
    )

    assert result["success"] is True
    assert result["steps_completed"] == 18
    assert all(r["success"] for r in result["results"])
    assert ("keyboard.type_text", {"text": "abc", "method": "paste"}) in records
    assert ("keyboard.press_multiple", {"key": "space", "presses": 2}) in records
    assert ("keyboard.hotkey", {"keys": ("ctrl", "c")}) in records
    assert ("mouse.move_to", {"x": 5, "y": 6}) in records
    assert ("mouse.move_relative", {"dx": 1, "dy": 2}) in records
    assert ("mouse.hover", {"x": 7, "y": 8}) in records
    assert ("mouse.drag", {"from": (0, 0), "to": (9, 9), "button": "left"}) in records
    assert ("mouse.click", {"x": 1, "y": 2, "button": "left", "clicks": 2}) in records
    assert ("mouse.click", {"x": 1, "y": 2, "button": "right", "clicks": 1}) in records
    assert ("mouse.click", {"x": 1, "y": 2, "button": "middle", "clicks": 1}) in records
    assert ("mouse.scroll", {"amount": 2}) in records
    assert ("mouse.scroll", {"amount": -3}) in records
    assert ("mouse.click", {"x": 3, "y": 4, "button": "left", "clicks": 1}) in records
    assert ("keyboard.key_down", {"key": "w"}) in records
    assert ("keyboard.key_up", {"key": "w"}) in records
    assert ("keyboard.release_all", {}) in records


def test_macro_stops_on_failed_step():
    class _BoomMouse(_FakeMouse):
        def click(self, x, y, button="left", clicks=1, modifiers=None):
            return _FakeResult(success=False, action="click", error="boom")

    ctrl = None
    from openkitsune.tools.desktop.controller import DesktopController

    records: list[tuple] = []
    ctrl = DesktopController()
    ctrl._mouse = _BoomMouse(records)
    ctrl._keyboard = _FakeKeyboard(records)

    result = ctrl.macro(
        [
            {"tool": "desktop_key", "params": {"action": "press", "key": "enter"}},
            {"tool": "desktop_mouse", "params": {"action": "click", "x": 1, "y": 2}},
        ]
    )

    assert result["success"] is False
    # 失败步本身已尝试执行并记录（含 error），stop_on_error 中止后续步骤
    assert [r["tool"] for r in result["results"]] == ["desktop_key", "desktop_mouse"]
    assert result["results"][1]["success"] is False
    assert "boom" in result["results"][1]["message"]
    assert result["steps_completed"] == 2


def test_macro_continues_when_stop_on_error_false():
    class _BoomMouse(_FakeMouse):
        def click(self, x, y, button="left", clicks=1, modifiers=None):
            return _FakeResult(success=False, action="click", error="boom")

    from openkitsune.tools.desktop.controller import DesktopController

    records: list[tuple] = []
    ctrl = DesktopController()
    ctrl._mouse = _BoomMouse(records)
    ctrl._keyboard = _FakeKeyboard(records)

    result = ctrl.macro(
        [
            {"tool": "desktop_key", "params": {"action": "press", "key": "enter"}},
            {"tool": "desktop_mouse", "params": {"action": "click", "x": 1, "y": 2}},
        ],
        stop_on_error=False,
    )

    assert result["success"] is False
    assert [r["tool"] for r in result["results"]] == ["desktop_key", "desktop_mouse"]


def test_macro_rejects_disallowed_tool_and_releases():
    ctrl, records = _make_core()
    result = ctrl.macro(
        [{"tool": "run_shell", "params": {"command": "whoami"}}]
    )

    assert result["success"] is False
    assert "not allowed" in result["results"][0]["error"]
    assert ("keyboard.release_all", {}) in records


def test_macro_validates_step_count():
    ctrl, _ = _make_core()

    empty = ctrl.macro([])
    assert "error" in empty

    too_many = ctrl.macro([{"tool": "desktop_key", "params": {"action": "press", "key": "a"}}] * 51)
    assert "error" in too_many


def test_macro_focus_window_activates_first(monkeypatch):
    from openkitsune.tools.desktop.controller import DesktopController

    records: list[tuple] = []
    ctrl = DesktopController()
    ctrl._mouse = _FakeMouse(records)
    ctrl._keyboard = _FakeKeyboard(records)
    activated: list[str] = []

    def fake_switch(title, timeout=None):
        activated.append(title)
        return _activation_success(title)

    monkeypatch.setattr(ctrl, "switch_to_window", fake_switch)

    result = ctrl.macro(
        [
            {"tool": "desktop_type", "params": {"text": "hi"}},
            {"tool": "desktop_press", "params": {"key": "enter"}},
        ],
        focus_window="notepad - 记事本",
        focus_delay_ms=0,
    )

    assert activated == ["notepad - 记事本"]
    assert result["success"] is True
    assert result["results"][0] == {
        "round": 0,
        "step": 0,
        "tool": "desktop_focus",
        "success": True,
        "message": "Focused window 'notepad - 记事本'",
    }
    assert [r["tool"] for r in result["results"][1:]] == ["desktop_type", "desktop_press"]


def test_macro_focus_window_failure_aborts_before_steps(monkeypatch):
    from openkitsune.tools.desktop.controller import DesktopController

    records: list[tuple] = []
    ctrl = DesktopController()
    ctrl._mouse = _FakeMouse(records)
    ctrl._keyboard = _FakeKeyboard(records)

    def fake_switch(title, timeout=None):
        return _activation_failure(title)

    monkeypatch.setattr(ctrl, "switch_to_window", fake_switch)

    result = ctrl.macro(
        [{"tool": "desktop_type", "params": {"text": "hi"}}],
        focus_window="missing-window",
        focus_delay_ms=0,
    )

    assert result["success"] is False
    assert result["results"][0]["tool"] == "desktop_focus"
    assert "activation failed" in result["results"][0]["error"]
    # 没有执行任何真实步骤
    assert not any(r.get("tool") == "desktop_type" for r in result["results"])


# ---------------------------------------------------------------------------
# desktop_macro 工具处理器（委派核心引擎 + 校验快路径）
# ---------------------------------------------------------------------------


class _FakeCore:
    def __init__(self):
        self.calls: list[tuple] = []

    def macro(self, steps, **kwargs):
        self.calls.append((steps, kwargs))
        return {"success": True, "rounds": 1, "steps_completed": 0, "results": []}


def _make_handler():
    from openkitsune.tools.desktop.tools import DesktopToolHandler

    handler = DesktopToolHandler()
    core = _FakeCore()
    handler._controller = core
    return handler, core


async def test_handler_macro_delegates_to_core_engine():
    handler, core = _make_handler()

    result = await handler._handle_macro(
        {
            "steps": [
                {"tool": "desktop_key", "params": {"action": "press", "key": "enter"}},
                {"tool": "desktop_mouse", "params": {"action": "click", "x": 10, "y": 20}},
            ],
            "repeat": 2,
            "focus_window": "记事本",
            "focus_delay_ms": 100,
        }
    )

    assert result["success"] is True
    assert len(core.calls) == 1
    steps, kwargs = core.calls[0]
    assert len(steps) == 2
    assert kwargs["repeat"] == 2
    assert kwargs["focus_window"] == "记事本"
    assert kwargs["focus_delay_ms"] == 100
    assert kwargs["stop_on_error"] is True
    assert kwargs["release_at_end"] is True


async def test_handler_macro_validates_before_delegation():
    handler, core = _make_handler()

    empty = await handler._handle_macro({"steps": []})
    assert "error" in empty

    too_many = await handler._handle_macro(
        {"steps": [{"tool": "desktop_key", "params": {"action": "press", "key": "a"}}] * 51}
    )
    assert "error" in too_many

    assert core.calls == []
