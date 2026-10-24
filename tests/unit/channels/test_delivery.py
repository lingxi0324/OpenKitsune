"""Unit tests for the normalized IM delivery result model."""

import pytest

from openkitsune.channels.base import ChannelDeliveryUnavailable
from openkitsune.channels.delivery import (
    DeliveryState,
    SendErrorKind,
    SendResult,
    classify_delivery_error,
    classify_send_result,
    is_delivery_ok,
    should_retry_send,
)


class TestClassifySendResult:
    def test_empty_message_id_is_not_delivered(self):
        result = classify_send_result("")
        assert result.state is DeliveryState.FAILED
        assert result.ok is False

    def test_none_is_not_delivered(self):
        assert classify_send_result(None).state is DeliveryState.FAILED

    def test_unknown_kind_is_not_delivered(self):
        result = classify_send_result("circuit_open_1712345678")
        assert result.state is DeliveryState.SKIPPED
        assert result.ok is False

    def test_skipped_sentinel_is_not_delivered(self):
        result = classify_send_result("skipped:req-1")
        assert result.state is DeliveryState.SKIPPED
        assert result.ok is False

    @pytest.mark.parametrize("raw", ["queued:req-1", "stream:stream-1"])
    def test_queued_and_stream_are_accepted(self, raw):
        result = classify_send_result(raw)
        assert result.state is DeliveryState.ACCEPTED
        assert result.ok is True
        assert result.confirmed is False

    @pytest.mark.parametrize("raw", ["msg-1", "webhook:image_sent", "12345"])
    def test_message_id_is_delivered(self, raw):
        result = classify_send_result(raw)
        assert result.state is DeliveryState.DELIVERED
        assert result.confirmed is True

    def test_send_result_passthrough(self):
        original = SendResult(DeliveryState.ACCEPTED, message_id="x")
        assert classify_send_result(original) is original

    def test_bool_and_dict_results(self):
        assert classify_send_result(True).state is DeliveryState.DELIVERED
        assert classify_send_result(False).state is DeliveryState.FAILED
        assert classify_send_result({"ok": False}).state is DeliveryState.FAILED
        assert classify_send_result({"message_id": "m1"}).state is DeliveryState.DELIVERED

    def test_is_delivery_ok_matches_ok_property(self):
        assert is_delivery_ok("msg-1") is True
        assert is_delivery_ok("queued:1") is True
        assert is_delivery_ok("") is False
        assert is_delivery_ok("circuit_open_1") is False


class TestClassifyDeliveryError:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Forbidden: bot was kicked", SendErrorKind.FORBIDDEN),
            ("chat not found", SendErrorKind.NOT_FOUND),
            ("message is too long", SendErrorKind.TOO_LONG),
            ("can't parse entities", SendErrorKind.BAD_FORMAT),
            ("429 Too Many Requests", SendErrorKind.RATE_LIMITED),
            ("connection reset by peer", SendErrorKind.TRANSIENT),
            ("something odd happened", SendErrorKind.UNKNOWN),
        ],
    )
    def test_text_markers(self, text, kind):
        assert classify_delivery_error(text) is kind

    def test_timeout_is_transient(self):
        assert classify_delivery_error(TimeoutError()) is SendErrorKind.TRANSIENT

    def test_connection_error_is_transient(self):
        assert classify_delivery_error(ConnectionResetError()) is SendErrorKind.TRANSIENT


class TestShouldRetrySend:
    def test_timeout_is_not_retried_to_avoid_duplicates(self):
        assert should_retry_send(TimeoutError()) is False

    def test_transient_error_is_retried(self):
        assert should_retry_send(ConnectionResetError()) is True

    def test_delivery_unavailable_uses_its_own_flag(self):
        retryable = ChannelDeliveryUnavailable("x", reason="session paused", retryable=True)
        permanent = ChannelDeliveryUnavailable("x", reason="context rejected", retryable=False)
        assert should_retry_send(retryable) is True
        assert should_retry_send(permanent) is False
