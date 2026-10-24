"""Gateway delivery-path tests for the normalized result model and video routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openkitsune.channels.gateway import MessageGateway
from openkitsune.channels.media_parser import parse_media_from_text
from openkitsune.channels.types import MessageContent, UnifiedMessage


def _message(channel: str = "wechat:test", chat_id: str = "chat-1") -> UnifiedMessage:
    return UnifiedMessage.create(
        channel=channel,
        channel_message_id="source-message-id",
        user_id="user-1",
        channel_user_id="user-1",
        chat_id=chat_id,
        content=MessageContent.text_only(""),
    )


class TestDeliveredSentinel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", False),
            ("circuit_open_1712345678", False),
            ("skipped:req-1", False),
            ("queued:req-1", True),
            ("stream:stream-1", True),
            ("msg-1", True),
        ],
    )
    def test_sentinels(self, raw, expected):
        assert MessageGateway._is_im_send_delivered(raw) is expected


class _VideoAdapter:
    def __init__(self) -> None:
        self.videos: list[str] = []
        self.files: list[str] = []
        self.texts: list[str] = []

    def has_capability(self, name: str) -> bool:
        return name in {"send_file", "send_video"}

    async def send_video(self, chat_id, video_path, caption=None, reply_to=None, **_kwargs):
        self.videos.append(video_path)
        return "video-message-id"

    async def send_file(self, chat_id, file_path, caption=None, **_kwargs):
        self.files.append(file_path)
        return "file-message-id"

    async def send_text(self, chat_id, text, **_kwargs):
        self.texts.append(text)
        return "text-message-id"


class _VideoDeclaredButUnimplementedAdapter(_VideoAdapter):
    async def send_video(self, chat_id, video_path, caption=None, reply_to=None, **_kwargs):
        raise NotImplementedError("video upload unavailable")


class TestExtractedVideoRouting:
    @pytest.mark.asyncio
    async def test_video_uses_dedicated_capability(self, tmp_path):
        video_path = tmp_path / "preview.mp4"
        video_path.write_bytes(b"video")

        gateway = MessageGateway(session_manager=MagicMock())
        adapter = _VideoAdapter()
        media_result = parse_media_from_text(f"MEDIA: {video_path}")

        await gateway._send_extracted_media(adapter, _message(), media_result, {})

        assert adapter.videos == [str(video_path)]
        assert adapter.files == []
        assert adapter.texts == []

    @pytest.mark.asyncio
    async def test_video_falls_back_to_file_when_unimplemented(self, tmp_path):
        video_path = tmp_path / "preview.mp4"
        video_path.write_bytes(b"video")

        gateway = MessageGateway(session_manager=MagicMock())
        adapter = _VideoDeclaredButUnimplementedAdapter()
        media_result = parse_media_from_text(f"MEDIA: {video_path}")

        await gateway._send_extracted_media(adapter, _message(), media_result, {})

        assert adapter.videos == []
        assert adapter.files == [str(video_path)]
        assert adapter.texts == []


class TestProactiveSendRetry:
    @pytest.mark.asyncio
    async def test_transient_failure_is_retried(self):
        gateway = MessageGateway(session_manager=MagicMock())
        adapter = MagicMock()
        adapter.send_text = AsyncMock(side_effect=[ConnectionResetError(), "msg-1"])
        gateway._adapters["wechat:test"] = adapter

        result = await gateway.send("wechat:test", "chat-1", "hello")

        assert result == "msg-1"
        assert adapter.send_text.await_count == 2

    @pytest.mark.asyncio
    async def test_circuit_open_sentinel_is_reported_as_failure(self):
        gateway = MessageGateway(session_manager=MagicMock())
        adapter = MagicMock()
        adapter.send_text = AsyncMock(return_value="circuit_open_1712345678")
        gateway._adapters["dingtalk:test"] = adapter

        result = await gateway.send("dingtalk:test", "chat-1", "hello")

        assert result is None
        assert adapter.send_text.await_count == 1

    @pytest.mark.asyncio
    async def test_timeout_is_not_retried(self):
        gateway = MessageGateway(session_manager=MagicMock())
        adapter = MagicMock()
        adapter.send_text = AsyncMock(side_effect=TimeoutError())
        gateway._adapters["wechat:test"] = adapter

        result = await gateway.send("wechat:test", "chat-1", "hello")

        assert result is None
        assert adapter.send_text.await_count == 1
