import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

from openkitsune.api.routes.agents import (
    BotCreateRequest,
    BotToggleRequest,
    BotUpdateRequest,
    _bot_apply_tasks,
    _runtime_bot_view,
    _validate_bot_credentials,
    create_bot,
    toggle_bot,
    update_bot,
)


@pytest.fixture(autouse=True)
def _default_profile_store(monkeypatch):
    """Keep bot lifecycle tests independent from profiles persisted on the host."""
    from openkitsune.agents import profile as profile_module

    default_profile = SimpleNamespace(id="default")
    store = SimpleNamespace(
        get=lambda profile_id: default_profile if profile_id == "default" else None
    )
    monkeypatch.setattr(profile_module, "get_profile_store", lambda: store)


def test_wework_ws_requires_all_credentials() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_bot_credentials("wework_ws", {"bot_id": "bot-1"})

    assert exc_info.value.status_code == 400
    assert "secret" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_bot_rejects_unknown_agent_profile(monkeypatch) -> None:
    import openkitsune.config as config
    from openkitsune.agents import profile as profile_module

    monkeypatch.setattr(config.settings, "im_bots", [], raising=False)
    monkeypatch.setattr(
        profile_module,
        "get_profile_store",
        lambda: SimpleNamespace(get=lambda _profile_id: None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_bot(
            BotCreateRequest(
                id="warehouse",
                type="wework_ws",
                agent_profile_id="missing",
                enabled=False,
                credentials={},
            ),
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
        )

    assert exc_info.value.status_code == 400
    assert "missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_bot_returns_before_runtime_start_and_keeps_failed_config(monkeypatch) -> None:
    import openkitsune.config as config

    original_bots = config.settings.im_bots
    saves: list[list[dict]] = []
    runtime_states: list[tuple[str, str, str | None]] = []
    startup_started = asyncio.Event()
    finish_startup = asyncio.Event()

    async def fail_apply(_bot: dict) -> bool:
        startup_started.set()
        await finish_startup.wait()
        return False

    monkeypatch.setattr(config.settings, "im_bots", [], raising=False)

    def save_updates(**updates):
        for key, value in updates.items():
            setattr(config.settings, key, value)
        saves.append(list(config.settings.im_bots))

    monkeypatch.setattr(config.runtime_state, "save_updates", save_updates)
    main_stub = ModuleType("openkitsune.main")
    main_stub.apply_im_bot = fail_apply
    main_stub.get_im_bot_runtime_error = lambda _channel: None
    main_stub._bot_channel_name = lambda bot: f"{bot['type']}:{bot['id']}"
    main_stub._set_im_bot_runtime_state = lambda channel, status, error=None: runtime_states.append(
        (channel, status, error)
    )
    monkeypatch.setitem(sys.modules, "openkitsune.main", main_stub)

    try:
        response = await create_bot(
            BotCreateRequest(
                id="warehouse",
                type="wework_ws",
                credentials={"bot_id": "bot-1", "secret": "secret-1"},
            ),
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
        )

        assert response["status"] == "accepted"
        assert config.settings.im_bots[0]["id"] == "warehouse"
        assert len(saves) == 1
        assert saves[0][0]["id"] == "warehouse"
        assert runtime_states == [("wework_ws:warehouse", "starting", None)]

        await asyncio.wait_for(startup_started.wait(), timeout=1)
        assert _bot_apply_tasks

        finish_startup.set()
        await asyncio.gather(*tuple(_bot_apply_tasks))

        assert config.settings.im_bots[0]["id"] == "warehouse"
        assert runtime_states[-1] == (
            "wework_ws:warehouse",
            "error",
            "The IM runtime is not available to start this bot",
        )
    finally:
        finish_startup.set()
        if _bot_apply_tasks:
            await asyncio.gather(*tuple(_bot_apply_tasks), return_exceptions=True)
        config.settings.im_bots = original_bots


@pytest.mark.asyncio
async def test_create_bot_restores_in_memory_config_when_persistence_fails(monkeypatch) -> None:
    import openkitsune.config as config

    original_bots = config.settings.im_bots
    existing = [{"id": "existing", "type": "feishu", "enabled": False}]
    monkeypatch.setattr(config.settings, "im_bots", existing, raising=False)
    monkeypatch.setattr(
        config.runtime_state,
        "save_updates",
        lambda **_updates: (_ for _ in ()).throw(OSError("disk full")),
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            await create_bot(
                BotCreateRequest(
                    id="warehouse",
                    type="wework_ws",
                    credentials={"bot_id": "bot-1", "secret": "secret-1"},
                ),
                SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail["error"] == "im_config_save_failed"
        assert config.settings.im_bots is existing
    finally:
        config.settings.im_bots = original_bots


@pytest.mark.asyncio
async def test_update_bot_rolls_back_when_runtime_rejects_without_error_text(monkeypatch) -> None:
    import openkitsune.config as config

    original_bots = config.settings.im_bots
    old_bot = {
        "id": "support",
        "type": "feishu",
        "name": "Old",
        "agent_profile_id": "default",
        "enabled": True,
        "credentials": {"app_id": "cli_x", "app_secret": "secret"},
    }
    applied_names: list[str] = []

    async def reject_apply(candidate: dict) -> bool:
        applied_names.append(str(candidate.get("name", "")))
        return False

    monkeypatch.setattr(config.settings, "im_bots", [old_bot], raising=False)

    def save_updates(**updates):
        for key, value in updates.items():
            setattr(config.settings, key, value)

    monkeypatch.setattr(config.runtime_state, "save_updates", save_updates)
    main_stub = ModuleType("openkitsune.main")
    main_stub.apply_im_bot = reject_apply
    main_stub.get_im_bot_runtime_error = lambda _channel: None
    monkeypatch.setitem(sys.modules, "openkitsune.main", main_stub)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await update_bot(
                "support",
                BotUpdateRequest(name="New"),
                SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            )

        assert exc_info.value.status_code == 502
        assert "did not accept" in exc_info.value.detail
        assert applied_names == ["New", "Old"]
        assert config.settings.im_bots[0]["name"] == "Old"
    finally:
        config.settings.im_bots = original_bots


@pytest.mark.asyncio
async def test_toggle_bot_rolls_back_when_runtime_rejects_enable(monkeypatch) -> None:
    import openkitsune.config as config

    original_bots = config.settings.im_bots
    old_bot = {
        "id": "support",
        "type": "feishu",
        "name": "Support",
        "agent_profile_id": "default",
        "enabled": False,
        "credentials": {"app_id": "cli_x", "app_secret": "secret"},
    }
    saves: list[list[dict]] = []

    async def reject_apply(_bot: dict) -> bool:
        return False

    monkeypatch.setattr(config.settings, "im_bots", [old_bot], raising=False)

    def save_updates(**updates):
        for key, value in updates.items():
            setattr(config.settings, key, value)
        saves.append(list(config.settings.im_bots))

    monkeypatch.setattr(config.runtime_state, "save_updates", save_updates)
    main_stub = ModuleType("openkitsune.main")
    main_stub.apply_im_bot = reject_apply
    main_stub.get_im_bot_runtime_error = lambda _channel: None
    monkeypatch.setitem(sys.modules, "openkitsune.main", main_stub)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await toggle_bot(
                "support",
                BotToggleRequest(enabled=True),
                SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
            )

        assert exc_info.value.status_code == 502
        assert "did not accept" in exc_info.value.detail
        assert [saved[0]["enabled"] for saved in saves] == [True, False]
        assert config.settings.im_bots[0]["enabled"] is False
    finally:
        config.settings.im_bots = original_bots


def test_runtime_status_reports_missing_credentials() -> None:
    from openkitsune.channels.status import collect_effective_im_status

    settings = SimpleNamespace(
        telegram_enabled=False,
        feishu_enabled=False,
        wework_enabled=False,
        wework_ws_enabled=False,
        dingtalk_enabled=False,
        onebot_enabled=False,
        qqbot_enabled=False,
        wechat_enabled=False,
        im_bots=[
            {
                "id": "warehouse",
                "type": "wework_ws",
                "enabled": True,
                "credentials": {},
            }
        ],
    )

    status = collect_effective_im_status(settings)
    detail = next(item for item in status["details"] if item["source"] == "im_bots")

    assert detail["configured"] is False
    assert detail["missing"] == ["bot_id", "secret"]
    assert detail["runtime_status"] == "unknown"


def test_runtime_bot_view_exposes_dependency_install_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "openkitsune.channels.runtime_status.resolve_bot_runtime_state",
        lambda _channel, _gateway=None: {
            "status": "installing_dependencies",
            "error": None,
            "progress": {"phase": "downloading", "percent": 64.0},
        },
    )

    view = _runtime_bot_view(
        {
            "id": "feishu-main",
            "type": "feishu",
            "enabled": True,
            "credentials": {"app_id": "cli_xxx", "app_secret": "secret"},
        },
        {
            "configured": True,
            "missing": [],
            "runtime_seen": False,
            "runtime_status": "unknown",
        },
    )

    assert view["runtime_status"] == "installing_dependencies"
    assert view["runtime_seen"] is True
    assert view["runtime_error"] is None
    assert view["runtime_progress"] == {"phase": "downloading", "percent": 64.0}
