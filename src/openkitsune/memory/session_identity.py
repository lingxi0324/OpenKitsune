"""Memory identity comes from session metadata, never substrings of its ID."""

from __future__ import annotations

import re
from typing import Any

DESKTOP_USER_ID = "desktop_user"


def memory_session_id(session: Any | None, fallback: str = "") -> str:
    key = getattr(session, "session_key", None) or fallback
    return re.sub(r'[/\\+=%?*<>|"\x00-\x1f]', "_", key.replace(":", "__"))


def memory_session_user(session: Any | None) -> str:
    user_id = str(getattr(session, "user_id", None) or "").strip()
    if getattr(session, "channel", None) == "desktop" and user_id in {"", "default", "anonymous"}:
        return DESKTOP_USER_ID
    return user_id or "anonymous"
