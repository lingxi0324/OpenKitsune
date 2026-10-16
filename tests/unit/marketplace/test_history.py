from openkitsune.integrations.marketplace.installer import MarketplaceInstallManager


def test_history_keeps_active_jobs_and_only_recent_terminal_jobs_without_secrets(tmp_path):
    manager = MarketplaceInstallManager(tmp_path)
    manager._jobs = {
        str(index): {
            "id": str(index), "status": "installed", "started_at": index,
            "token": "instruction-secret", "download_url": "signed-url",
            "signature": "signature", "verification": {"private": True},
            "_installation_progress": "internal",
        }
        for index in range(60)
    }
    manager._jobs["active"] = {"id": "active", "status": "installing"}
    history = manager.list_jobs()
    assert len(history) == 51
    assert history[0]["id"] == "active"
    assert history[1]["id"] == "59"
    assert history[-1]["id"] == "10"
    assert not any(
        key in job
        for job in history
        for key in ("token", "download_url", "signature", "verification", "_installation_progress")
    )
