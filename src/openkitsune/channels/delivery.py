"""统一 IM 投递结果与失败分类。

参考 Hermes ``gateway/platforms/base.py`` 的 ``SendResult`` / ``SEND_ERROR_KINDS``
与 ``classify_send_error()`` 设计，把各适配器五花八门的返回值收敛成一个
明确的状态模型：

- 适配器返回值 -> :func:`classify_send_result`
- 适配器异常   -> :func:`classify_delivery_error`
- 是否重试     -> :func:`should_retry_send`

这样网关、调度器和插件不需要再靠“非空字符串就是成功”猜测投递结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .base import ChannelDeliveryUnavailable


class DeliveryState(StrEnum):
    """一次发送的最终状态。"""

    DELIVERED = "delivered"  # 平台已确认（返回了真实 message id）
    ACCEPTED = "accepted"  # 已交给平台队列/流更新，尚未确认
    SKIPPED = "skipped"  # 适配器主动跳过（熔断、无活跃流、媒体被丢弃）
    FAILED = "failed"
    UNKNOWN = "unknown"


class SendErrorKind(StrEnum):
    """平台错误语义分类，用于决定重试/降级/死目标。"""

    TOO_LONG = "too_long"
    BAD_FORMAT = "bad_format"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SendResult:
    """结构化发送结果。适配器可直接返回它，也可继续返回字符串。"""

    state: DeliveryState
    message_id: str = ""
    raw: Any = None
    error_kind: SendErrorKind = SendErrorKind.UNKNOWN
    retryable: bool = False
    retry_after: float | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.state in (DeliveryState.DELIVERED, DeliveryState.ACCEPTED)

    @property
    def confirmed(self) -> bool:
        return self.state is DeliveryState.DELIVERED


_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "forbidden",
    "403",
    "bot was kicked",
    "bot_kicked",
    "kicked from the group",
    "bot is not a member",
    "not a member of the chat",
    "bot was blocked",
    "blocked by the user",
    "user is deactivated",
    "account is deactivated",
    "机器人已被移出",
    "机器人被踢",
    "被拉黑",
    "用户已注销",
)

_NOT_FOUND_MARKERS: tuple[str, ...] = (
    "chat not found",
    "chat_not_found",
    "chat not exist",
    "chat_id_invalid",
    "peer_id_invalid",
    "user not found",
    "群不存在",
    "会话不存在",
    "用户不存在",
)

_TOO_LONG_MARKERS: tuple[str, ...] = (
    "message is too long",
    "message too long",
    "too long",
    "exceeds the limit",
    "payload too large",
    "长度超限",
    "消息过长",
    "超过限制",
)

_BAD_FORMAT_MARKERS: tuple[str, ...] = (
    "can't parse entities",
    "cant parse entities",
    "parse entities",
    "invalid markdown",
    "bad request",
    "invalid parameter",
    "格式错误",
)

_RATE_LIMITED_MARKERS: tuple[str, ...] = (
    "429",
    "rate limit",
    "ratelimit",
    "too many requests",
    "flood control",
    "retry after",
    "限流",
    "请求过于频繁",
)

_TRANSIENT_MARKERS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection error",
    "network error",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "502",
    "503",
    "504",
    "网络错误",
    "超时",
)


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def classify_delivery_error(error: BaseException | str | None) -> SendErrorKind:
    """把异常/错误文本映射为 :class:`SendErrorKind`。"""
    if error is None:
        return SendErrorKind.UNKNOWN
    if isinstance(error, BaseException):
        if isinstance(error, (TimeoutError, ConnectionError)):
            return SendErrorKind.TRANSIENT
        try:
            import httpx

            if isinstance(error, httpx.HTTPStatusError):
                status = error.response.status_code
                if status == 429:
                    return SendErrorKind.RATE_LIMITED
                if status in (401, 403):
                    return SendErrorKind.FORBIDDEN
                if status == 404:
                    return SendErrorKind.NOT_FOUND
                if status == 413:
                    return SendErrorKind.TOO_LONG
                if status == 400:
                    return SendErrorKind.BAD_FORMAT
                if status >= 500:
                    return SendErrorKind.TRANSIENT
            if isinstance(error, httpx.TransportError):
                return SendErrorKind.TRANSIENT
        except ImportError:
            pass
    text = (getattr(error, "reason", "") or str(error)).strip().lower()
    if not text:
        return SendErrorKind.UNKNOWN
    if _matches(text, _FORBIDDEN_MARKERS):
        return SendErrorKind.FORBIDDEN
    if _matches(text, _NOT_FOUND_MARKERS):
        return SendErrorKind.NOT_FOUND
    if _matches(text, _TOO_LONG_MARKERS):
        return SendErrorKind.TOO_LONG
    if _matches(text, _BAD_FORMAT_MARKERS):
        return SendErrorKind.BAD_FORMAT
    if _matches(text, _RATE_LIMITED_MARKERS):
        return SendErrorKind.RATE_LIMITED
    if _matches(text, _TRANSIENT_MARKERS):
        return SendErrorKind.TRANSIENT
    return SendErrorKind.UNKNOWN


def classify_send_result(result: Any, channel: str = "") -> SendResult:
    """把适配器返回值归一化为 :class:`SendResult`。

    兼容现有适配器的字符串哨兵：

    - ``""``                    -> 未送达
    - ``circuit_open_<ts>``      -> 熔断跳过，未送达
    - ``skipped:<id>``           -> 适配器跳过，未送达
    - ``queued:<id>``            -> 已入队，accepted
    - ``stream:<id>``            -> 已写入流式会话，accepted
    - ``webhook:<name>``         -> webhook 已确认，delivered
    - 其他非空字符串              -> 视为 message id，delivered
    """

    if isinstance(result, SendResult):
        return result
    if result is None:
        return SendResult(
            DeliveryState.FAILED,
            raw=result,
            reason=f"{channel + ': ' if channel else ''}adapter returned None",
        )
    if result is True:
        return SendResult(DeliveryState.DELIVERED, raw=result)
    if result is False:
        return SendResult(DeliveryState.FAILED, raw=result, reason="adapter returned False")
    if isinstance(result, str):
        value = result.strip()
        if not value:
            return SendResult(DeliveryState.FAILED, raw=result, reason="empty message id")
        lowered = value.lower()
        if lowered.startswith("circuit_open"):
            return SendResult(
                DeliveryState.SKIPPED,
                raw=result,
                reason="adapter circuit breaker open",
            )
        if lowered.startswith("skipped"):
            return SendResult(DeliveryState.SKIPPED, raw=result, reason="adapter skipped send")
        if lowered.startswith("queued"):
            return SendResult(DeliveryState.ACCEPTED, message_id=value, raw=result)
        if lowered.startswith("stream"):
            return SendResult(DeliveryState.ACCEPTED, message_id=value, raw=result)
        if lowered.startswith("webhook"):
            return SendResult(DeliveryState.DELIVERED, message_id=value, raw=result)
        return SendResult(DeliveryState.DELIVERED, message_id=value, raw=result)
    if isinstance(result, dict):
        message_id = str(result.get("message_id") or result.get("id") or "")
        if result.get("ok") is False:
            return SendResult(DeliveryState.FAILED, raw=result, reason="adapter reported ok=False")
        state = DeliveryState.DELIVERED if message_id else DeliveryState.ACCEPTED
        return SendResult(state, message_id=message_id, raw=result)
    return SendResult(DeliveryState.DELIVERED, raw=result)


def is_delivery_ok(result: Any) -> bool:
    """是否可视为“这条消息已经交给平台”。"""
    return classify_send_result(result).ok


def should_retry_send(error: BaseException) -> bool:
    """发送路径的重试判定。

    与 :func:`openkitsune.channels.retry.default_should_retry` 的差异：

    - 超时不重试：请求可能已经到达平台，重试会造成重复消息；
    - ``ChannelDeliveryUnavailable`` 只有显式 ``retryable=True`` 才重试；
    - 仅网络抖动、5xx、429 视为可重试。
    """

    if isinstance(error, ChannelDeliveryUnavailable):
        return bool(error.retryable)
    if isinstance(error, TimeoutError):
        return False
    return classify_delivery_error(error) in (
        SendErrorKind.TRANSIENT,
        SendErrorKind.RATE_LIMITED,
    )
