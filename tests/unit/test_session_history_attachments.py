from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from openkitsune.api.routes.chat import _history_attachments_from_request
from openkitsune.api.routes.sessions import AppendBatchRequest, _history_entry
from openkitsune.api.schemas import AttachmentInfo, ChatAttachmentRecord


def test_request_attachments_are_serialized_as_chat_history_records():
    attachments = [
        AttachmentInfo(
            type="image",
            name="diagram.png",
            url="data:image/png;base64,abc",
            local_path="D:/tmp/diagram.png",
            upload_id="upload-1",
            size=123,
            mime_type="image/png",
        )
    ]

    assert _history_attachments_from_request(attachments) == [
        {
            "type": "image",
            "name": "diagram.png",
            "url": "data:image/png;base64,abc",
            "localPath": "D:/tmp/diagram.png",
            "uploadId": "upload-1",
            "previewUrl": "data:image/png;base64,abc",
            "size": 123,
            "mimeType": "image/png",
            "uploadStatus": "uploaded",
        }
    ]


def test_session_history_exposes_only_canonical_attachments_field():
    session = SimpleNamespace(last_active=datetime.fromisoformat("2026-01-01T00:00:00"))
    entry = _history_entry(
        session,
        "conv-1",
        0,
        {
            "role": "user",
            "content": "see image",
            "timestamp": "2026-01-01T00:00:00",
            "attachments": [
                {
                    "type": "image",
                    "name": "diagram.png",
                    "url": "data:image/png;base64,abc",
                    "previewUrl": "data:image/png;base64,abc",
                    "uploadStatus": "uploaded",
                }
            ],
            "input_attachments": [{"name": "legacy.png"}],
        },
    )

    assert entry["attachments"][0]["name"] == "diagram.png"
    assert "input_attachments" not in entry


def test_append_session_messages_accepts_canonical_chat_attachments():
    body = AppendBatchRequest.model_validate(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "",
                    "attachments": [
                        {
                            "type": "image",
                            "name": "shot.png",
                            "url": "data:image/png;base64,abc",
                            "previewUrl": "data:image/png;base64,abc",
                            "uploadStatus": "uploaded",
                        }
                    ],
                }
            ]
        }
    )

    assert body.messages[0].attachments
    assert body.messages[0].attachments[0].to_history_dict()["previewUrl"].startswith("data:")


def test_chat_attachment_record_rejects_snake_case_history_fields():
    with pytest.raises(ValidationError):
        ChatAttachmentRecord.model_validate(
            {
                "type": "image",
                "name": "shot.png",
                "local_path": "D:/tmp/shot.png",
            }
        )
