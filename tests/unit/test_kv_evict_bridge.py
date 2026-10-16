"""KV 驱逐桥接测试：attach_kv_evict_callback 的成功/禁用/失败降级路径。"""

import sys
from pathlib import Path

import pytest

from openkitsune.integrations.kv_evict import attach_kv_evict_callback


class _FakeCM:
    def __init__(self):
        self.kv_cache_evict_callback = None


class _FakeSettings:
    def __init__(self, **kw):
        self.__dict__.update(
            {
                "kv_evict_llamacpp_enabled": True,
                "kv_evict_llamacpp_adapter_path": "",
                "kv_evict_llamacpp_base_url": "http://127.0.0.1:8220",
                "kv_evict_llamacpp_manager_url": "http://127.0.0.1:8240",
                "kv_evict_llamacpp_model_id": "test-model",
                "kv_evict_llamacpp_restart_threshold": 0.5,
                "kv_evict_llamacpp_restart_cooldown_seconds": 600,
                "kv_evict_llamacpp_enable_restart": True,
                "kv_evict_llamacpp_log_dir": "",
            }
        )
        self.__dict__.update(kw)


def test_disabled_returns_false(tmp_path: Path) -> None:
    settings = _FakeSettings(kv_evict_llamacpp_enabled=False)
    cm = _FakeCM()
    assert attach_kv_evict_callback(cm, settings) is False
    assert cm.kv_cache_evict_callback is None


def test_missing_adapter_path_returns_false() -> None:
    settings = _FakeSettings(kv_evict_llamacpp_adapter_path="")
    cm = _FakeCM()
    assert attach_kv_evict_callback(cm, settings) is False
    assert cm.kv_cache_evict_callback is None


def test_invalid_adapter_path_degrades_quietly(tmp_path: Path) -> None:
    settings = _FakeSettings(kv_evict_llamacpp_adapter_path=str(tmp_path / "nope"))
    cm = _FakeCM()
    # 无效路径绝不抛错，仅返回 False
    assert attach_kv_evict_callback(cm, settings) is False
    assert cm.kv_cache_evict_callback is None


def test_attach_success_with_stub_adapter(tmp_path: Path, monkeypatch) -> None:
    stub_dir = tmp_path / "adapter"
    stub_dir.mkdir()
    (stub_dir / "kv_evict_llamacpp.py").write_text(
        "class LlamaCppKvEvictor:\n"
        "    def __init__(self, **kw):\n"
        "        self.model_id = kw.get('model_id')\n"
        "        self.base_url = kw.get('base_url')\n"
        "        self.enable_gap_pause = kw.get('enable_gap_pause', False)\n"
        "    def evict(self, payload):\n"
        "        return {'ok': True, 'action': 'cache_prompt_false'}\n",
        encoding="utf-8",
    )
    settings = _FakeSettings(kv_evict_llamacpp_adapter_path=str(stub_dir))
    cm = _FakeCM()
    assert attach_kv_evict_callback(cm, settings) is True
    assert cm.kv_cache_evict_callback is not None
    assert cm.kv_cache_evict_callback({"spans": [], "messages": []})["action"] == "cache_prompt_false"
