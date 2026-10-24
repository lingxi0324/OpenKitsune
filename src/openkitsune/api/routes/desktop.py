"""Desktop state API routes.

提供 AI 桌面可视化方法逻辑的 HTTP 出口（参照 agent-zero ``plugins/_desktop/helpers/desktop_routes.py``）：

- ``GET /api/desktop/state``    → 当前桌面状态快照（屏幕/指针/活动窗口/可见窗口/最近截图/能力）
- ``GET /api/desktop/screenshot`` → 现场截取一张新截图

设计约束：
- 仅 win32 可用，其余平台返回结构化降级（ok=False + errors）
- 阻塞采集（UIA 枚举 / mss 截图）放入 asyncio.to_thread，避免卡住事件循环
- 截图文件路径经 /api/files 提供访问（files.py 支持绝对路径）
- 永不抛 500：任何异常转为 ok=False + errors
"""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import quote

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class WindowActionBody(BaseModel):
    """窗口操作请求体（面板点击窗口 / 用户手动操作）。"""

    action: str
    title: str | None = None
    handle: int | None = None


class OpenTargetBody(BaseModel):
    """打开文件路径 / 网址请求体。"""

    target: str


class DesktopClickBody(BaseModel):
    """面板截图点击穿透请求体（屏幕绝对坐标）。"""

    x: int
    y: int
    button: str = "left"
    double: bool = False


def _desktop_available() -> bool:
    return sys.platform == "win32"


def _file_url(path: str) -> str:
    """将本地截图路径转为 /api/files 可访问的 URL。"""
    return "/api/files?path=" + quote(str(path))


