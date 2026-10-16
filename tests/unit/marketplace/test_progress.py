import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from openkitsune.integrations.marketplace.installer import MarketplaceInstallManager


@pytest.mark.asyncio
async def test_download_tracks_real_bytes_and_percent(tmp_path, monkeypatch):
    job = {"size_bytes": 8, "download_url": "https://example.test/package.zip"}
    samples = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"1234"
            samples.append((job["downloaded_bytes"], job["progress"]))
            yield b"5678"

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "openkitsune.integrations.marketplace.installer.httpx.AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())), **kw
        ),
    )
    manager = MarketplaceInstallManager(tmp_path)
    await manager._download(job, tmp_path / "package.zip")
    assert samples == [(4, 50)]
    assert job["downloaded_bytes"] == 8 and job["progress"] == 100
    assert (tmp_path / "package.zip").read_bytes() == b"12345678"


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_plugin_progress_reaches_market_job_and_relay_stops(tmp_path, monkeypatch, fails):
    from openkitsune.api.routes import plugins
    from openkitsune.integrations.marketplace.installer import MarketplaceInstallError

    entered, finish = asyncio.Event(), asyncio.Event()
    trackers = []

    async def install(source, directory, progress, request):
        trackers.append(progress)
        progress.update(
            "dependency_downloading", "private detail never forwarded", dependency="docxtpl"
        )
        entered.set()
        await finish.wait()
        if fails:
            raise RuntimeError("pip failed")
        return "demo", True

    monkeypatch.setattr(plugins, "_do_install", install)
    monkeypatch.setattr(plugins, "_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(plugins, "_finalize_plugin_install", lambda *args: None)
    job = {"status": "installing", "progress": None, "started_at": time.time() - 65}
    task = asyncio.create_task(MarketplaceInstallManager._install_plugin(tmp_path, None, job=job))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        for _ in range(20):
            if job.get("current_dependency") == "docxtpl":
                break
            await asyncio.sleep(0.02)
        assert job["stage"] == "dependency_downloading"
        assert job["current_dependency"] == "docxtpl"
        public = MarketplaceInstallManager._public(job)
        assert public["elapsed_seconds"] >= 65 and public["progress"] is None
        assert "private detail" not in str(public)
    finally:
        finish.set()
        if fails:
            with pytest.raises(MarketplaceInstallError) as caught:
                await task
            assert caught.value.code == "marketplace_plugin_install_failed"
            assert "pip failed" in caught.value.detail
        else:
            assert await task is False
            assert MarketplaceInstallManager._public(job)["plugin_id"] == "demo"
    trackers[0].update("loading", "late event")
    await asyncio.sleep(0.15)
    assert job["stage"] == "dependency_downloading", "Relay leaked after completion"


@pytest.mark.asyncio
async def test_install_has_no_fixed_percentage_and_records_elapsed(tmp_path, monkeypatch):
    manager = MarketplaceInstallManager(tmp_path)
    job = {
        "id": "demo",
        "status": "downloading",
        "progress": 0,
        "token": "token",
        "started_at": time.time() - 5,
        "_installation_snapshot": "unchanged",
    }
    manager._jobs["demo"] = job
    monkeypatch.setattr(manager, "_report", AsyncMock(return_value=True))
    monkeypatch.setattr(manager, "_download", AsyncMock())
    monkeypatch.setattr(
        manager, "_inspect", AsyncMock(return_value={"_installation_snapshot": "unchanged"})
    )
    monkeypatch.setattr(manager, "_flush_terminal_report", AsyncMock())

    def verify(*args):
        assert job["stage"] == "verifying" and job["progress"] is None

    async def install(*args):
        assert job["stage"] == "installing" and job["progress"] is None
        return False

    monkeypatch.setattr(manager, "_verify", verify)
    monkeypatch.setattr(manager, "_install", install)
    await manager._run("demo", None)
    assert job["status"] == "installed" and job["progress"] == 100
    assert job["elapsed_seconds"] >= 5


@pytest.mark.asyncio
async def test_plugin_failure_details_survive_polling_and_restart_without_external_reporting(
    tmp_path, monkeypatch,
):
    from openkitsune.api.routes import plugins
    from openkitsune.integrations.marketplace.installer import MarketplaceInstallError
    from openkitsune.plugins.installer import PluginInstallError

    async def install(source, directory, progress, request):
        progress.update("dependency_downloading", "Downloading", dependency="docxtpl")
        raise PluginInstallError(
            "ERROR: IncompleteRead(428516, 46522) https://user:secret123@example.test/file",
            reason="dependency_network",
        )

    monkeypatch.setattr(plugins, "_do_install", install)
    monkeypatch.setattr(plugins, "_plugins_dir", lambda: tmp_path)
    manager = MarketplaceInstallManager(tmp_path)
    job = {"id": "failure-test", "status": "installing", "token": "private"}
    with pytest.raises(MarketplaceInstallError) as caught:
        await manager._install_plugin(tmp_path, None, job=job)
    report = AsyncMock(return_value=True)
    monkeypatch.setattr(manager, "_report", report)
    exc = caught.value
    await manager._fail(job, exc.code, detail=exc.detail, reason=exc.reason)
    restored = MarketplaceInstallManager(tmp_path)
    public = await restored.get(job["id"])
    assert public["failure_stage"] == "dependency_downloading"
    assert public["current_dependency"] == "docxtpl"
    assert public["failure_reason"] == "dependency_network"
    assert "IncompleteRead(428516, 46522)" in public["failure_detail"]
    assert "secret123" not in str(public)
    assert "token" not in public
    assert report.call_args.kwargs == {"failure_code": "marketplace_plugin_install_failed"}
