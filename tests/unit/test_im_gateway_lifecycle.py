from types import SimpleNamespace

import pytest


class _FakeGateway:
    def __init__(self, session_manager, agent_handler=None, stt_client=None):
        self.session_manager = session_manager
        self.agent_handler = agent_handler
        self.stt_client = stt_client
        self._running = False
        self.adapters = []
        self.install_errors = {}

    def set_brain(self, brain):
        self.brain = brain

    def set_channel_install_errors(self, errors):
        self.install_errors = errors

    async def register_adapter(self, adapter):
        self.adapters.append(adapter)
        if self._running:
            await adapter.start()

    async def start(self):
        self._running = True

    def get_started_adapters(self):
        return []

    def get_failed_adapters(self):
        return []

    def get_failed_adapter_reasons(self):
        return {}


class _FakeAgent:
    brain = object()

    def set_scheduler_gateway(self, gateway):
        self.scheduler_gateway = gateway

    async def chat_with_session(self, **_kwargs):
        return ""

    async def chat_with_session_stream(self, **_kwargs):
        if False:
            yield None

    def is_stop_command(self, *_args):
        return False

    def is_skip_command(self, *_args):
        return False

    def classify_interrupt(self, *_args):
        return None

    async def cancel_current_task(self, *_args):
        return None

    async def skip_current_step(self, *_args):
        return None

    async def insert_user_message(self, *_args):
        return None


@pytest.mark.asyncio
async def test_empty_gateway_starts_without_dependency_check_and_accepts_hot_bot(monkeypatch):
    import openkitsune.channels as channels
    import openkitsune.logging as openkitsune_logging

    monkeypatch.setattr(openkitsune_logging, "setup_logging", lambda **_kwargs: None)
    import openkitsune.main as main

    for setting_name in (
        "telegram_enabled",
        "feishu_enabled",
        "wework_enabled",
        "wework_ws_enabled",
        "dingtalk_enabled",
        "onebot_enabled",
        "qqbot_enabled",
        "wechat_enabled",
    ):
        monkeypatch.setattr(main.settings, setting_name, False)
    monkeypatch.setattr(main.settings, "im_bots", [])
    monkeypatch.setattr(main, "_message_gateway", None)
    monkeypatch.setattr(main, "_session_manager", object())
    monkeypatch.setattr(main, "_orchestrator", None)
    monkeypatch.setattr(channels, "MessageGateway", _FakeGateway)
    monkeypatch.setattr(
        "openkitsune.llm.config.load_endpoints_config",
        lambda: ([], [], [], {}),
    )

    dependency_checks = []
    monkeypatch.setattr(main, "_ensure_channel_deps", lambda *_args: dependency_checks.append(True))

    agent = _FakeAgent()
    assert await main.start_im_channels(agent) == []
    assert main._message_gateway is not None
    assert main._message_gateway._running is True
    assert dependency_checks == []

    adapter = SimpleNamespace(started=False)

    async def start_adapter():
        adapter.started = True

    adapter.start = start_adapter
    monkeypatch.setattr(main, "_ensure_channel_deps", lambda *_args: {})
    monkeypatch.setattr(main, "_create_bot_adapter", lambda *_args, **_kwargs: adapter)
    monkeypatch.setattr(main, "_set_im_bot_runtime_state", lambda *_args, **_kwargs: None)

    applied = await main.apply_im_bot(
        {
            "id": "primary",
            "type": "feishu",
            "agent_profile_id": "default",
            "credentials": {"app_id": "cli_test", "app_secret": "secret"},
        }
    )

    assert applied is True
    assert adapter.started is True
    assert main._message_gateway.adapters == [adapter]
