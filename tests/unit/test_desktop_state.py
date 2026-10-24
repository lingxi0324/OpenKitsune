"""tests/unit/test_desktop_state.py

桌面状态采集 / 提示词注入 / API 路由的单元测试。

覆盖：
- ``_safe_context_id`` 路径清理
- ``stable_state`` 归一化（错误清空、截图默认值、能力兜底）
- ``collect_state`` 主路径与未启用降级（monkeypatch 重采集项，不碰真实 UIA）
- ``compact_prompt_context`` 渲染（有界窗口数、行动指引、空桌面降级）
- prompt builder 注入 ``[DESKTOP STATE]`` 块
- /api/desktop/state 与 /api/desktop/screenshot 路由（mock 采集函数）
- 非 win32 结构化降级
"""

from __future__ import annotations

import asyncio
import sys

import pytest

# 桌面自动化模块是 Windows-only 且需要 pyautogui/mss 等非 dev 依赖：
# CI（ubuntu/macos runner、以及未装 desktop extras 的 windows runner）上
# 顶层 import 会抛 ImportError，必须显式跳过而不是让 collection 失败。
desktop_state = pytest.importorskip(
    "openkitsune.tools.desktop.state",
    reason="desktop automation is Windows-only and needs pyautogui/mss (desktop extras)",
    exc_type=ImportError,
)
desktop_routes = pytest.importorskip(
    "openkitsune.api.routes.desktop",
    reason="desktop API routes depend on the Windows desktop module",
    exc_type=ImportError,
)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


class TestSafeContextId:
    def test_sanitizes_separators(self):
        assert desktop_state._safe_context_id("a/b c:d") == "a_b_c_d"

    def test_empty_defaults(self):
        assert desktop_state._safe_context_id("") == "default"

    def test_all_separators_defaults(self):
        assert desktop_state._safe_context_id(".../..") == "default"

    def test_unicode_falls_back_to_default(self):
        assert desktop_state._safe_context_id("桌面会话") == "default"


class TestStableState:
    def test_normalizes_errors_to_str(self):
        result = desktop_state.stable_state(errors=["a", 42, ""])
        assert result["ok"] is False
        assert result["errors"] == ["a", "42"]

    def test_empty_screenshot_default(self):
        result = desktop_state.stable_state(context_id="s1")
        shot = result["screenshot"]
        assert shot["ok"] is False
        assert shot["context_id"] == "s1"
        assert shot["path"] == ""

    def test_capabilities_fallback_is_dict(self):
        result = desktop_state.stable_state(capabilities=None)
        assert isinstance(result["capabilities"], dict)
        assert "mss" in result["capabilities"]

    def test_happy_path_shape(self):
        shot = {"ok": True, "path": "C:/x.png", "format": "png",
                "captured_at": "2026-01-01T00:00:00Z", "recent": True,
                "context_id": "s1"}
        result = desktop_state.stable_state(
            context_id="s1",
            screen_size={"width": 1920, "height": 1080},
            pointer={"x": 10, "y": 20},
            active_window={"title": "Notepad", "class_name": "Notepad"},
            windows=[{"title": "W1", "class_name": "C1"}],
            screenshot=shot,
            capabilities={"mss": "ok"},
            errors=[],
        )
        assert result["ok"] is True
        assert result["screen_size"] == {"width": 1920, "height": 1080}
        assert result["active_window"]["title"] == "Notepad"
        assert result["screenshot"] is shot


# ---------------------------------------------------------------------------
# collect_state
# ---------------------------------------------------------------------------


_FAKE_HEAVY = {
    "screen_size": {"width": 1920, "height": 1080},
    "active_window": {"title": "Notepad", "class_name": "Notepad"},
    "windows": [{"title": "W1", "class_name": "C1"}, {"title": "W2", "class_name": "C2"}],
    "capabilities": {"mss": "ok", "pyautogui": "ok", "pywinauto": "ok", "PIL": "ok"},
}

_FAKE_SHOT = {
    "ok": True, "path": "C:/shots/desktop.png", "format": "png",
    "width": 1920, "height": 1080,
    "captured_at": "2026-01-01T00:00:00Z", "recent": True,
    "context_id": "s1", "error": "",
}


