"""Desktop (Windows) 工具定义 —— 平台无关注册面。

桌面工具的真实 schema 在 ``openkitsune.tools.desktop.tools.DESKTOP_TOOLS``
（该模块带 Windows 平台守卫，非 Windows 上 import 会抛 ImportError）。
这里条件导入同一份列表对象，避免维护两份 schema：
- Windows：DESKTOP_TOOLS = 完整的 14 个桌面工具定义（与运行时一致）；
- 其他平台：空列表，不破坏 BASE_TOOLS 的跨平台导入。

工具执行仍由 ``core/_agent_runtime`` 按 ``_ensure_desktop()`` 结果决定是否
注册 handler（与 POWERSHELL_TOOLS 同一模式：定义无条件进入 BASE_TOOLS，
处理器仅在实际可用平台注册）。
"""

from __future__ import annotations

try:
    from ..desktop.tools import DESKTOP_TOOLS  # Windows-only（自带平台守卫）
except Exception:  # pragma: no cover - 非 Windows 平台
    DESKTOP_TOOLS = []

__all__ = ["DESKTOP_TOOLS"]
