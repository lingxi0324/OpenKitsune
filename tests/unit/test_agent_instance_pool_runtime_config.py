import asyncio

import pytest

from openkitsune.agents.factory import AgentInstancePool
from openkitsune.agents.profile import AgentProfile


class _DummyAgent:
    def __init__(self, label: str):
        self.label = label
        self.brain = object()
        self.shutdown_called = False

    async def shutdown(self):
        self.shutdown_called = True


class _DummyFactory:
    def __init__(self):
        self.created = 0
        self.parent_brains = []

    async def create(self, profile: AgentProfile, parent_brain=None):
        self.created += 1
        self.parent_brains.append(parent_brain)
        return _DummyAgent(f"{profile.id}-{self.created}")


@pytest.mark.asyncio
async def test_runtime_config_change_recreates_pooled_agent():
    factory = _DummyFactory()
    pool = AgentInstancePool(factory=factory)
    profile = AgentProfile(id="default", name="Default")

    first = await pool.get_or_create("session-1", profile)
    reused = await pool.get_or_create("session-1", profile)
    assert reused is first

    pool.notify_runtime_config_changed("llm_config")

    recreated = await pool.get_or_create("session-1", profile)
    assert recreated is not first
    assert factory.created == 2


@pytest.mark.asyncio
async def test_runtime_config_change_does_not_reuse_stale_parent_brain():
    factory = _DummyFactory()
    pool = AgentInstancePool(factory=factory)
    default_profile = AgentProfile(id="default", name="Default")
    worker_profile = AgentProfile(id="worker", name="Worker")

    await pool.get_or_create("session-1", default_profile)
    await pool.get_or_create("session-1", worker_profile)

    pool.notify_runtime_config_changed("llm_config")

    await pool.get_or_create("session-1", worker_profile)

    assert factory.parent_brains[-1] is None


@pytest.mark.asyncio
async def test_profile_invalidation_during_creation_rebuilds_with_latest_profile():
    started = asyncio.Event()
    release = asyncio.Event()
    created_profiles: list[str] = []

    class _BlockingFactory:
        async def create(self, profile: AgentProfile, parent_brain=None):
            created_profiles.append(profile.name)
            if len(created_profiles) == 1:
                started.set()
                await release.wait()
            return _DummyAgent(profile.name)

    old_profile = AgentProfile(id="worker", name="Old")
    latest_profile = AgentProfile(id="worker", name="Latest")
    store = type("Store", (), {"get": lambda self, _profile_id: latest_profile})()
    pool = AgentInstancePool(factory=_BlockingFactory(), profile_store=store)

    task = asyncio.create_task(pool.get_or_create("session-1", old_profile))
    await started.wait()
    pool.invalidate_profile("worker")
    release.set()

    agent = await task

    assert agent.label == "Latest"
    assert created_profiles == ["Old", "Latest"]
    assert await pool.get_or_create("session-1", latest_profile) is agent
