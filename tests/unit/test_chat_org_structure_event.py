"""Regression coverage for chat-to-org-editor refresh events."""

from __future__ import annotations

from openkitsune.api.routes.chat import (
    _extract_org_structure_change,
    _strip_org_structure_marker,
)


def test_extract_org_structure_change_from_setup_organization_marker():
    event = {
        "type": "tool_call_end",
        "tool": "setup_organization",
        "id": "call_1",
        "result": (
            "✅ 组织「测试组织」创建成功！\n\n"
            '[OPENKITSUNE_ORG] {"action":"created","org_id":"org_123","org_name":"测试组织"}'
        ),
    }

    payload = _extract_org_structure_change(event)

    assert payload == {
        "action": "created",
        "org_id": "org_123",
        "org_name": "测试组织",
        "tool_use_id": "call_1",
    }


def test_strip_org_structure_marker_keeps_user_facing_result_clean():
    event = {
        "type": "tool_call_end",
        "tool": "setup_organization",
        "result": "完成\n\n[OPENKITSUNE_ORG] {\"action\":\"updated\",\"org_id\":\"org_123\"}",
    }

    stripped = _strip_org_structure_marker(event)

    assert stripped["result"] == "完成"
    assert event["result"].endswith('{"action":"updated","org_id":"org_123"}')