class TestCollectState:
    def test_happy_path_includes_screenshot(self, monkeypatch):
        monkeypatch.setattr(desktop_state, "_state_enabled", lambda: True)
        monkeypatch.setattr(desktop_state, "_collect_heavy_state",
                            lambda errors: dict(_FAKE_HEAVY))
        monkeypatch.setattr(desktop_state, "_collect_pointer",
                            lambda errors: {"x": 30, "y": 40})
        monkeypatch.setattr(desktop_state, "capture_screenshot",
                            lambda **kw: dict(_FAKE_SHOT))

        result = desktop_state.collect_state(include_screenshot=True, context_id="s1")

        assert result["ok"] is True
        assert result["screen_size"]["width"] == 1920
        assert result["pointer"] == {"x": 30, "y": 40}
        assert len(result["windows"]) == 2
        assert result["screenshot"]["ok"] is True
        assert result["screenshot"]["path"] == "C:/shots/desktop.png"

    def test_disabled_degrades(self, monkeypatch):
        monkeypatch.setattr(desktop_state, "_state_enabled", lambda: False)
        result = desktop_state.collect_state()
        assert result["ok"] is False
        assert result["screen_size"] == {"width": 0, "height": 0}
        assert any("未启用" in err for err in result["errors"])

    def test_missing_capability_appends_error(self, monkeypatch):
        monkeypatch.setattr(desktop_state, "_state_enabled", lambda: True)
        heavy = dict(_FAKE_HEAVY)
        heavy["capabilities"] = {"mss": "", "pyautogui": "ok",
                                 "pywinauto": "ok", "PIL": "ok"}
        monkeypatch.setattr(desktop_state, "_collect_heavy_state",
                            lambda errors: heavy)
        monkeypatch.setattr(desktop_state, "_collect_pointer",
                            lambda errors: {"x": 0, "y": 0})

        result = desktop_state.collect_state()
        assert result["ok"] is False
        assert any("mss" in err for err in result["errors"])


# ---------------------------------------------------------------------------
# compact_prompt_context
# ---------------------------------------------------------------------------


class TestCompactPromptContext:
    def test_renders_bounded_block(self):
        windows = [
            {"title": f"W{i}", "class_name": f"C{i}"} for i in range(10)
        ]
        fake_state = desktop_state.stable_state(
            context_id="s1",
            screen_size={"width": 1920, "height": 1080},
            pointer={"x": 11, "y": 22},
            active_window={"title": "Notepad", "class_name": "Notepad"},
            windows=windows,
            screenshot={"ok": True, "path": "C:/shot.png", "recent": True,
                        "format": "png", "captured_at": "x", "context_id": "s1"},
            capabilities={"mss": "ok"},
            errors=[],
        )
        block = desktop_state.compact_prompt_context(fake_state)

        assert block.startswith("[DESKTOP STATE]")
        assert "- screen=1920x1080 pointer=11,22" in block
        assert "- active=Notepad (Notepad)" in block
        assert "W0 (C0)" in block and "W4 (C4)" in block
        assert "W5 (C5)" not in block  # 有界：最多 5 个窗口
        assert "- recent_screenshot=C:/shot.png" in block
        assert "desktop_screenshot()" in block  # 行动指引（默认自动 OCR + 画面理解）
        assert "desktop_press" in block  # 空格/回车等单键工具
        assert "verify=" in block

    def test_unknown_screen_returns_empty(self):
        fake_state = desktop_state.stable_state(screen_size={"width": 0, "height": 0})
        assert desktop_state.compact_prompt_context(fake_state) == ""

    def test_errors_line_capped(self):
        fake_state = desktop_state.stable_state(
            screen_size={"width": 1920, "height": 1080},
            errors=["e1", "e2", "e3"],
        )
        block = desktop_state.compact_prompt_context(fake_state)
        assert "errors=e1; e2" in block
        assert "e3" not in block.split("errors=")[1]


# ---------------------------------------------------------------------------
# prompt builder 注入
# ---------------------------------------------------------------------------


class TestPromptBuilderInjection:
    def test_builder_section_renders_on_win32(self, monkeypatch):
        if sys.platform != "win32":
            pytest.skip("desktop state is Windows-only")
        from openkitsune.prompt import builder

        fake_state = desktop_state.stable_state(
            screen_size={"width": 1920, "height": 1080},
            pointer={"x": 1, "y": 2},
            active_window={"title": "Notepad", "class_name": "Notepad"},
            windows=[{"title": "W1", "class_name": "C1"}],
            capabilities={"mss": "ok"},
            errors=[],
        )
        real_render = desktop_state.compact_prompt_context
        desktop_state.clear_prompt_context_cache()
        monkeypatch.setattr(
            "openkitsune.tools.desktop.state.compact_prompt_context",
            lambda *a, **kw: real_render(fake_state),
        )
        section = builder._build_desktop_state_section()
        assert section.startswith("[DESKTOP STATE]")
        assert "screen=1920x1080" in section
        desktop_state.clear_prompt_context_cache()

    def test_builder_section_empty_on_non_win32(self, monkeypatch):
        if sys.platform == "win32":
            pytest.skip("this host is Windows; win32 path asserted elsewhere")
        from openkitsune.prompt import builder

        assert builder._build_desktop_state_section() == ""


