"""Durable optional-feature requests and browser runtime bootstrap."""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import urllib.request
import uuid
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from openkitsune.optional_assets import load_optional_asset_feature
from openkitsune.utils.atomic_io import atomic_json_write, read_json_safe

OPTIONAL_FEATURE_MARKER = "__OPENKITSUNE_OPTIONAL_FEATURE_INSTALL__"
PLAYWRIGHT_RUNTIME_FEATURE = "browser.playwright-runtime"
BROWSER_AUTOMATION_FEATURE = "browser.automation"
_REQUEST_LOCK = threading.RLock()
_REQUEST_EVENTS: dict[str, asyncio.Event] = {}
_INSTALL_LOCKS: dict[str, asyncio.Lock] = {}
_PLAYWRIGHT_HEADER = re.compile(r"^(.+?) \(playwright (.+?) v([^\)]+)\)$")
_PLAYWRIGHT_URL = re.compile(r"^\s*Download (?:url|fallback \d+):\s+(https?://\S+)\s*$")
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def _openkitsune_root() -> Path:
    configured = os.environ.get("OPENKITSUNE_ROOT", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".openkitsune"


def _request_store_path() -> Path:
    return _openkitsune_root() / "data" / "optional_feature_requests.json"


def _load_requests() -> dict[str, dict]:
    data = read_json_safe(_request_store_path()) or {}
    requests = data.get("requests") if isinstance(data, dict) else None
    return requests if isinstance(requests, dict) else {}


def _save_requests(requests: dict[str, dict]) -> None:
    atomic_json_write(
        _request_store_path(),
        {"schema_version": 1, "requests": requests},
        backup=True,
    )


def create_install_request(conversation_id: str, *, visible: bool = True) -> dict:
    request_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    request = {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "feature_id": BROWSER_AUTOMATION_FEATURE,
        "title": "安装浏览器自动化组件",
        "description": "包含 Playwright 运行时和 Chromium，安装后才能使用浏览器自动化。",
        "components": [
            {"id": PLAYWRIGHT_RUNTIME_FEATURE, "name": "Playwright driver + Node"},
            {"id": "browser.chromium", "name": "Chromium + FFmpeg"},
        ],
        "estimated_download_mb": 450,
        "estimated_disk_mb": 550,
        "status": "pending",
        "progress": 0,
        "phase": "awaiting_confirmation",
        "phase_progress": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "current_item": "",
        "install_progress": 0,
        "message": "等待用户确认",
        "visible": bool(visible),
        "created_at": now,
        "updated_at": now,
    }
    with _REQUEST_LOCK:
        requests = _load_requests()
        requests[request_id] = request
        _save_requests(requests)
    _REQUEST_EVENTS.setdefault(request_id, asyncio.Event())
    return dict(request)


def get_install_request(request_id: str) -> dict | None:
    with _REQUEST_LOCK:
        request = _load_requests().get(request_id)
    if not isinstance(request, dict):
        return None
    if request.get("status") == "installing":
        active_lock = _INSTALL_LOCKS.get(request_id)
        if active_lock is None or not active_lock.locked():
            recovered = update_install_request(
                request_id,
                status="failed",
                message="上次安装已中断，已下载内容会在重试时继续使用",
            )
            return recovered
    return dict(request)


def update_install_request(request_id: str, **changes: Any) -> dict | None:
    with _REQUEST_LOCK:
        requests = _load_requests()
        request = requests.get(request_id)
        if not isinstance(request, dict):
            return None
        request.update(changes)
        request["updated_at"] = datetime.now(UTC).isoformat()
        requests[request_id] = request
        _save_requests(requests)
    if request.get("status") in {"installed", "failed", "cancelled"}:
        event = _REQUEST_EVENTS.get(request_id)
        if event is not None:
            event.set()
    return dict(request)


async def wait_for_install_request(request_id: str, timeout: float = 900) -> dict | None:
    request = get_install_request(request_id)
    if not request or request.get("status") in {"installed", "failed", "cancelled"}:
        return request
    event = _REQUEST_EVENTS.setdefault(request_id, asyncio.Event())
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        return get_install_request(request_id)
    return get_install_request(request_id)


def optional_feature_marker(*, visible: bool = True) -> str:
    return OPTIONAL_FEATURE_MARKER + json.dumps({"visible": bool(visible)}, separators=(",", ":"))


def parse_optional_feature_marker(value: object) -> dict | None:
    if not isinstance(value, str) or OPTIONAL_FEATURE_MARKER not in value:
        return None
    raw = value.split(OPTIONAL_FEATURE_MARKER, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _playwright_version() -> str:
    return package_version("playwright")


def _managed_driver_dir() -> Path:
    return _openkitsune_root() / "modules" / "browser" / "playwright-driver" / _playwright_version()


def _driver_paths(root: Path) -> tuple[Path, Path]:
    node = root / ("node.exe" if os.name == "nt" else "node")
    return node, root / "package" / "cli.js"


def resolve_playwright_driver() -> tuple[str, str] | None:
    import inspect

    import playwright

    bundled = Path(inspect.getfile(playwright)).parent / "driver"
    for root in (bundled, _managed_driver_dir()):
        node, cli = _driver_paths(root)
        if node.is_file() and cli.is_file():
            return str(node), str(cli)
    return None


def configure_playwright_driver() -> tuple[str, str] | None:
    resolved = resolve_playwright_driver()
    if resolved is None:
        return None

    from playwright._impl import _driver, _transport

    def compute() -> tuple[str, str]:
        return resolved

    _driver.compute_driver_executable = compute
    _transport.compute_driver_executable = compute
    return resolved


def _runtime_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if system == "Windows":
        return "windows-arm64" if arm else "windows-x64"
    if system == "Darwin":
        return "macos-arm64" if arm else "macos-x64"
    if system == "Linux":
        return "linux-arm64" if arm else "linux-x64"
    raise RuntimeError(f"Unsupported Playwright runtime platform: {system} {machine}")


def _select_driver_artifact() -> dict:
    feature = load_optional_asset_feature(PLAYWRIGHT_RUNTIME_FEATURE)
    if not feature:
        raise RuntimeError("Playwright runtime manifest is unavailable")
    versions = feature.get("versions")
    release = versions.get(_playwright_version()) if isinstance(versions, dict) else None
    if not isinstance(release, dict):
        raise RuntimeError(f"No mirrored Playwright runtime for version {_playwright_version()}")
    target = _runtime_platform()
    for artifact in release.get("artifacts", []):
        if isinstance(artifact, dict) and artifact.get("platform") == target:
            selected = dict(artifact)
            mirror_root = os.environ.get("OPENKITSUNE_OPTIONAL_ASSET_MIRROR", "").strip()
            mirror_path = str(selected.get("path") or "").lstrip("/")
            if mirror_root and mirror_path:
                selected["mirror_url"] = urljoin(f"{mirror_root.rstrip('/')}/", mirror_path)
            return selected
    raise RuntimeError(f"No Playwright runtime artifact for {target}")


def _optional_asset_cache() -> Path:
    return _openkitsune_root() / "cache" / "optional-assets"


def _response_total(response: Any, offset: int) -> int:
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            return int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    try:
        return offset + int(response.headers.get("Content-Length") or 0)
    except ValueError:
        return 0


def _download_resumable(
    sources: list[str],
    destination: Path,
    *,
    expected_hash: str = "",
    expected_size: int = 0,
    progress: Any | None = None,
) -> Path:
    """Download into a persistent .part file and resume with HTTP Range."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    if destination.is_file():
        if expected_hash and hashlib.sha256(destination.read_bytes()).hexdigest() != expected_hash:
            destination.unlink()
        elif not expected_size or destination.stat().st_size == expected_size:
            if progress:
                progress(destination.stat().st_size, expected_size or destination.stat().st_size)
            return destination

    last_error: Exception | None = None
    for url in sources:
        if not url:
            continue
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "OpenKitsune optional-feature"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                resumed = offset > 0 and getattr(response, "status", None) == 206
                if offset and not resumed:
                    offset = 0
                total = expected_size or _response_total(response, offset)
                mode = "ab" if resumed else "wb"
                downloaded = offset
                if progress:
                    progress(downloaded, total)
                with open(partial, mode) as output:
                    while chunk := response.read(_DOWNLOAD_CHUNK_SIZE):
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
            if expected_size and partial.stat().st_size != expected_size:
                raise RuntimeError(
                    f"download size mismatch: expected {expected_size}, got {partial.stat().st_size}"
                )
            if expected_hash:
                digest = hashlib.sha256(partial.read_bytes()).hexdigest()
                if digest != expected_hash:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("download SHA-256 mismatch")
            partial.replace(destination)
            return destination
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"download failed: {last_error}")


def install_playwright_runtime(progress: Any | None = None) -> Path:
    existing = configure_playwright_driver()
    if existing is not None:
        return _managed_driver_dir()

    artifact = _select_driver_artifact()
    sources = [artifact.get("mirror_url"), artifact.get("upstream_url")]
    expected_hash = str(artifact.get("sha256") or "").lower()
    if not expected_hash:
        raise RuntimeError("Playwright runtime artifact has no SHA-256")

    target = _managed_driver_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = (
        _optional_asset_cache()
        / "playwright"
        / _playwright_version()
        / str(artifact.get("name") or "playwright.whl")
    )
    if progress:
        progress(0, int(artifact.get("size") or 0), "Playwright driver + Node")
    _download_resumable(
        [str(source) for source in sources if source],
        archive,
        expected_hash=expected_hash,
        expected_size=int(artifact.get("size") or 0),
        progress=(
            (lambda downloaded, total: progress(downloaded, total, "Playwright driver + Node"))
            if progress
            else None
        ),
    )
    with tempfile.TemporaryDirectory(prefix="openkitsune-playwright-") as temp_name:
        temp = Path(temp_name)
        extracted = temp / "driver"
        prefix = "playwright/driver/"
        with zipfile.ZipFile(archive) as wheel:
            members = [name for name in wheel.namelist() if name.startswith(prefix)]
            if not members:
                raise RuntimeError("Playwright wheel does not contain driver files")
            for name in members:
                relative = name[len(prefix) :]
                if not relative or relative.endswith("/"):
                    continue
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise RuntimeError("Playwright wheel contains an unsafe driver path")
                output = extracted / relative_path
                output.parent.mkdir(parents=True, exist_ok=True)
                with wheel.open(name) as source, open(output, "wb") as destination:
                    shutil.copyfileobj(source, destination)

        node, cli = _driver_paths(extracted)
        if not node.is_file() or not cli.is_file():
            raise RuntimeError("Extracted Playwright driver is incomplete")
        if os.name != "nt":
            node.chmod(node.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if target.exists():
            shutil.rmtree(target)
        extracted.replace(target)
    configure_playwright_driver()
    return target


def _discover_chromium_downloads() -> list[dict]:
    resolved = configure_playwright_driver()
    if resolved is None:
        raise RuntimeError("Playwright driver runtime is not installed")
    node, cli = resolved
    env = dict(os.environ)
    env.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
    result = subprocess.run(
        [str(node), str(cli), "install", "--dry-run", "--no-shell", "chromium"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    artifacts: list[dict] = []
    current: dict | None = None
    for line in result.stdout.splitlines():
        header = _PLAYWRIGHT_HEADER.match(line.strip())
        if header:
            current = {"name": header.group(1), "sources": []}
            continue
        match = _PLAYWRIGHT_URL.match(line)
        if not match or current is None:
            continue
        url = match.group(1)
        current["sources"].append(url)
        if len(current["sources"]) == 1:
            path = urlparse(url).path
            marker = "/builds/"
            if marker not in path:
                raise RuntimeError(f"Unsupported Playwright download URL: {url}")
            current["path"] = "builds/" + path.split(marker, 1)[1]
            artifacts.append(current)
    if not artifacts:
        raise RuntimeError("Playwright did not report Chromium download artifacts")
    return artifacts


def cache_chromium_downloads(progress: Any | None = None) -> Path:
    from openkitsune.optional_assets import resolve_optional_asset_mirror

    artifacts = _discover_chromium_downloads()
    mirror = resolve_optional_asset_mirror(
        "browser.chromium",
        strategy="playwright_download_host",
        mirror_path="optional/playwright",
    )
    cache_root = _optional_asset_cache() / "playwright"
    for index, artifact in enumerate(artifacts):
        sources = list(artifact["sources"])
        if mirror is not None:
            sources.insert(0, urljoin(f"{mirror.base_url}/", artifact["path"]))

        def report(
            downloaded: int,
            total: int,
            *,
            _index: int = index,
            _name: str = str(artifact["name"]),
        ) -> None:
            if progress:
                progress(downloaded, total, _name, _index, len(artifacts))

        _download_resumable(
            sources,
            cache_root / artifact["path"],
            progress=report,
        )
    return cache_root


class _QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextmanager
def serve_optional_asset_cache(root: Path):
    def handler(*args: Any, **kwargs: Any):
        return _QuietFileHandler(*args, directory=str(root), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def install_browser_automation(request_id: str) -> dict:
    lock = _INSTALL_LOCKS.setdefault(request_id, asyncio.Lock())
    async with lock:
        request = get_install_request(request_id)
        if not request:
            raise KeyError(request_id)
        if request.get("status") == "installed":
            return request

        def download_progress(
            downloaded: int,
            total: int,
            item: str,
            index: int = 0,
            count: int = 1,
        ) -> None:
            item_progress = int(downloaded * 100 / total) if total else 0
            update_install_request(
                request_id,
                phase="downloading",
                phase_progress=item_progress,
                progress=min(80, 5 + int(((index + item_progress / 100) / count) * 75)),
                downloaded_bytes=downloaded,
                total_bytes=total,
                current_item=item,
                message=f"正在下载 {item}（{index + 1}/{count}）",
            )

        update_install_request(
            request_id,
            status="installing",
            progress=1,
            phase="downloading",
            phase_progress=0,
            install_progress=0,
            message="准备下载",
        )
        try:
            await asyncio.to_thread(install_playwright_runtime, download_progress)
            from openkitsune.tools.browser.manager import (
                _download_managed_chromium,
                _managed_browsers_dir,
            )

            cache_root = await asyncio.to_thread(cache_chromium_downloads, download_progress)
            update_install_request(
                request_id,
                phase="installing",
                phase_progress=100,
                install_progress=15,
                progress=82,
                current_item="Chromium",
                message="正在安装 Chromium",
            )
            with serve_optional_asset_cache(cache_root) as local_host:
                await _download_managed_chromium(
                    _managed_browsers_dir(),
                    download_host=local_host,
                    progress=lambda value, message: update_install_request(
                        request_id,
                        install_progress=value,
                        progress=82 + int(value * 0.14),
                        message=message,
                    ),
                )
            update_install_request(
                request_id,
                install_progress=90,
                progress=96,
                message="正在验证浏览器组件",
            )
            return (
                update_install_request(
                    request_id,
                    status="installed",
                    progress=100,
                    phase="complete",
                    phase_progress=100,
                    install_progress=100,
                    message="浏览器自动化组件安装完成",
                )
                or {}
            )
        except Exception as exc:
            update_install_request(request_id, status="failed", message=str(exc), progress=0)
            raise
