"""openkitsune-brain 记忆 Provider 接入测试。

覆盖：
- Windows 盘符路径 → WSL 挂载路径归一化；
- Provider 的 MemoryRecord 到 RetrievalEngine 外部候选的适配；
- 旧数据源可用时的真实检索与分页读取（不可用时自动跳过）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openkitsune.memory.okmem_provider import (
    OkmemRetrievalSource,
    _default_okmem_home,
    _normalize_okmem_home,
    create_okmem_provider,
)
from openkitsune.memory.public_api import MemoryRecord

LIVE_HOME = Path("/mnt/e/agents/openkitsune-brain")


class _StubProvider:
    async def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return [
            MemoryRecord(
                id="okmem:1",
                content=f"命中:{query}",
                score=0.87,
                metadata={"backend": "okmem", "fmt": "semantic"},
            )
        ]

    def close(self) -> None:
        return None


async def test_retrieval_source_maps_records() -> None:
    source = OkmemRetrievalSource(_StubProvider())
    items = await source.retrieve("河图洛书", limit=3)

    assert source.source_name == "openkitsune-brain"
    assert len(items) == 1
    assert items[0]["id"] == "okmem:1"
    assert items[0]["content"] == "命中:河图洛书"
    assert items[0]["relevance"] == pytest.approx(0.87)
    assert items[0]["metadata"]["backend"] == "okmem"


def test_normalize_windows_path_for_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    assert (
        _normalize_okmem_home(r"E:\agents\openkitsune-brain")
        == "/mnt/e/agents/openkitsune-brain"
    )
    assert (
        _normalize_okmem_home("E:/agents/openkitsune-brain")
        == "/mnt/e/agents/openkitsune-brain"
    )
    assert _normalize_okmem_home("/mnt/e/agents/openkitsune-brain") == (
        "/mnt/e/agents/openkitsune-brain"
    )


def test_default_home_has_expected_name() -> None:
    assert Path(_default_okmem_home()).name == "openkitsune-brain"


@pytest.mark.skipif(
    not (LIVE_HOME / "okmem").is_dir(),
    reason="openkitsune-brain 数据目录未挂载到 WSL",
)
async def test_live_provider_reads_legacy_store() -> None:
    provider = create_okmem_provider(home=str(LIVE_HOME), auto_embed=False)
    try:
        stats = await provider.stats()
        assert "by_fmt" in stats["okmem"]

        hits = await provider.search("方案", limit=3)
        assert isinstance(hits, list)
        for record in hits:
            assert record.id.startswith(("okmem:", "fusion:", "fusion-fts:"))
            page = await provider.read_content(record.id, limit=16)
            assert page["ok"] is True
            assert page["total"] >= len(page["content"])
    finally:
        provider.close()