# ---------------------------------------------------------------------------
# 截图清理（ephemeral）
# ---------------------------------------------------------------------------


class TestScreenshotPruning:
    def _make_dir(self, tmp_path, context_id="ctx"):
        directory = tmp_path / "screenshots" / context_id
        directory.mkdir(parents=True)
        return directory

    def test_ephemeral_keeps_only_latest(self, tmp_path, monkeypatch):
        import time as _time

        directory = self._make_dir(tmp_path)
        monkeypatch.setattr(desktop_state, "screenshots_dir", lambda cid="": tmp_path / "screenshots" / cid)
        (tmp_path / "screenshots" / "ctx" / "a.png").write_bytes(b"x")
        (tmp_path / "screenshots" / "ctx" / "b.png").write_bytes(b"x")
        keep = tmp_path / "screenshots" / "ctx" / "c.png"
        keep.write_bytes(b"x")

        desktop_state._prune_screenshots(
            context_id="ctx", keep_path=keep, max_age_seconds=None
        )

        remaining = sorted(p.name for p in directory.iterdir())
        assert remaining == ["c.png"]  # 无论新旧，仅保留最新一张

    def test_default_age_window_keeps_recent(self, tmp_path, monkeypatch):
        import time as _time

        monkeypatch.setattr(desktop_state, "screenshots_dir", lambda cid="": tmp_path / "screenshots" / cid)
        directory = tmp_path / "screenshots" / "ctx"
        directory.mkdir(parents=True)
        old = directory / "old.png"
        old.write_bytes(b"x")
        old_time = _time.time() - 3600
        _os_utime = __import__("os").utime
        _os_utime(old, (old_time, old_time))
        recent = directory / "recent.png"
        recent.write_bytes(b"x")

        desktop_state._prune_screenshots(context_id="ctx")

        remaining = sorted(p.name for p in directory.iterdir())
        assert remaining == ["recent.png"]  # 超过新鲜度窗口的旧图被清理


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------


class TestDesktopRoutes:
    def test_state_route_returns_snapshot(self, monkeypatch):
        fake = desktop_state.stable_state(
            context_id="s1",
            screen_size={"width": 1920, "height": 1080},
            pointer={"x": 0, "y": 0},
            windows=[],
            capabilities={"mss": "ok"},
            errors=[],
        )
        captured: dict = {}

        def _fake_collect(**kw):
            captured.update(kw)
            return fake

        monkeypatch.setattr("openkitsune.tools.desktop.state.collect_state", _fake_collect)
        result = asyncio.run(
            desktop_routes.desktop_state(include_screenshot=False, context_id="s1")
        )
        assert result["ok"] is True
        assert result["context_id"] == "s1"
        assert result["screen_size"]["width"] == 1920
        # 轮询场景：截图走 ephemeral，避免截图文件堆积
        assert captured["screenshot_transport"] == "ephemeral"

    def test_state_route_adds_file_url_for_recent_shot(self, monkeypatch):
        shot = {"ok": True, "path": "C:/shot.png", "format": "png",
                "captured_at": "x", "recent": True, "context_id": "s1"}
        fake = desktop_state.stable_state(
            screen_size={"width": 1920, "height": 1080},
            screenshot=shot,
            capabilities={"mss": "ok"},
            errors=[],
        )
        monkeypatch.setattr(
            "openkitsune.tools.desktop.state.collect_state",
            lambda **kw: fake,
        )
        result = asyncio.run(desktop_routes.desktop_state(include_screenshot=False))
        assert result["screenshot"]["file_url"].startswith("/api/files?path=")

    def test_screenshot_route_returns_path_and_url(self, monkeypatch):
        shot = {"ok": True, "path": "C:/shot.png", "format": "png",
                "width": 1920, "height": 1080, "captured_at": "x",
                "recent": True, "context_id": "s1", "error": ""}
        monkeypatch.setattr(
            "openkitsune.tools.desktop.state.capture_screenshot",
            lambda **kw: shot,
        )
        result = asyncio.run(desktop_routes.desktop_screenshot(context_id="s1"))
        assert result["ok"] is True
        assert result["file_url"].startswith("/api/files?path=")

    def test_route_degradation_on_non_win32(self, monkeypatch):
        monkeypatch.setattr(desktop_routes, "_desktop_available", lambda: False)
        result = asyncio.run(desktop_routes.desktop_state())
        assert result["ok"] is False
        assert "Windows-only" in result["errors"][0]

    def test_route_survives_collect_exception(self, monkeypatch):
        def boom(**kw):
            raise RuntimeError("uia exploded")

        monkeypatch.setattr("openkitsune.tools.desktop.state.collect_state", boom)
        result = asyncio.run(desktop_routes.desktop_state())
        assert result["ok"] is False
        assert "uia exploded" in result["errors"][0]
