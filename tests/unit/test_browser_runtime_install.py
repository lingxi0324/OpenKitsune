from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openkitsune.optional_assets import OptionalAssetMirror
from openkitsune.tools.browser import manager


class _InstallProcess:
    def __init__(self, browsers_dir: Path, *, returncode: int = 0) -> None:
        self.returncode = returncode
        self._browsers_dir = browsers_dir
        self.killed = False

    async def communicate(self):
        if self.returncode == 0:
            (self._browsers_dir / "chromium-expected").mkdir(parents=True, exist_ok=True)
        return b"playwright install output", b""

    def kill(self) -> None:
        self.killed = True


def test_managed_browsers_dir_respects_openkitsune_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path))

    assert manager._managed_browsers_dir() == tmp_path / "modules" / "browser" / "browsers"


@pytest.mark.asyncio
async def test_download_managed_chromium_uses_bundled_driver_cli(
    tmp_path: Path, monkeypatch
) -> None:
    browsers_dir = tmp_path / "browsers"
    calls = []

    async def fake_subprocess(*args, **kwargs):
        calls.append((args, kwargs))
        return _InstallProcess(browsers_dir)

    monkeypatch.setattr(
        "openkitsune.optional_features.configure_playwright_driver",
        lambda: (tmp_path / "node", tmp_path / "cli.js"),
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(manager, "resolve_optional_asset_mirror", lambda *args, **kwargs: None)

    await manager._download_managed_chromium(browsers_dir)

    args, kwargs = calls[0]
    assert args[-3:] == ("install", "--no-shell", "chromium")
    assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_dir)
    assert (browsers_dir / "chromium-expected").is_dir()


@pytest.mark.asyncio
async def test_download_managed_chromium_reports_installer_failure(
    tmp_path: Path, monkeypatch
) -> None:
    browsers_dir = tmp_path / "browsers"

    monkeypatch.setattr(
        "openkitsune.optional_features.configure_playwright_driver",
        lambda: (tmp_path / "node", tmp_path / "cli.js"),
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        lambda *args, **kwargs: _async_value(_InstallProcess(browsers_dir, returncode=1)),
    )
    monkeypatch.setattr(manager, "resolve_optional_asset_mirror", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="Chromium download failed"):
        await manager._download_managed_chromium(browsers_dir)


@pytest.mark.asyncio
async def test_download_managed_chromium_prefers_mirror_then_falls_back(
    tmp_path: Path, monkeypatch
) -> None:
    browsers_dir = tmp_path / "browsers"
    calls = []
    processes = iter(
        (
            _InstallProcess(browsers_dir, returncode=1),
            _InstallProcess(browsers_dir, returncode=0),
        )
    )

    async def fake_subprocess(*args, **kwargs):
        calls.append((args, kwargs))
        return next(processes)

    monkeypatch.setattr(
        "playwright._impl._driver.compute_driver_executable",
        lambda: (tmp_path / "node", tmp_path / "cli.js"),
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(
        manager,
        "resolve_optional_asset_mirror",
        lambda *args, **kwargs: OptionalAssetMirror(
            "browser.chromium",
            "playwright_download_host",
            "https://mirror.example/optional/playwright",
        ),
    )
    monkeypatch.delenv("PLAYWRIGHT_DOWNLOAD_HOST", raising=False)

    await manager._download_managed_chromium(browsers_dir)

    assert len(calls) == 2
    assert (
        calls[0][1]["env"]["PLAYWRIGHT_DOWNLOAD_HOST"]
        == "https://mirror.example/optional/playwright"
    )
    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in calls[1][1]["env"]


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_missing_chromium_downloads_then_restarts_driver(tmp_path: Path, monkeypatch) -> None:
    missing_executable = tmp_path / "missing" / "chrome.exe"
    installed_executable = tmp_path / "browsers" / "chromium-current" / "chrome.exe"
    installed_executable.parent.mkdir(parents=True)
    installed_executable.write_bytes(b"x" * 1_100_000)

    browser_type = SimpleNamespace(executable_path=str(missing_executable))
    browser_manager = object.__new__(manager.BrowserManager)
    browser_manager._bundled_executable = None
    browser_manager._playwright = SimpleNamespace(chromium=browser_type)
    browser_manager._chromium_install_error = None
    browser_manager._chromium_install_allowed = True
    browser_manager.chromium_install_required = False
    browser_manager._is_server = False
    browser_manager._cleanup_playwright = AsyncMock()
    browser_manager._launch_persistent = AsyncMock(return_value=True)
    browser_manager._launch_standard = AsyncMock(return_value=False)

    async def restart_driver() -> bool:
        browser_type.executable_path = str(installed_executable)
        return True

    browser_manager._start_playwright_driver = restart_driver
    download = AsyncMock()
    monkeypatch.setattr(manager, "_managed_browsers_dir", lambda: tmp_path / "browsers")
    monkeypatch.setattr(manager, "_download_managed_chromium", download)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

    assert await browser_manager._try_bundled_chromium(headless=True)
    download.assert_awaited_once_with(tmp_path / "browsers")
    browser_manager._cleanup_playwright.assert_awaited_once()
    browser_manager._launch_persistent.assert_awaited_once_with(None, True)
    assert manager.os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "browsers")


@pytest.mark.asyncio
async def test_missing_chromium_requires_confirmation_without_downloading(
    tmp_path: Path, monkeypatch
) -> None:
    browser_manager = object.__new__(manager.BrowserManager)
    browser_manager._bundled_executable = None
    browser_manager._playwright = SimpleNamespace(
        chromium=SimpleNamespace(executable_path=str(tmp_path / "missing" / "chrome.exe"))
    )
    browser_manager._chromium_install_error = None
    browser_manager._chromium_install_allowed = False
    browser_manager.chromium_install_required = False
    browser_manager._is_server = False
    download = AsyncMock()
    monkeypatch.setattr(manager, "_download_managed_chromium", download)

    with pytest.raises(RuntimeError, match="请先询问用户是否下载安装"):
        await browser_manager._try_bundled_chromium(headless=True)

    assert browser_manager.chromium_install_required is True
    download.assert_not_awaited()
