from __future__ import annotations

import asyncio
import hashlib
import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from openkitsune import optional_features
from openkitsune.api.message_parts import build_message_parts


class _DownloadResponse(io.BytesIO):
    def __init__(self, value: bytes, *, status: int, headers: dict[str, str]) -> None:
        super().__init__(value)
        self.status = status
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_resumable_download_appends_to_persistent_partial(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "asset.zip"
    partial = tmp_path / "asset.zip.part"
    partial.write_bytes(b"first-")
    seen_headers: dict[str, str] = {}

    def urlopen(request, timeout):
        seen_headers.update(dict(request.headers))
        return _DownloadResponse(
            b"second",
            status=206,
            headers={"Content-Range": "bytes 6-11/12", "Content-Length": "6"},
        )

    monkeypatch.setattr(optional_features.urllib.request, "urlopen", urlopen)

    optional_features._download_resumable(
        ["https://assets.example/asset.zip"], destination, expected_size=12
    )

    assert seen_headers["Range"] == "bytes=6-"
    assert destination.read_bytes() == b"first-second"
    assert not partial.exists()


def test_install_request_survives_in_memory_reset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path))
    optional_features._REQUEST_EVENTS.clear()

    created = optional_features.create_install_request("conversation-1")
    optional_features._REQUEST_EVENTS.clear()
    restored = optional_features.get_install_request(created["request_id"])

    assert restored is not None
    assert restored["conversation_id"] == "conversation-1"
    assert restored["status"] == "pending"


def test_interrupted_install_becomes_retryable_after_restart(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path))
    optional_features._REQUEST_EVENTS.clear()
    optional_features._INSTALL_LOCKS.clear()
    created = optional_features.create_install_request("conversation-restart")
    optional_features.update_install_request(created["request_id"], status="installing")

    restored = optional_features.get_install_request(created["request_id"])

    assert restored is not None
    assert restored["status"] == "failed"
    assert "重试" in restored["message"]


@pytest.mark.asyncio
async def test_install_request_completion_wakes_waiter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path))
    optional_features._REQUEST_EVENTS.clear()
    created = optional_features.create_install_request("conversation-2")

    waiter = asyncio.create_task(
        optional_features.wait_for_install_request(created["request_id"], timeout=2)
    )
    await asyncio.sleep(0)
    optional_features.update_install_request(created["request_id"], status="installed")

    assert (await waiter)["status"] == "installed"


def test_playwright_runtime_extracts_only_driver(tmp_path: Path, monkeypatch) -> None:
    wheel = tmp_path / "playwright.whl"
    node_name = "node.exe" if os.name == "nt" else "node"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"playwright/driver/{node_name}", b"node")
        archive.writestr("playwright/driver/package/cli.js", b"cli")
        archive.writestr("playwright/async_api/__init__.py", b"ignored")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    managed = tmp_path / "managed-driver"

    monkeypatch.setattr(optional_features, "configure_playwright_driver", lambda: None)
    monkeypatch.setattr(optional_features, "_managed_driver_dir", lambda: managed)
    monkeypatch.setattr(
        optional_features,
        "_select_driver_artifact",
        lambda: {
            "mirror_url": "https://mirror.example/playwright.whl",
            "upstream_url": "https://upstream.example/playwright.whl",
            "sha256": digest,
        },
    )

    def download(sources, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copyfile(wheel, destination))

    monkeypatch.setattr(optional_features, "_download_resumable", download)

    optional_features.install_playwright_runtime()

    assert (managed / node_name).read_bytes() == b"node"
    assert (managed / "package" / "cli.js").read_bytes() == b"cli"
    assert not (managed / "async_api").exists()


def test_playwright_runtime_rejects_unsafe_driver_path(tmp_path: Path, monkeypatch) -> None:
    wheel = tmp_path / "playwright.whl"
    node_name = "node.exe" if os.name == "nt" else "node"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"playwright/driver/{node_name}", b"node")
        archive.writestr("playwright/driver/package/cli.js", b"cli")
        archive.writestr("playwright/driver/../../outside.txt", b"unsafe")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

    monkeypatch.setattr(optional_features, "configure_playwright_driver", lambda: None)
    monkeypatch.setattr(optional_features, "_managed_driver_dir", lambda: tmp_path / "managed")
    monkeypatch.setattr(
        optional_features,
        "_select_driver_artifact",
        lambda: {"mirror_url": "https://mirror.example/playwright.whl", "sha256": digest},
    )

    def download(sources, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copyfile(wheel, destination))

    monkeypatch.setattr(optional_features, "_download_resumable", download)

    with pytest.raises(RuntimeError, match="unsafe driver path"):
        optional_features.install_playwright_runtime()

    assert not (tmp_path / "outside.txt").exists()


def test_optional_feature_message_part_is_persistable() -> None:
    request = {
        "request_id": "req-1",
        "feature_id": "browser.automation",
        "status": "pending",
    }

    parts = build_message_parts(
        {
            "role": "assistant",
            "content": "fallback text",
            "optional_feature_install": request,
        }
    )

    assert parts == [
        {
            "kind": "optional_feature_install",
            "id": "optional_feature_install:req-1",
            "request": request,
        }
    ]
