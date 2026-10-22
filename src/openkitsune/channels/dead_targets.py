"""IM 投递死目标登记表

某些平台错误是**永久性**的：机器人被踢出群、被用户拉黑、chat_id 已失效。
对这类目标继续重试只会浪费配额并刷错误日志，因此把 ``channel:chat_id``
登记为 dead target，短时间内直接短路投递，成功一次后自动清除。

与 Hermes ``gateway/dead_targets.py`` 的差异：这里额外带 TTL（默认 24h），
避免“目标已恢复但没人手动清理”导致永久静默。

失败分类保持保守：只登记明确不可恢复的错误，瞬时网络错误、限流、
平台暂时不可用一律不登记。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..utils.atomic_io import atomic_json_write

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/sessions/im_dead_targets.json")
DEFAULT_TTL_SECONDS = 24 * 60 * 60
MAX_ENTRIES = 500

# 只匹配明确的“永久性”错误；顺序不重要，命中任意一条即视为死目标。
_HARD_ERROR_MARKERS: tuple[str, ...] = (
    "forbidden",
    "403",
    "chat not found",
    "chat_not_found",
    "chat not exist",
    "chat_id_invalid",
    "peer_id_invalid",
    "bot was kicked",
    "bot_kicked",
    "kicked from the group",
    "bot is not a member",
    "not a member of the chat",
    "not in the chat",
    "bot was blocked",
    "blocked by the user",
    "user is deactivated",
    "account is deactivated",
    "群不存在",
    "会话不存在",
    "机器人已被移出",
    "机器人被踢",
    "用户已注销",
)


def classify_dead_error(error: BaseException | str | None) -> str | None:
    """返回死目标原因；若错误可能是瞬时/可恢复的，返回 ``None``。"""
    if error is None:
        return None
    text = str(error).strip()
    if not text:
        return None
    lowered = text.lower()
    for marker in _HARD_ERROR_MARKERS:
        if marker in lowered:
            return text[:200]
    return None


class DeadTargetRegistry:
    """Persistent ``channel:chat_id`` dead-target registry."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
    ) -> None:
        self._path = Path(path) if path else DEFAULT_PATH
        self._ttl_seconds = max(int(ttl_seconds), 1)
        self._max_entries = max(int(max_entries), 1)
        self._entries: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(channel: str, chat_id: str) -> str:
        return f"{channel}:{chat_id}"

    def is_dead(self, channel: str, chat_id: str) -> bool:
        key = self._key(channel, chat_id)
        entry = self._entries.get(key)
        if not entry:
            return False
        marked_at = float(entry.get("marked_at") or 0)
        if time.time() - marked_at > self._ttl_seconds:
            self._entries.pop(key, None)
            self._save()
            return False
        return True

    def mark_dead(self, channel: str, chat_id: str, reason: str) -> None:
        key = self._key(channel, chat_id)
        self._entries[key] = {"reason": reason, "marked_at": time.time()}
        if len(self._entries) > self._max_entries:
            oldest = sorted(self._entries.items(), key=lambda item: item[1].get("marked_at", 0))
            for stale_key, _ in oldest[: len(self._entries) - self._max_entries]:
                self._entries.pop(stale_key, None)
        self._save()
        logger.warning(
            "[DeadTarget] Marked %s as undeliverable: %s",
            key,
            reason[:160],
        )

    def clear(self, channel: str, chat_id: str) -> None:
        if self._entries.pop(self._key(channel, chat_id), None) is not None:
            self._save()
            logger.info("[DeadTarget] Cleared %s:%s after successful delivery", channel, chat_id)

    def snapshot(self) -> dict[str, dict]:
        return {key: dict(value) for key, value in self._entries.items()}

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            entries = data.get("targets", {})
            if isinstance(entries, dict):
                self._entries = {
                    str(key): dict(value)
                    for key, value in entries.items()
                    if isinstance(value, dict)
                }
        except Exception as exc:  # noqa: BLE001 -- 损坏时按空表处理，失败开放
            logger.warning("[DeadTarget] Failed to load %s: %s", self._path, exc)
            self._entries = {}

    def _save(self) -> None:
        try:
            atomic_json_write(self._path, {"targets": self._entries})
        except Exception as exc:  # noqa: BLE001 -- 持久化失败不应阻断投递
            logger.warning("[DeadTarget] Failed to persist %s: %s", self._path, exc)
