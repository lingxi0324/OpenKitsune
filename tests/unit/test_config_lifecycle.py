import sys
from types import SimpleNamespace

from openkitsune.config_lifecycle import (
    ConfigApplyMode,
    classify_config_changes,
    classify_config_key,
    effective_config_values,
    reload_config_components,
)


async def test_classify_config_api_reuses_runtime_lifecycle_policy(monkeypatch):
    from openkitsune.api.routes.config import ConfigClassifyRequest, classify_config
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "api_port", 18900)
    monkeypatch.setattr(settings, "ui_theme", "system")

    response = await classify_config(
        ConfigClassifyRequest(keys=["UI_THEME", "DESKTOP_MAX_WIDTH", "API_PORT"])
    )

    assert response == {
        "apply_mode": "process_restart",
        "apply_modes": {
            "API_PORT": "process_restart",
            "DESKTOP_MAX_WIDTH": "component_reload",
            "UI_THEME": "immediate",
        },
        "effective_values": {
            "API_PORT": "18900",
            "UI_THEME": "system",
        },
        "restart_required": True,
        "hot_reloadable": False,
    }


def test_effective_values_expose_settings_defaults_for_missing_env_keys(monkeypatch):
    from openkitsune.config import settings

    monkeypatch.setattr(settings, "desktop_notify_enabled", False)

    assert effective_config_values(["DESKTOP_NOTIFY_ENABLED"]) == {
        "DESKTOP_NOTIFY_ENABLED": "false"
    }


def test_process_infrastructure_requires_restart_by_exact_field_name():
    assert classify_config_key("API_HOST") is ConfigApplyMode.PROCESS_RESTART
    assert classify_config_key("API_PORT") is ConfigApplyMode.PROCESS_RESTART
    assert classify_config_key("DATABASE_PATH") is ConfigApplyMode.PROCESS_RESTART


def test_qqbot_and_other_channel_fields_require_restart():
    assert classify_config_key("QQBOT_ENABLED") is ConfigApplyMode.PROCESS_RESTART
    assert classify_config_key("QQBOT_APP_SECRET") is ConfigApplyMode.PROCESS_RESTART
    assert classify_config_key("TELEGRAM_ENABLED") is ConfigApplyMode.PROCESS_RESTART


def test_agent_owned_settings_apply_at_next_task_boundary():
    assert classify_config_key("MAX_ITERATIONS") is ConfigApplyMode.NEXT_TASK
    assert classify_config_key("MAX_TOKENS") is ConfigApplyMode.NEXT_TASK
    assert classify_config_key("MCP_ENABLED") is ConfigApplyMode.NEXT_TASK
    assert classify_config_key("MCP_TIMEOUT") is ConfigApplyMode.NEXT_TASK
    assert classify_config_key("OPENAI_API_KEY") is ConfigApplyMode.NEXT_TASK


def test_dynamic_and_presentation_settings_apply_immediately():
    assert classify_config_key("WEB_SEARCH_PROVIDER") is ConfigApplyMode.IMMEDIATE
    assert classify_config_key("DESKTOP_NOTIFY_ENABLED") is ConfigApplyMode.IMMEDIATE
    assert classify_config_key("UI_THEME") is ConfigApplyMode.IMMEDIATE


def test_desktop_settings_reload_the_component_without_process_restart():
    plan = classify_config_changes(["DESKTOP_ENABLED", "DESKTOP_MAX_WIDTH"])

    assert plan.apply_mode is ConfigApplyMode.COMPONENT_RELOAD
    assert plan.restart_required is False
    assert plan.hot_reloadable is True
    assert plan.component_reload_keys == {"DESKTOP_ENABLED", "DESKTOP_MAX_WIDTH"}


def test_desktop_component_reload_resets_cached_config(monkeypatch):
    reset_calls: list[bool] = []
    desktop_config = SimpleNamespace(reset_config=lambda: reset_calls.append(True))
    monkeypatch.setitem(sys.modules, "openkitsune.tools.desktop.config", desktop_config)
    plan = classify_config_changes(["DESKTOP_ENABLED"])

    assert reload_config_components(plan) == {"desktop": "reloaded"}
    assert reset_calls == [True]


def test_desktop_component_reload_does_not_import_unloaded_platform_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "openkitsune.tools.desktop.config", raising=False)
    plan = classify_config_changes(["DESKTOP_ENABLED"])

    assert reload_config_components(plan) == {"desktop": "reloaded"}
    assert "openkitsune.tools.desktop.config" not in sys.modules


def test_unknown_environment_key_is_not_claimed_as_hot_reloadable():
    assert classify_config_key("THIRD_PARTY_IMPORT_TIME_FLAG") is ConfigApplyMode.PROCESS_RESTART


def test_change_plan_reports_each_key_and_strongest_mode():
    plan = classify_config_changes(["MAX_ITERATIONS", "API_PORT", "UI_THEME"])

    assert plan.modes == {
        "API_PORT": ConfigApplyMode.PROCESS_RESTART,
        "MAX_ITERATIONS": ConfigApplyMode.NEXT_TASK,
        "UI_THEME": ConfigApplyMode.IMMEDIATE,
    }
    assert plan.apply_mode is ConfigApplyMode.PROCESS_RESTART
    assert plan.restart_required is True
    assert plan.hot_reloadable is False
    assert plan.next_task_keys == {"MAX_ITERATIONS"}