@router.get("/api/desktop/state")
async def desktop_state(
    include_screenshot: bool = False,
    context_id: str = "",
    refresh: bool = False,
    screenshot_max_width: int = 1280,
    screenshot_max_height: int = 720,
):
    """Return the current Windows desktop state snapshot.

    Query params:
        include_screenshot: 是否现场截取一张新图（默认只返回最近截图，更快）
        context_id: 会话/聊天上下文标识，用于截图分目录存储
        refresh: 是否清空 5 秒状态缓存后实时重新采集
        screenshot_max_width / screenshot_max_height: 预览截图缩放上限（0 = 原尺寸）

    截图存储：include_screenshot 走 ephemeral（仅保留最新一张，供前端轮询），
    持久化截图请调用 ``GET /api/desktop/screenshot``。
    """
    if not _desktop_available():
        return {
            "ok": False,
            "platform": sys.platform,
            "errors": ["desktop_state is Windows-only"],
        }

    def _collect() -> dict:
        if refresh:
            from openkitsune.tools.desktop.state import (
                clear_prompt_context_cache,
                clear_state_cache,
            )

            clear_state_cache()
            clear_prompt_context_cache()

        from openkitsune.tools.desktop.state import collect_state

        return collect_state(
            include_screenshot=include_screenshot,
            context_id=context_id,
            screenshot_transport="ephemeral",
            screenshot_max_width=max(0, int(screenshot_max_width or 0)),
            screenshot_max_height=max(0, int(screenshot_max_height or 0)),
        )

    try:
        state = await asyncio.to_thread(_collect)
    except Exception as exc:  # noqa: BLE001 -- 永不抛 500
        logger.error("[DesktopState] /api/desktop/state failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}

    shot = state.get("screenshot") or {}
    if shot.get("ok") and shot.get("path"):
        shot["file_url"] = _file_url(shot["path"])
    return state


@router.get("/api/desktop/screenshot")
async def desktop_screenshot(
    context_id: str = "",
    max_width: int = 0,
    max_height: int = 0,
):
    """Capture a fresh desktop screenshot and return its path + file URL."""
    if not _desktop_available():
        return {
            "ok": False,
            "platform": sys.platform,
            "errors": ["desktop_screenshot is Windows-only"],
        }

    def _capture() -> dict:
        from openkitsune.tools.desktop.state import capture_screenshot

        return capture_screenshot(
            context_id=context_id,
            transport="path",
            max_width=max(0, int(max_width or 0)),
            max_height=max(0, int(max_height or 0)),
        )

    try:
        result = await asyncio.to_thread(_capture)
    except Exception as exc:  # noqa: BLE001
        logger.error("[DesktopState] /api/desktop/screenshot failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}

    if result.get("ok") and result.get("path"):
        result["file_url"] = _file_url(result["path"])
    return result


@router.post("/api/desktop/window")
async def desktop_window_action(body: WindowActionBody):
    """对指定窗口执行 switch/minimize/maximize/restore/close。

    面板里用户点击窗口列表项 → 调用本接口把窗口置前（协同操作）；
    AI 侧对应 ``desktop_window`` 工具，二者共享同一套底层能力。
    """
    if not _desktop_available():
        return {"ok": False, "errors": ["desktop_window is Windows-only"]}

    action = str(body.action or "").strip().lower()
    aliases = {"activate": "switch", "focus": "switch", "open": "switch"}
    action = aliases.get(action, action)
    allowed = {"list", "switch", "minimize", "maximize", "restore", "close"}
    if action not in allowed:
        return {"ok": False, "error": f"Unsupported action: {body.action}"}

    def _run() -> dict:
        from openkitsune.tools.desktop.controller import get_controller

        controller = get_controller()
        if action == "list":
            windows = [w.to_dict() for w in controller.list_windows(visible_only=True)]
            return {"ok": True, "action": "list", "windows": windows, "count": len(windows)}

        result = controller.window_action(action, body.title, handle=body.handle)
        payload = {"ok": bool(result.success), **result.to_dict()}
        if not result.success:
            payload["error"] = result.error or f"Failed to {action} window"
        else:
            try:
                from openkitsune.tools.desktop.state import record_activity

                record_activity(
                    "focus",
                    window=body.title or body.handle,
                    handle=body.handle,
                    action=action,
                )
            except Exception:  # noqa: BLE001
                pass
        return payload

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.error("[DesktopState] /api/desktop/window failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}


@router.get("/api/desktop/window/elements")
async def desktop_window_elements(
    title: str = "",
    handle: int = 0,
    depth: int = 2,
):
    """返回窗口信息与 UI 元素树（面板展开详情 / AI 感知共用）。"""
    if not _desktop_available():
        return {"ok": False, "errors": ["desktop_window_elements is Windows-only"]}

    safe_depth = max(1, min(int(depth or 2), 4))

    def _run() -> dict:
        from openkitsune.tools.desktop.controller import get_controller

        controller = get_controller()
        window_title = title.strip()
        info = None
        if handle:
            window = controller.uia.find_window(handle=int(handle), timeout=2.0)
            if window is not None:
                window_title = window.name or window_title
                info = window.to_window_info().to_dict()
        elif window_title:
            window = controller.uia.find_window_fuzzy(window_title, timeout=2.0)
            if window is not None:
                info = window.to_window_info().to_dict()

        if not window_title and not handle:
            return {"ok": False, "error": "title or handle required"}

        text = ""
        error = ""
        try:
            text = controller.inspect_text(window_title=window_title or None, depth=safe_depth)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        if len(text) > 20000:
            text = text[:20000] + "\n... (元素树已截断)"

        return {
            "ok": bool(text) and not error,
            "title": window_title,
            "handle": handle or (info or {}).get("handle", 0),
            "depth": safe_depth,
            "window": info,
            "text": text,
            "error": error,
        }

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[DesktopState] /api/desktop/window/elements failed: %s", exc, exc_info=True
        )
        return {"ok": False, "errors": [str(exc)]}


@router.post("/api/desktop/open")
async def desktop_open(body: OpenTargetBody):
    """打开文件路径 / 网址（用户从面板打开，AI 通过活动记录感知）。"""
    if not _desktop_available():
        return {"ok": False, "errors": ["desktop_open is Windows-only"]}

    target = str(body.target or "").strip().strip('"')
    if not target:
        return {"ok": False, "error": "target is required"}

    def _run() -> dict:
        from openkitsune.tools.desktop.open_target import open_target

        return open_target(target)

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.error("[DesktopState] /api/desktop/open failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}


@router.post("/api/desktop/click")
async def desktop_click(body: DesktopClickBody):
    """预览图点击穿透：必要时最小化遮挡窗口，执行真实点击后恢复。

    浏览器模式下面板所在窗口通常会遮挡目标；先最小化前台窗口，
    点击完成后再以「不抢焦点」的方式恢复，避免打断新打开的窗口。
    """
    if not _desktop_available():
        return {"ok": False, "errors": ["desktop_click is Windows-only"]}

    button = str(body.button or "left").strip().lower()
    if button not in {"left", "right", "middle"}:
        return {"ok": False, "error": f"Unsupported button: {body.button}"}

    def _run() -> dict:
        import ctypes
        import time as _time

        from openkitsune.tools.desktop.controller import get_controller
        from openkitsune.tools.desktop.state import record_activity

        controller = get_controller()
        width, height = controller.mouse.get_screen_size()
        x, y = int(body.x), int(body.y)
        if not (0 <= x < width and 0 <= y < height):
            return {
                "ok": False,
                "error": f"Coordinates out of screen bounds: ({x},{y}) for {width}x{height}",
            }

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user32 = ctypes.windll.user32
        foreground = int(user32.GetForegroundWindow() or 0)
        hidden = False
        if foreground:
            rect = _RECT()
            if user32.GetWindowRect(foreground, ctypes.byref(rect)) and (
                rect.left <= x <= rect.right and rect.top <= y <= rect.bottom
            ):
                user32.ShowWindow(foreground, 6)  # SW_MINIMIZE
                hidden = True
                _time.sleep(0.3)

                # 等待最小化动画结束：直到该点不再属于被隐藏的窗口，
                # 否则点击会落在面板/浏览器自身，造成误操作。
                deadline = _time.time() + 1.2
                while _time.time() < deadline:
                    hwnd_at = int(user32.WindowFromPoint(_POINT(x, y)) or 0)
                    root = int(user32.GetAncestor(hwnd_at, 2) or hwnd_at) if hwnd_at else 0
                    if root != foreground:
                        break
                    _time.sleep(0.12)
                else:
                    hwnd_at = int(user32.WindowFromPoint(_POINT(x, y)) or 0)
                    root = int(user32.GetAncestor(hwnd_at, 2) or hwnd_at) if hwnd_at else 0
                    if root == foreground:
                        user32.ShowWindow(foreground, 4)
                        return {
                            "ok": False,
                            "error": (
                                "target is still covered by the panel window; "
                                "move the panel aside and retry"
                            ),
                            "x": x,
                            "y": y,
                        }

        result = controller.mouse.click(
            x, y, button=button, clicks=2 if body.double else 1
        )
        _time.sleep(0.5)

        from openkitsune.tools.desktop.state import collect_active_context

        context = collect_active_context()

        if hidden and foreground:
            user32.ShowWindow(foreground, 4)  # SW_SHOWNOACTIVATE：恢复但不抢焦点

        record_activity(
            "click",
            x=x,
            y=y,
            window=context.get("title"),
            location=context.get("location"),
        )
        return {
            "ok": bool(result.success),
            "x": x,
            "y": y,
            "hidden_window": hidden,
            "active_window": context,
            "message": result.message,
        }

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        logger.error("[DesktopState] /api/desktop/click failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}
