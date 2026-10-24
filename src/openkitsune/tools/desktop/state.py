"""
OpenKitsune - Windows 桌面状态采集与感知上下文（AI 桌面可视化方法逻辑）

参照 agent-zero ``plugins/_desktop/helpers/desktop_state.py`` 的「观察方法逻辑」，
将其移植并适配到 OpenKitsune 的 Windows 桌面控制层（tools/desktop）：

1. ``collect_state()`` — 采集一次完整桌面状态快照：
   - 屏幕尺寸（mss）
   - 指针位置（pyautogui）
   - 活动窗口 + 可见窗口列表（UIA）
   - 能力探测（依赖是否可用）
   - 截图（可选，带新鲜度 / 聊天级目录 / 临时清理）
2. ``stable_state()`` — 归一化稳定输出（含错误清单，不抛异常）
3. ``compact_prompt_context()`` — 渲染 ``[DESKTOP STATE]`` 提示词块：
   让模型每轮都能感知当前桌面上下文，并遵循
   「坐标操作前先观察、操作后用新截图验证」的行动纪律
4. 截图管理：按 context 分目录存储，按新鲜度清理（默认 10 分钟）
5. CLI：``python -m openkitsune.tools.desktop.state state|observe|screenshot``

与桌面控制层的关系：
- 控制层负责「动手」（点击 / 输入 / 窗口操作 / UIA / 视觉识别）
- 本模块负责「感知与上下文」——把桌面状态变成模型可消费的结构化信息，
  是控制层的「眼睛与上下文记忆」，也是 /api/desktop 路由的数据源

平台：仅 win32。非 win32 或依赖缺失时优雅降级（ok=False + errors），
绝不向上抛异常破坏提示词构建或 API 响应。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

_PLATFORM = sys.platform

# 状态 TTL：窗口列表 / 屏幕尺寸等「重」采集项缓存秒数，提示词构建高频调用时避免反复枚举窗口
_DEFAULT_STATE_TTL = 5.0
# 截图新鲜度窗口：超过该秒数的截图视为过期
_RECENT_SCREENSHOT_SECONDS = 600
# 单次采集可见窗口上限
_MAX_WINDOWS = 20
# 提示词块中展示的窗口数上限
_PROMPT_WINDOW_LIMIT = 5

_SAFE_CONTEXT_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg"}

# 用户/AI 的桌面活动记录（最近打开、切换、点击），供面板展示与 AI 感知。
_ACTIVITY_MAX = 50
_activity_log: deque[dict[str, Any]] = deque(maxlen=_ACTIVITY_MAX)


def record_activity(kind: str, **fields: Any) -> dict[str, Any]:
    """记录一条桌面活动（打开路径/URL、窗口聚焦、点击穿透等）。"""
    entry: dict[str, Any] = {
        "kind": str(kind or "activity"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    _activity_log.appendleft(entry)
    return entry


def recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    """返回最近的活动记录（最新在前）。"""
    if limit <= 0:
        return []
    return list(_activity_log)[:limit]


def clear_activity() -> None:
    """清空活动记录（测试/隐私重置）。"""
    _activity_log.clear()


def collect_active_context() -> dict[str, Any]:
    """活动窗口信息 + 尽力读取地址栏/路径（浏览器 URL、资源管理器路径）。"""
    try:
        from .controller import get_controller
        from .uia.elements import UIAElementWrapper

        controller = get_controller()
        window = controller.get_active_window()
        if not window:
            return {}
        payload = window.to_dict()
        root = controller.uia.find_window(handle=window.handle, timeout=1.0)
        if root is None:
            return payload

        scanned = 0
        for child in root.control.descendants():
            scanned += 1
            if scanned > 1200:
                break
            try:
                wrapper = UIAElementWrapper(child)
                name = wrapper.name or ""
                value = wrapper.value or ""
                control_type = (wrapper.control_type or "").lower()
            except Exception:
                continue
            lowered = name.lower()
            if control_type == "edit" and (
                "address" in lowered or "地址" in name or "search" in lowered
            ):
                location = value or name
                if location:
                    payload["location"] = location
                    break
            if value and (
                value.startswith("http://")
                or value.startswith("https://")
                or re.match(r"^[A-Za-z]:\\", value)
            ):
                payload["location"] = value
                break
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DesktopState] active context failed: %s", exc)
        return {}

# 能力探测：名称 -> 可导入模块
_CAPABILITY_MODULES: dict[str, str] = {
    "mss": "mss",
    "pyautogui": "pyautogui",
    "pywinauto": "pywinauto",
    "PIL": "PIL",
}


def _state_enabled() -> bool:
    """状态采集开关（默认 win32 开启，可用环境变量关闭）。"""
    if _PLATFORM != "win32":
        return False
    value = os.getenv("DESKTOP_STATE_ENABLED", "1").strip().lower()
    return value not in ("0", "false", "no", "off")


def _state_ttl() -> float:
    try:
        return float(os.getenv("DESKTOP_STATE_TTL", str(_DEFAULT_STATE_TTL)))
    except ValueError:
        return _DEFAULT_STATE_TTL


def _safe_context_id(context_id: str = "") -> str:
    raw = str(context_id or "default")
    return _SAFE_CONTEXT_RE.sub("_", raw).strip("._") or "default"


def _state_root() -> Path:
    """状态根目录：优先 settings.project_root/data/desktop，兜底 cwd/data/desktop。"""
    try:
        from openkitsune.config import settings

        root = Path(getattr(settings, "project_root", "") or "").resolve()
        if root.is_dir():
            return root / "data" / "desktop"
    except Exception:
        pass
    return Path.cwd() / "data" / "desktop"


def screenshots_dir(context_id: str = "") -> Path:
    return _state_root() / "screenshots" / _safe_context_id(context_id)


# ---------------------------------------------------------------------------
# 状态缓存（重采集项：窗口列表 / 活动窗口 / 屏幕尺寸 / 能力）
# ---------------------------------------------------------------------------

_state_cache: dict[str, Any] = {"ts": 0.0, "payload": None}


def _cached_payload(ttl: float | None = None) -> dict[str, Any] | None:
    ttl = _state_ttl() if ttl is None else ttl
    if ttl <= 0:
        return None
    if _state_cache["payload"] is None:
        return None
    if time.monotonic() - _state_cache["ts"] > ttl:
        return None
    return _state_cache["payload"]


def _cache_payload(payload: dict[str, Any]) -> None:
    _state_cache["ts"] = time.monotonic()
    _state_cache["payload"] = payload


def clear_state_cache() -> None:
    """清空桌面状态缓存（供测试与隐私重置使用）。"""
    _state_cache["ts"] = 0.0
    _state_cache["payload"] = None

# ---------------------------------------------------------------------------
# 能力探测
# ---------------------------------------------------------------------------


def collect_capabilities() -> dict[str, str]:
    """探测桌面自动化依赖可用性：name -> "ok" / 空字符串。"""
    result: dict[str, str] = {}
    for name, module in _CAPABILITY_MODULES.items():
        try:
            __import__(module)
            result[name] = "ok"
        except Exception:
            result[name] = ""
    return result


def _require_capabilities(capabilities: dict[str, str]) -> list[str]:
    missing = [name for name, status in capabilities.items() if not status]
    errors: list[str] = []
    if missing:
        errors.append(
            "桌面状态采集依赖缺失: " + ", ".join(missing)
            + "（安装 mss / pyautogui / pywinauto / Pillow 后可用）"
        )
    return errors


# ---------------------------------------------------------------------------
# 状态采集
# ---------------------------------------------------------------------------


def _collect_screen_size(errors: list[str]) -> dict[str, int]:
    try:
        from .capture import get_capture

        width, height = get_capture().get_screen_size(0)
        return {"width": int(width), "height": int(height)}
    except Exception as exc:
        errors.append(f"屏幕尺寸读取失败: {exc}")
        return {"width": 0, "height": 0}


def _collect_pointer(errors: list[str]) -> dict[str, int]:
    try:
        from .actions import get_mouse

        x, y = get_mouse().get_position()
        return {"x": int(x), "y": int(y)}
    except Exception as exc:
        errors.append(f"指针位置读取失败: {exc}")
        return {"x": 0, "y": 0}


def _collect_active_window(errors: list[str]) -> dict[str, Any] | None:
    try:
        from .controller import get_controller

        window = get_controller().get_active_window()
        if window is not None:
            return window.to_dict()
    except Exception as exc:
        errors.append(f"活动窗口读取失败: {exc}")
    return None


def _collect_windows(errors: list[str]) -> list[dict[str, Any]]:
    try:
        from .controller import get_controller

        windows = get_controller().list_windows(visible_only=True)
        return [w.to_dict() for w in windows[:_MAX_WINDOWS]]
    except Exception as exc:
        errors.append(f"窗口列表读取失败: {exc}")
        return []


def _collect_heavy_state(errors: list[str]) -> dict[str, Any]:
    """采集「重」状态（带 TTL 缓存），供提示词构建与 API 高频调用复用。"""
    cached = _cached_payload()
    if cached is not None:
        return cached
    payload = {
        "screen_size": _collect_screen_size(errors),
        "active_window": _collect_active_window(errors),
        "windows": _collect_windows(errors),
        "capabilities": collect_capabilities(),
    }
    _cache_payload(payload)
    return payload


def latest_screenshot(context_id: str = "") -> dict[str, Any]:
    """返回最近的截图信息（带新鲜度标记），无截图时返回 ok=False。"""
    directory = screenshots_dir(context_id)
    if not directory.exists():
        return {
            "ok": False, "path": "", "format": "", "captured_at": "",
            "recent": False, "context_id": _safe_context_id(context_id),
        }
    try:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in _SCREENSHOT_SUFFIXES
        ]
    except OSError as exc:
        logger.debug("[DesktopState] screenshot dir scan failed: %s", exc)
        return {
            "ok": False, "path": "", "format": "", "captured_at": "",
            "recent": False, "context_id": _safe_context_id(context_id),
        }
    if not candidates:
        return {
            "ok": False, "path": "", "format": "", "captured_at": "",
            "recent": False, "context_id": _safe_context_id(context_id),
        }
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    age = max(0.0, time.time() - latest.stat().st_mtime)
    return {
        "ok": True,
        "path": str(latest),
        "format": latest.suffix.lower().lstrip("."),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest.stat().st_mtime)),
        "recent": age <= _RECENT_SCREENSHOT_SECONDS,
        "context_id": _safe_context_id(context_id),
    }


def capture_screenshot(
    *,
    path: str | Path | None = None,
    context_id: str = "",
    transport: str = "path",
    max_width: int = 0,
    max_height: int = 0,
) -> dict[str, Any]:
    """截取当前屏幕并保存，返回结构化结果。

    Args:
        path: 显式保存路径；为空时保存到 screenshots/<context>/desktop-<ts>.png
        context_id: 聊天/会话上下文标识，用于分目录
        transport: 存储方式（"path" 持久保存 / "ephemeral" 仅保留最新并清理旧图）
        max_width / max_height: 保存前缩小到指定上限（0 = 保持原尺寸）
            面板预览与视觉分析都用固定小图，避免大图难以读取/传输。

    Returns:
        {ok, path, format, width, height, captured_at, recent, context_id, error}
    """
    try:
        from PIL import Image as _PILImage

        from .controller import get_controller
    except Exception as exc:
        return {
            "ok": False, "path": "", "format": "", "width": 0, "height": 0,
            "captured_at": "", "recent": False,
            "context_id": _safe_context_id(context_id), "error": str(exc),
        }

    explicit = path is not None and str(path).strip() != ""
    if explicit:
        target = Path(path)
    else:
        directory = screenshots_dir(context_id)
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        millis = int((time.time() % 1) * 1000)
        target = directory / f"desktop-{timestamp}-{millis:03d}.png"

    try:
        img = get_controller().screenshot()
        if not isinstance(img, _PILImage.Image):
            raise TypeError("screenshot did not return a PIL Image")
        if max_width > 0 or max_height > 0:
            limit_w = max_width if max_width > 0 else img.width
            limit_h = max_height if max_height > 0 else img.height
            if img.width > limit_w or img.height > limit_h:
                ratio = min(limit_w / img.width, limit_h / img.height)
                img = img.resize(
                    (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                    _PILImage.Resampling.LANCZOS,
                )
        img.save(target, format="PNG")
        width, height = int(img.width), int(img.height)
    except Exception as exc:
        logger.error("[DesktopState] screenshot failed: %s", exc, exc_info=True)
        return {
            "ok": False, "path": "", "format": "", "width": 0, "height": 0,
            "captured_at": "", "recent": False,
            "context_id": _safe_context_id(context_id), "error": str(exc),
        }

    if str(transport).lower() == "ephemeral" and not explicit:
        # ephemeral 语义：只保留最新一张，其余无论新旧全部清理
        _prune_screenshots(context_id=context_id, keep_path=target, max_age_seconds=None)

    return {
        "ok": True,
        "path": str(target),
        "format": target.suffix.lower().lstrip(".") or "png",
        "width": width,
        "height": height,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recent": True,
        "context_id": _safe_context_id(context_id),
        "error": "",
    }


def _prune_screenshots(
    *,
    context_id: str = "",
    keep_path: Path | None = None,
    max_age_seconds: float | None = _RECENT_SCREENSHOT_SECONDS,
) -> None:
    """清理过期截图；keep_path 保留。max_age_seconds=None 时仅保留 keep_path。"""
    directory = screenshots_dir(context_id)
    if not directory.exists():
        return
    keep = keep_path.resolve() if keep_path is not None else None
    now = time.time()
    try:
        for candidate in directory.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in _SCREENSHOT_SUFFIXES:
                continue
            if keep is not None and candidate.resolve() == keep:
                continue
            if max_age_seconds is not None:
                try:
                    if now - candidate.stat().st_mtime <= max_age_seconds:
                        continue
                except OSError:
                    pass
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        if keep is None:
            try:
                directory.rmdir()
            except OSError:
                pass
    except OSError:
        pass


def collect_state(
    *,
    include_screenshot: bool = False,
    screenshot_path: str | Path | None = None,
    context_id: str = "",
    screenshot_transport: str = "path",
    screenshot_max_width: int = 0,
    screenshot_max_height: int = 0,
) -> dict[str, Any]:
    """采集一次完整的桌面状态快照（参照 agent-zero collect_state）。

    Args:
        include_screenshot: 是否现场截一张新图
        screenshot_path: 截图显式保存路径（可选）
        context_id: 聊天/会话上下文标识
        screenshot_transport: 截图存储方式（"path" / "ephemeral"）
        screenshot_max_width / screenshot_max_height: 截图缩放上限（0 = 原尺寸）

    Returns:
        稳定状态字典（永不抛异常）
    """
    errors: list[str] = []

    if not _state_enabled():
        return stable_state(
            context_id=context_id,
            screen_size={"width": 0, "height": 0},
            pointer={"x": 0, "y": 0},
            active_window=None,
            windows=[],
            screenshot={
                "ok": False, "path": "", "format": "", "captured_at": "",
                "recent": False, "context_id": _safe_context_id(context_id),
            },
            capabilities={},
            errors=["desktop_state 未启用（非 Windows 或 DESKTOP_STATE_ENABLED=0）"],
        )

    heavy = _collect_heavy_state(errors)
    errors.extend(_require_capabilities(heavy.get("capabilities") or {}))
    pointer = _collect_pointer(errors)

    screenshot: dict[str, Any] = {
        "ok": False, "path": "", "format": "", "captured_at": "",
        "recent": False, "context_id": _safe_context_id(context_id),
    }
    if include_screenshot:
        screenshot = capture_screenshot(
            path=screenshot_path,
            context_id=context_id,
            transport=screenshot_transport,
            max_width=screenshot_max_width,
            max_height=screenshot_max_height,
        )
    else:
        screenshot = latest_screenshot(context_id=context_id)

    return stable_state(
        context_id=context_id,
        screen_size=heavy.get("screen_size") or {"width": 0, "height": 0},
        pointer=pointer,
        active_window=heavy.get("active_window"),
        windows=heavy.get("windows") or [],
        screenshot=screenshot,
        capabilities=heavy.get("capabilities") or {},
        errors=errors,
    )


def stable_state(
    *,
    context_id: str = "",
    screen_size: dict[str, int] | None = None,
    pointer: dict[str, int] | None = None,
    active_window: dict[str, Any] | None = None,
    windows: list[dict[str, Any]] | None = None,
    screenshot: dict[str, Any] | None = None,
    capabilities: dict[str, str] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """归一化稳定状态输出（参照 agent-zero stable_state）。"""
    clean_errors = [str(item) for item in (errors or []) if str(item)]
    empty_shot = {
        "ok": False, "path": "", "format": "", "captured_at": "",
        "recent": False, "context_id": _safe_context_id(context_id),
    }
    return {
        "ok": not clean_errors,
        "context_id": _safe_context_id(context_id),
        "screen_size": screen_size or {"width": 0, "height": 0},
        "pointer": pointer or {"x": 0, "y": 0},
        "active_window": active_window,
        "windows": windows or [],
        "screenshot": screenshot or empty_shot,
        "capabilities": capabilities or collect_capabilities(),
        "activity": recent_activity(20),
        "errors": clean_errors,
    }


# ---------------------------------------------------------------------------
# 提示词上下文
# ---------------------------------------------------------------------------


def compact_prompt_context(state: dict[str, Any] | None = None) -> str:
    """渲染 ``[DESKTOP STATE]`` 提示词块。

    无可用桌面（非 win32 / 未启用 / 尺寸未知）时返回空字符串，
    避免向模型注入噪音。内容有界：最多 5 个窗口、前 2 条错误。
    """
    if state is None:
        state = collect_state(include_screenshot=False)

    screen_size = state.get("screen_size") or {}
    if not (screen_size.get("width") and screen_size.get("height")):
        return ""

    lines = ["[DESKTOP STATE]"]
    pointer = state.get("pointer") or {}
    lines.append(
        f"- screen={screen_size.get('width', 0)}x{screen_size.get('height', 0)} "
        f"pointer={pointer.get('x', 0)},{pointer.get('y', 0)}"
    )

    active = state.get("active_window") or {}
    if active:
        title = str(active.get("title") or "<untitled>")
        window_class = str(active.get("class_name") or active.get("process_name") or "")
        lines.append(f"- active={title}" + (f" ({window_class})" if window_class else ""))

    visible: list[str] = []
    for window in state.get("windows") or []:
        title = str(window.get("title") or "<untitled>")
        window_class = str(window.get("class_name") or window.get("process_name") or "")
        visible.append(f"{title} ({window_class})" if window_class else title)
        if len(visible) >= _PROMPT_WINDOW_LIMIT:
            break
    if visible:
        lines.append("- visible=" + "; ".join(visible))

    screenshot = state.get("screenshot") or {}
    if screenshot.get("recent") and screenshot.get("path"):
        lines.append(f"- recent_screenshot={screenshot['path']}")

    activity = state.get("activity") or []
    if activity:
        parts: list[str] = []
        for item in activity[:2]:
            label = item.get("target") or item.get("title") or item.get("window") or ""
            kind = item.get("kind") or "activity"
            parts.append(f"{kind}:{label}" if label else str(kind))
        lines.append("- activity=" + "; ".join(parts))

    lines.append(
        "- list=窗口清单/指针/活动窗口/窗口 bbox/元素树用 desktop_state"
        "（refresh=true 实时采集，比截图快且省 token；含 activity：用户最近打开的路径/网址、"
        "窗口聚焦与点击穿透记录）；只有需要文字或画面内容时才用 desktop_screenshot"
    )
    lines.append(
        "- next=操作桌面应用前先用 desktop_screenshot() 观察"
        "（默认自动返回 OCR 文字 + 画面理解 + 坐标空间）；"
        "定位元素用 desktop_find_element（UIA 返回精确屏幕坐标），结构不清用 desktop_inspect；"
        "坐标操作必须基于最新截图，避免盲点盲操作"
    )
    lines.append(
        "- keys=文本输入用 desktop_type（默认 WM_CHAR/剪贴板，避开输入法干扰）；"
        "空格/回车/Tab/方向键用 desktop_press；组合键用 desktop_hotkey；"
        "按住/连发用 desktop_key(action=down/up/press)"
    )
    lines.append(
        "- combo=鼠标键盘协同用 desktop_macro（Ctrl+点击多选、Shift+点击范围、Ctrl+拖拽复制、"
        "拖拽+按键、游戏连招）；拖拽用 desktop_mouse(action=drag)，相对移动用 move_relative；"
        "执行宏前传 focus_window=目标窗口标题（引擎会自动标题栏单击加固前台）；"
        "步骤默认带 120ms 步间延迟，紧随注入键的 WM_CHAR 不再丢失"
    )
    lines.append(
        "- files=打开文件/目录用 desktop_open（等同双击，打开后写 activity）；"
        "读取/修改/保存内容用 read_file / edit_file / write_file；"
        "定位路径用 list_directory / glob；保存后可用 read_file 或 desktop_screenshot 复核"
    )
    lines.append(
        "- web=要正文与结构（标题/链接/列表）用 browser_navigate + browser_get_content；"
        "要看真实渲染画面或已登录站点时用 desktop_open 打开浏览器 + desktop_screenshot"
        "（自动 OCR + 画面理解），再结合文本做深度解读"
    )
    lines.append(
        "- image=本地图片文件用 view_image 提取信息；"
        "屏幕上的图片/图表/扫描件用 desktop_screenshot，读其 OCR 文字与画面理解"
    )
    lines.append(
        "- verify=每次点击/输入后用新截图验证结果，确认界面已按预期变化"
    )

    if state.get("errors"):
        lines.append("- errors=" + "; ".join(str(item) for item in state["errors"][:2]))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 提示词块缓存（保证连续提示词构建逐字稳定）
# ---------------------------------------------------------------------------

# 渲染块缓存：提示词注入高频调用（每轮构建），而指针等实时项每次现采会导致
# 连续两次构建的提示词文本不一致，破坏 prompt-cache 稳定性测试与缓存命中。
# 因此按 TTL 缓存整块渲染结果，TTL 内连续构建得到逐字相同的块。
_prompt_block_cache: tuple[float, str] | None = None


def cached_prompt_context() -> str:
    """返回 TTL 内缓存的 ``[DESKTOP STATE]`` 块，过期或未缓存时重新渲染。"""
    global _prompt_block_cache
    ttl = _state_ttl()
    now = time.monotonic()
    if _prompt_block_cache is not None and ttl > 0 and now - _prompt_block_cache[0] <= ttl:
        return _prompt_block_cache[1]
    block = compact_prompt_context()
    if ttl > 0:
        _prompt_block_cache = (now, block)
    return block


def clear_prompt_context_cache() -> None:
    """清空提示词块缓存（供测试使用）。"""
    global _prompt_block_cache
    _prompt_block_cache = None


# ---------------------------------------------------------------------------
# CLI（便于手动调试与闭环验证）
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe the OpenKitsune Windows desktop state."
    )
    subparsers = parser.add_subparsers(dest="command")

    for name in ("state", "observe"):
        sub = subparsers.add_parser(name, help=f"{name} current desktop state")
        sub.add_argument("--json", action="store_true")
        sub.add_argument("--screenshot", action="store_true")
        sub.add_argument("--context-id", default="")

    shot = subparsers.add_parser("screenshot", help="capture a desktop screenshot")
    shot.add_argument("path", nargs="?")
    shot.add_argument("--json", action="store_true")
    shot.add_argument("--context-id", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "state"
    context_id = str(args.context_id or "")

    if command in ("state", "observe"):
        payload = collect_state(
            include_screenshot=bool(getattr(args, "screenshot", False)),
            context_id=context_id,
            screenshot_transport="path",
        )
        print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        return 0 if payload.get("ok") else 1

    if command == "screenshot":
        payload = capture_screenshot(
            path=args.path,
            context_id=context_id,
            transport="path",
        )
        if getattr(args, "json", False):
            print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        else:
            print(payload.get("path") or payload.get("error") or "")
        return 0 if payload.get("ok") else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
