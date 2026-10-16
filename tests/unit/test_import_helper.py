from unittest.mock import patch

from openkitsune.tools._import_helper import _PACKAGE_MODULE_MAP, _build_hint, import_or_hint


def test_optional_and_core_packages_have_the_expected_module_mapping():
    expected = {
        "sentence_transformers": "vector-memory",
        "chromadb": "vector-memory",
        "whisper": "whisper",
        "static_ffmpeg": "whisper",
        "playwright": None,
    }

    assert {name: _PACKAGE_MODULE_MAP[name][0] for name in expected} == expected


def test_import_or_hint_returns_none_for_an_available_module():
    assert import_or_hint("os") is None


def test_import_or_hint_returns_a_pip_hint_for_an_unknown_missing_module():
    hint = import_or_hint("__nonexistent_package_xyz__")

    assert hint is not None
    assert "pip install" in hint


def test_frozen_optional_module_hint_mentions_setup_center():
    with patch("openkitsune.tools._import_helper.IS_FROZEN", True):
        hint = _build_hint("sentence_transformers")

    assert "设置中心" in hint
    assert "向量记忆增强" in hint


def test_frozen_core_package_hint_mentions_reinstall():
    with patch("openkitsune.tools._import_helper.IS_FROZEN", True):
        assert "重新安装" in _build_hint("playwright")


def test_development_hint_names_the_pip_package():
    with patch("openkitsune.tools._import_helper.IS_FROZEN", False):
        hint = _build_hint("sentence_transformers")

    assert "pip install" in hint
    assert "sentence-transformers" in hint
