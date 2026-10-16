import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.core.policy_v2 import PolicyContext, reset_current_context, set_current_context
from openkitsune.tools.handlers.im_channel import IMChannelHandler


class _FakeAgent:
    def __init__(self, workspace_dir):
        self.workspace_dir = str(workspace_dir)


class _MetadataSession:
    def __init__(self):
        self.metadata = {}

    def get_metadata(self, key, default=None):
        return self.metadata.get(key, default)

    def set_metadata(self, key, value):
        self.metadata[key] = value


def test_normalize_delivery_params_accepts_legacy_recipients():
    params = {
        "recipients": [
            {
                "channel": "telegram",
                "file_path": "data/out/report.md",
                "filename": "report.md",
            }
        ]
    }

    normalized = IMChannelHandler._normalize_delivery_params(params)

    assert normalized["target_channel"] == "telegram"
    assert normalized["artifacts"] == [
        {
            "channel": "telegram",
            "file_path": "data/out/report.md",
            "filename": "report.md",
            "path": "data/out/report.md",
            "type": "file",
            "name": "report.md",
        }
    ]


def test_normalize_delivery_params_accepts_stringified_recipient_object():
    params = {
        "artifacts": json.dumps(
            {
                "recipients": [
                    {
                        "type": "image",
                        "local_path": "data/out/chart.png",
                        "caption": "chart",
                    }
                ]
            }
        )
    }

    normalized = IMChannelHandler._normalize_delivery_params(params)

    assert normalized["artifacts"] == [
        {
            "type": "image",
            "local_path": "data/out/chart.png",
            "caption": "chart",
            "path": "data/out/chart.png",
        }
    ]


def test_normalize_delivery_params_accepts_string_path_list():
    normalized = IMChannelHandler._normalize_delivery_params(
        {"artifacts": json.dumps(["data/out/a.md"])}
    )

    assert normalized["artifacts"] == [{"type": "file", "path": "data/out/a.md"}]


@pytest.mark.asyncio
async def test_deliver_artifacts_desktop_handles_legacy_recipients(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    artifact = tmp_path / "report.md"
    artifact.write_text("hello", encoding="utf-8")
    handler = IMChannelHandler(_FakeAgent(tmp_path))

    result = await handler.handle(
        "deliver_artifacts",
        {"recipients": [{"file_path": str(artifact), "caption": "done"}]},
    )
    payload = json.loads(result)

    assert payload["ok"] is True
    assert payload["receipts"][0]["status"] == "delivered"
    assert payload["receipts"][0]["path"] == str(artifact.resolve())


@pytest.mark.asyncio
async def test_deliver_artifacts_desktop_prefers_session_working_directory(tmp_path):
    agent_root = tmp_path / "agent"
    session_root = tmp_path / "session"
    agent_root.mkdir()
    session_root.mkdir()
    artifact = session_root / "report.md"
    artifact.write_text("hello", encoding="utf-8")
    handler = IMChannelHandler(_FakeAgent(agent_root))
    ctx = PolicyContext(
        session_id="artifact-session",
        working_directory=session_root,
        workspace_roots=(session_root,),
    )
    token = set_current_context(ctx)
    try:
        result = await handler.handle(
            "deliver_artifacts",
            {"artifacts": [{"path": "report.md", "type": "file"}]},
        )
    finally:
        reset_current_context(token)

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["receipts"][0]["path"] == str(artifact.resolve())


@pytest.mark.asyncio
async def test_deliver_artifacts_desktop_reports_missing_artifacts(tmp_path):
    handler = IMChannelHandler(_FakeAgent(tmp_path))

    result = await handler.handle("deliver_artifacts", {"artifacts": []})
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["error_code"] == "missing_artifacts"
    assert payload["receipts"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel",
    [
        "wechat:customer",
        "telegram:customer",
        "feishu:customer",
        "dingtalk:customer",
        "wework_ws:customer",
        "qqbot:customer",
        "onebot:customer",
    ],
)
async def test_successful_im_image_delivery_queues_desktop_mirror(tmp_path, channel):
    image = tmp_path / "generated.png"
    image.write_bytes(b"image-data")
    session = _MetadataSession()
    agent = _FakeAgent(tmp_path)
    agent._current_session = session
    handler = IMChannelHandler(agent)
    handler._get_adapter_and_chat_id = lambda: (
        SimpleNamespace(),
        "chat-1",
        channel,
        "reply-1",
        "user-1",
    )
    handler._send_image = AsyncMock(return_value="✅ 已发送图片 (message_id=media-1)")

    result = await handler._deliver_artifacts(
        {
            "artifacts": [
                {
                    "type": "image",
                    "path": str(image),
                    "caption": "海景图",
                }
            ]
        }
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["receipts"][0]["status"] == "delivered"
    handler._send_image.assert_awaited_once()
    assert session.get_metadata("_pending_desktop_artifacts") == [
        {
            "artifact_type": "image",
            "path": str(image),
            "name": "generated.png",
            "caption": "海景图",
            "size": len(b"image-data"),
            "sha256": payload["receipts"][0]["sha256"],
        }
    ]
