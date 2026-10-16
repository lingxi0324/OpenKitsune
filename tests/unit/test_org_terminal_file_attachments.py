"""Organization terminal results expose registered deliverable files uniformly."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from openkitsune.orgs._runtime_artifact_flow import ArtifactRecord, artifact_ledger
from openkitsune.orgs.command_service import (
    OrgCommandService,
    _project_manifest_file_attachments,
)
from openkitsune.runtime.supervisor import FinalOutcome


def test_manifest_ids_are_hydrated_from_artifact_ledger(tmp_path: Path) -> None:
    image_path = tmp_path / "key-frame.png"
    video_path = tmp_path / "preview.mp4"
    image_path.write_bytes(b"image")
    video_path.write_bytes(b"video")
    manifest = {
        "state": "complete",
        "final": True,
        "artifacts": [
            {
                "kind": "image",
                "status": "ready",
                "name": "key frame",
                "asset_ids": ["image-asset"],
                "task_ids": ["image-task"],
                "paths": [],
            },
            {
                "kind": "video",
                "status": "ready",
                "name": "preview",
                "asset_ids": ["video-asset"],
                "task_ids": ["video-task"],
                "paths": [],
            },
        ],
    }
    records = (
        ArtifactRecord(
            org_id="org-1",
            command_id="cmd-1",
            source_node_id="image-worker",
            tool_name="image_create",
            asset_ids=("image-asset",),
            task_ids=("image-task",),
            asset_kinds=("image",),
            registered_paths=(str(image_path),),
        ),
        ArtifactRecord(
            org_id="org-1",
            command_id="cmd-1",
            source_node_id="video-worker",
            tool_name="video_create",
            asset_ids=("video-asset",),
            task_ids=("video-task",),
            asset_kinds=("video",),
            registered_paths=(str(video_path),),
            registered_video_paths=(str(video_path),),
            media_validation_passed=True,
        ),
    )

    projected, attachments = _project_manifest_file_attachments(manifest, records)

    assert projected is not None
    assert projected["artifacts"][0]["paths"] == [str(image_path)]
    assert projected["artifacts"][1]["paths"] == [str(video_path)]
    assert [(item["kind"], item["file_path"]) for item in attachments] == [
        ("image", str(image_path)),
        ("video", str(video_path)),
    ]
    assert attachments[1]["file_size"] == len(b"video")


def test_manifest_projection_does_not_leak_unclaimed_intermediate_files(tmp_path: Path) -> None:
    final_path = tmp_path / "final.mp4"
    intermediate_path = tmp_path / "intermediate.mp4"
    final_path.write_bytes(b"final")
    intermediate_path.write_bytes(b"intermediate")
    manifest = {
        "artifacts": [
            {
                "kind": "video",
                "asset_ids": ["final-asset"],
                "task_ids": [],
                "paths": [],
            }
        ]
    }
    records = (
        ArtifactRecord(
            org_id="org-1",
            command_id="cmd-1",
            source_node_id="video-worker",
            tool_name="video_create",
            asset_ids=("final-asset",),
            asset_kinds=("video",),
            registered_video_paths=(str(final_path),),
        ),
        ArtifactRecord(
            org_id="org-1",
            command_id="cmd-1",
            source_node_id="video-worker",
            tool_name="video_create",
            asset_ids=("intermediate-asset",),
            asset_kinds=("video",),
            registered_video_paths=(str(intermediate_path),),
        ),
    )

    projected, attachments = _project_manifest_file_attachments(manifest, records)

    assert projected is not None
    assert projected["artifacts"][0]["paths"] == [str(final_path)]
    assert [item["file_path"] for item in attachments] == [str(final_path)]


def test_supervisor_terminal_result_exposes_hydrated_file_attachments(tmp_path: Path) -> None:
    video_path = tmp_path / "preview.mp4"
    video_path.write_bytes(b"video")
    record = ArtifactRecord(
        org_id="org-1",
        command_id="cmd-1",
        source_node_id="video-worker",
        tool_name="video_create",
        asset_ids=("video-asset",),
        task_ids=("video-task",),
        asset_kinds=("video",),
        registered_paths=(str(video_path),),
        registered_video_paths=(str(video_path),),
        media_validation_passed=True,
    )
    artifact_ledger.clear()
    artifact_ledger.append(record)
    service = object.__new__(OrgCommandService)
    service._commands = {
        "cmd-1": {
            "org_id": "org-1",
            "root_node_id": "producer",
            "source": "im",
            "origin_surface": "feishu",
        }
    }
    service._command_outcomes = {}
    service._runtime = MagicMock()
    service._runtime.finalize_command_project = None
    service._update_command_state = MagicMock()
    service._bridge_persist_result = MagicMock()
    outcome = SimpleNamespace(
        outcome=FinalOutcome.DONE,
        final_message="组织任务完成",
        deliverable="组织任务完成",
        n_turns=2,
        n_replans=0,
        final_checkpoint_id="cp-1",
        delivery_manifest={
            "state": "complete",
            "final": True,
            "artifacts": [
                {
                    "kind": "video",
                    "status": "ready",
                    "name": "preview",
                    "asset_ids": ["video-asset"],
                    "task_ids": ["video-task"],
                    "paths": [],
                }
            ],
        },
    )

    try:
        service._reflect_supervisor_outcome("cmd-1", MagicMock(), outcome)
    finally:
        artifact_ledger.clear()

    result = service._update_command_state.call_args.kwargs["result"]
    assert result["delivery_manifest"]["artifacts"][0]["paths"] == [str(video_path)]
    assert result["file_attachments"] == [
        {
            "filename": "preview.mp4",
            "file_path": str(video_path),
            "file_size": len(b"video"),
            "kind": "video",
            "name": "preview",
        }
    ]
