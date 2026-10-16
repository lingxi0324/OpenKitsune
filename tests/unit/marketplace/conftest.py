"""Keep all installation probes inside the test's temporary workspace."""

import pytest

from openkitsune.config import settings
from openkitsune.skills import allowlist_io


@pytest.fixture(autouse=True)
def isolated_marketplace_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENKITSUNE_ROOT", str(tmp_path / "home"))
    monkeypatch.setattr(settings, "project_root", tmp_path / "project")
    monkeypatch.setattr(allowlist_io, "_skills_json_path", lambda: tmp_path / "skills.json")
