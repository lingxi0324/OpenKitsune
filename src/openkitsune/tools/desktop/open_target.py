"""打开文件路径 / 网址的共享实现。

面板（``/api/desktop/open``）与 AI 工具（``desktop_open``）共用同一逻辑：
- 目录用资源管理器打开，文件用默认程序打开，URL 用默认浏览器打开
- 打开后尝试把目标窗口带到前台
- 记录活动（完整路径/网址 + 活动窗口），供 AI 感知
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from .state import collect_active_context, record_activity

_URL_PATTERN = re.compile(r"^(https?://|file://|www\.)", re.IGNORECASE)
_MAX_ACTIVATE_WAIT = 1.2


def _activate_opened_window(name: str) -> None:
    """按文件名/目录名尝试把刚打开的窗口带到前台。"""
    if not name:
        return
    try:
        from .controller import get_controller

        controller = get_controller()
        window = controller.uia.find_window_fuzzy(name, timeout=_MAX_ACTIVATE_WAIT)
        if window is not None:
            controller.uia.activate_window(window)
            time.sleep(0.35)
    except Exception:  # noqa: BLE001 - 激活失败不影响“已打开”的事实
        pass


def open_target(target: str) -> dict[str, Any]:
    """打开路径或网址，返回结构化结果并写入活动记录。"""
    raw = os.path.expandvars(os.path.expanduser(str(target or "").strip().strip('"')))
    if not raw:
        return {"ok": False, "error": "target is required"}

    if _URL_PATTERN.match(raw):
        url = raw if not raw.lower().startswith("www.") else f"https://{raw}"
        os.startfile(url)  # noqa: S606 - ShellExecute 打开默认浏览器
        kind, opened, window_name = "url", url, ""
    else:
        path = Path(raw).resolve()
        if not path.exists():
            return {"ok": False, "error": f"Path not found: {raw}"}
        os.startfile(str(path))  # noqa: S606 - ShellExecute 打开文件/目录
        kind = "dir" if path.is_dir() else "file"
        opened = str(path)
        window_name = path.name or str(path)

    time.sleep(0.9)
    _activate_opened_window(window_name)
    context = collect_active_context()
    record_activity(
        "open",
        target=opened,
        detail=kind,
        window=context.get("title"),
        location=context.get("location"),
    )
    return {
        "ok": True,
        "kind": kind,
        "target": opened,
        "active_window": context,
        "detail": kind,
        "message": f"Opened {kind}: {opened}",
    }
