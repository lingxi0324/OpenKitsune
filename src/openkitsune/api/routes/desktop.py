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

logger = logging.getLogger(__name__)

router = APIRouter()


def _desktop_available() -> bool:
    return sys.platform == "win32"


def _file_url(path: str) -> str:
    """将本地截图路径转为 /api/files 可访问的 URL。"""
    return "/api/files?path=" + quote(str(path))


@router.get("/api/desktop/state")
async def desktop_state(
    include_screenshot: bool = False,
    context_id: str = "",
):
    """Return the current Windows desktop state snapshot.

    Query params:
        include_screenshot: 是否现场截取一张新图（默认只返回最近截图，更快）
        context_id: 会话/聊天上下文标识，用于截图分目录存储

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
        from openkitsune.tools.desktop.state import collect_state

        return collect_state(
            include_screenshot=include_screenshot,
            context_id=context_id,
            screenshot_transport="ephemeral",
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
async def desktop_screenshot(context_id: str = ""):
    """Capture a fresh desktop screenshot and return its path + file URL."""
    if not _desktop_available():
        return {
            "ok": False,
            "platform": sys.platform,
            "errors": ["desktop_screenshot is Windows-only"],
        }

    def _capture() -> dict:
        from openkitsune.tools.desktop.state import capture_screenshot

        return capture_screenshot(context_id=context_id, transport="path")

    try:
        result = await asyncio.to_thread(_capture)
    except Exception as exc:  # noqa: BLE001
        logger.error("[DesktopState] /api/desktop/screenshot failed: %s", exc, exc_info=True)
        return {"ok": False, "errors": [str(exc)]}

    if result.get("ok") and result.get("path"):
        result["file_url"] = _file_url(result["path"])
    return result
