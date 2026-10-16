from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _Pool:
    def __init__(self):
        self.invalidated: list[str] = []

    def invalidate_profile(self, profile_id: str) -> int:
        self.invalidated.append(profile_id)
        return 1


class _Store:
    def __init__(self):
        self.profile = SimpleNamespace(id="worker", is_system=False)
        self.deleted = False

    def get(self, profile_id: str):
        return self.profile if profile_id == "worker" else None

    def delete(self, profile_id: str) -> bool:
        self.deleted = profile_id == "worker"
        return self.deleted


def _empty_org_manager():
    return SimpleNamespace(
        list_orgs=lambda include_archived: [],
        get=lambda _org_id: None,
    )


@pytest.mark.asyncio
async def test_delete_profile_rejects_im_bot_reference(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(
        settings,
        "im_bots",
        [{"id": "feishu-a", "name": "Support", "agent_profile_id": "worker"}],
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(org_manager=None)))

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent_profile("worker", request)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["references"][0]["id"] == "feishu-a"
    assert store.deleted is False


@pytest.mark.asyncio
async def test_delete_profile_rejects_org_node_reference(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])
    org = SimpleNamespace(
        nodes=[SimpleNamespace(id="reviewer", name="Reviewer", agent_profile_id="worker")]
    )
    manager = SimpleNamespace(
        list_orgs=lambda include_archived: [{"id": "org-1"}],
        get=lambda org_id: org if org_id == "org-1" else None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(org_manager=manager)))

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent_profile("worker", request)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["references"][0]["id"] == "org-1:reviewer"
    assert store.deleted is False


@pytest.mark.asyncio
async def test_delete_profile_fails_closed_when_references_cannot_be_checked(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])

    def _fail_list(*, include_archived: bool):
        raise OSError("organization store unavailable")

    manager = SimpleNamespace(list_orgs=_fail_list)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(org_manager=manager)))

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent_profile("worker", request)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["error"] == "profile_reference_check_failed"
    assert store.deleted is False


@pytest.mark.asyncio
async def test_delete_profile_fails_closed_when_org_manager_is_unavailable(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(org_manager=None)))

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent_profile("worker", request)

    assert exc_info.value.status_code == 503
    assert store.deleted is False


@pytest.mark.asyncio
async def test_delete_profile_uses_strict_organization_scan(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])

    def _strict_scan():
        raise ValueError("corrupt organization")

    manager = SimpleNamespace(
        list_organizations_strict=_strict_scan,
        list_orgs=lambda include_archived: [],
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(org_manager=manager)))

    with pytest.raises(HTTPException) as exc_info:
        await delete_agent_profile("worker", request)

    assert exc_info.value.status_code == 500
    assert store.deleted is False


@pytest.mark.asyncio
async def test_delete_profile_invalidates_both_agent_pools(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings
    from openkitsune.prompt import builder

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])
    monkeypatch.setattr(builder, "clear_prompt_section_cache", lambda: None)
    desktop = _Pool()
    orchestrator = _Pool()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                org_manager=_empty_org_manager(),
                agent_pool=desktop,
                orchestrator=SimpleNamespace(_pool=orchestrator),
            )
        )
    )

    response = await delete_agent_profile("worker", request)

    assert response["status"] == "ok"
    assert store.deleted is True
    assert desktop.invalidated == ["worker"]
    assert orchestrator.invalidated == ["worker"]


@pytest.mark.asyncio
async def test_delete_profile_preserves_success_when_runtime_invalidation_fails(monkeypatch) -> None:
    from openkitsune.agents import profile as profile_module
    from openkitsune.api.routes.agents import delete_agent_profile
    from openkitsune.config import settings
    from openkitsune.prompt import builder

    class _FailingPool:
        def invalidate_profile(self, _profile_id: str) -> int:
            raise RuntimeError("pool unavailable")

    store = _Store()
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)
    monkeypatch.setattr(settings, "im_bots", [])
    monkeypatch.setattr(builder, "clear_prompt_section_cache", lambda: None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                org_manager=_empty_org_manager(),
                agent_pool=_FailingPool(),
            )
        )
    )

    response = await delete_agent_profile("worker", request)

    assert response["operation_status"] == "ok"
    assert response["status"] == "partial"
    assert response["runtime"]["failed"]["agent_pool"] == "pool unavailable"
    assert store.deleted is True
