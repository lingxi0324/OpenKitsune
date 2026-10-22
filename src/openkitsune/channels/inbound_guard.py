"""入站消息幂等与陈旧消息防护

各适配器都有一份自己的去重表，但实现分散、TTL 不一致，且网关层没有
统一兜底。平台重连、webhook 重试、多实例切换都可能让同一条消息二次
进入 ``MessageGateway._on_message``，从而重复调用 Agent、重复回复。

本模块提供两个与平台无关的小工具：

- :class:`InboundGuard`：按 ``channel:chat_id:message_id`` 做 TTL 去重
- :meth:`InboundGuard.is_stale`：按消息时间戳丢弃积压过久的历史消息

都是进程内内存态，不做持久化——重启后平台自身的重放窗口通常已经过去，
持久化反而会让「用户重启后重新发一遍同 ID 消息」被误杀。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import datetime

DEFAULT_TTL_SECONDS = 300
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_STALE_THRESHOLD_SECONDS = 120


class InboundGuard:
    """Process-local inbound deduplication + staleness guard."""

    def __init__(
        self,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    ) -> None:
        self._ttl_seconds = max(int(ttl_seconds), 1)
        self._max_entries = max(int(max_entries), 1)
        self._stale_threshold_seconds = max(int(stale_threshold_seconds), 0)
        self._seen: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, channel: str, chat_id: str, message_id: str) -> bool:
        """Return True if this platform message was already accepted.

        Empty ``message_id`` is never treated as duplicate (some adapters do
        not expose a stable id); callers rely on adapter-level dedup there.
        """
        message_id = (message_id or "").strip()
        if not message_id:
            return False

        key = f"{channel}:{chat_id}:{message_id}"
        now = time.monotonic()
        self._prune(now)

        seen_at = self._seen.get(key)
        if seen_at is not None and now - seen_at <= self._ttl_seconds:
            self._seen.move_to_end(key)
            return True

        self._seen[key] = now
        self._seen.move_to_end(key)
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return False

    def is_stale(self, timestamp: datetime | None, *, now: datetime | None = None) -> bool:
        """Return True if ``timestamp`` is older than the stale threshold."""
        if timestamp is None or self._stale_threshold_seconds <= 0:
            return False
        try:
            reference = now or datetime.now(timestamp.tzinfo)
            age = (reference - timestamp).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return False
        return age > self._stale_threshold_seconds

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, seen_at in self._seen.items()
            if now - seen_at > self._ttl_seconds
        ]
        for key in expired:
            self._seen.pop(key, None)
