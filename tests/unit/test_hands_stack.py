"""openkitsune-hands 网络爪牙伴随启动与 Provider 测试。

覆盖：
- 环境变量解析（开关 / 地址 / 超时 / 工程目录）；
- 二进制 release→debug 回退与子进程环境构造；
- 总开关关闭、二进制缺失、端口已占用时的降级路径；
- Provider 在 web_search registry 中的注册与响应解析。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openkitsune.tools.web_search import hands_stack
from openkitsune.tools.web_search.hands_stack import (
    DEFAULT_HANDS_URL,
    HandsConfig,
    HandsSupervisor,
    build_hands_env,
    resolve_hands_binary,
    resolve_hands_home,
    resolve_hands_url,
)
from openkitsune.tools.web_search.providers.hands import HandsProvider, _parse_results


def _config(home: Path, **overrides) -> HandsConfig:
    values = {"home": home}
    values.update(overrides)
    return HandsConfig(**values)


def test_env_overrides(tmp_path: Path) -> None:
    env = {
        "OPENKITSUNE_HANDS_HOME": str(tmp_path),
        "OPENKITSUNE_HANDS_URL": "http://127.0.0.1:9320/",
        "OPENKITSUNE_HANDS_AUTOSTART": "0",
        "OPENKITSUNE_HANDS_STOP_ON_EXIT": "off",
        "OPENKITSUNE_HANDS_HEALTH_TIMEOUT": "8.5",
    }
    config = HandsConfig.from_env(env)

    assert config.home == tmp_path
    assert config.url == "http://127.0.0.1:9320"
    assert config.host == "127.0.0.1"
    assert config.port == 9320
    assert config.autostart is False
    assert config.stop_on_exit is False
    assert config.health_timeout_s == pytest.approx(8.5)


def test_url_default_and_normalization() -> None:
    assert resolve_hands_url({}) == DEFAULT_HANDS_URL
    assert resolve_hands_url({"OPENKITSUNE_HANDS_URL": "http://localhost:8320/"}) == (
        "http://localhost:8320"
    )


def test_home_prefers_existing_project(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]", encoding="utf-8")

    assert resolve_hands_home({"OPENKITSUNE_HANDS_HOME": str(tmp_path)}) == tmp_path


def test_binary_prefers_release_then_debug(tmp_path: Path) -> None:
    config = _config(tmp_path)
    binary_name = hands_stack._BINARY_NAMES[0]
    debug_bin = tmp_path / "target" / "debug" / binary_name
    debug_bin.parent.mkdir(parents=True)
    debug_bin.write_text("", encoding="utf-8")

    assert resolve_hands_binary(config) == debug_bin

    release_bin = tmp_path / "target" / "release" / binary_name
    release_bin.parent.mkdir(parents=True)
    release_bin.write_text("", encoding="utf-8")

    assert resolve_hands_binary(config) == release_bin


def test_binary_missing_returns_none(tmp_path: Path) -> None:
    assert resolve_hands_binary(_config(tmp_path)) is None


def test_build_env_sets_config_and_bind(tmp_path: Path) -> None:
    env = build_hands_env(_config(tmp_path, url="http://127.0.0.1:9320"), base={})

    assert env["NX_CONFIG"] == str(tmp_path / "config.yaml")
    assert env["NX_BIND"] == "127.0.0.1:9320"
    assert env["RUST_LOG"] == "info"


def test_autostart_disabled_never_spawns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when autostart is disabled")

    monkeypatch.setattr(hands_stack.subprocess, "Popen", _fail)
    supervisor = HandsSupervisor(_config(tmp_path, autostart=False))

    status = supervisor.start()

    assert status["enabled"] is False
    assert status["owned"] is False


def test_missing_binary_degrades(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hands_stack, "service_reachable", lambda *_args, **_kwargs: False)

    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when binary is missing")

    monkeypatch.setattr(hands_stack.subprocess, "Popen", _fail)
    supervisor = HandsSupervisor(_config(tmp_path))

    status = supervisor.start()

    assert status["health"] == "missing-binary"
    supervisor.stop(force=True)


def test_existing_service_is_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hands_stack, "service_reachable", lambda *_args, **_kwargs: True)

    def _fail(*_args, **_kwargs):
        raise AssertionError("Popen must not be called when the port is already served")

    monkeypatch.setattr(hands_stack.subprocess, "Popen", _fail)
    supervisor = HandsSupervisor(_config(tmp_path, health_timeout_s=0.1))

    status = supervisor.start()

    assert status["external"] is True
    assert status["owned"] is False
    supervisor.stop(force=True)


def test_provider_is_registered_and_prioritized() -> None:
    from openkitsune.tools.web_search.registry import get_provider, iter_providers

    provider = get_provider("hands")
    assert provider is not None
    assert provider.auto_detect_order < 10  # 优先于需要 Key 的源

    ids = [p.id for p in iter_providers()]
    assert "hands" in ids


def test_provider_parses_camel_case_response() -> None:
    data = {
        "query": "河图洛书",
        "provider": "searxng",
        "hits": [
            {
                "title": "河图洛书概述",
                "url": "https://example.com/a",
                "snippet": "摘要",
                "source": "wikipedia",
                "publishedDate": "2026-01-02",
            }
        ],
    }

    results = _parse_results(data, max_results=5)

    assert len(results) == 1
    assert results[0].title == "河图洛书概述"
    assert results[0].snippet == "摘要"
    assert results[0].source == "wikipedia"
    assert results[0].date == "2026-01-02"


def test_provider_falls_back_to_infobox() -> None:
    data = {
        "hits": [],
        "infobox": {
            "infoboxType": "wikipedia",
            "title": "九尾狐",
            "content": "中国古代神话中的生物。",
            "url": "https://example.com/fox",
        },
    }

    results = _parse_results(data, max_results=5)

    assert len(results) == 1
    assert results[0].title == "九尾狐"
    assert results[0].url == "https://example.com/fox"


async def test_provider_news_search_defers() -> None:
    assert await HandsProvider().news_search("新闻") is None
