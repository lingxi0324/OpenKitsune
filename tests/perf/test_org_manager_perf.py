"""Opt-in performance baselines for filesystem-backed organization storage."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openkitsune.orgs.manager import OrgManager


@pytest.mark.perf
def test_100_blob_create_and_list_performance(tmp_path: Path) -> None:
    """Create and list 100 organizations within the established budget."""
    manager = OrgManager(tmp_path)

    started_at = time.perf_counter()
    for i in range(100):
        manager.create({"name": f"blob_{i:03d}"})
    items = manager.list_orgs()
    elapsed = time.perf_counter() - started_at

    assert len(items) == 100
    assert elapsed < 5.0, f"100-blob stress took {elapsed:.2f}s (> 5s budget)"
