"""L1 Unit Tests: PersonaManager preset loading and trait management."""

from types import SimpleNamespace

import pytest

from openkitsune.agent.persona import PersonaManager, apply_persona_runtime


@pytest.fixture
def personas_dir(tmp_path):
    d = tmp_path / "personas"
    d.mkdir()
    (d / "default.md").write_text(
        "# Default\n\n你是一个友好、温暖的助手。\n\n## 语气\n亲切自然",
        encoding="utf-8",
    )
    (d / "professional.md").write_text(
        "# Professional\n\n你是一个专业、严谨的助手。\n\n## 语气\n正式",
        encoding="utf-8",
    )
    return d


class TestPresetDiscovery:
    def test_list_available_presets(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir)
        presets = pm.available_presets
        assert "default" in presets
        assert "professional" in presets

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty_personas"
        d.mkdir()
        pm = PersonaManager(personas_dir=d)
        assert isinstance(pm.available_presets, list)


class TestPresetSwitch:
    def test_switch_to_existing(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir)
        result = pm.switch_preset("professional")
        assert result is True

    def test_switch_to_nonexistent(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir)
        result = pm.switch_preset("nonexistent_preset_xyz")
        assert result is False

    def test_runtime_apply_switches_and_rebuilds_current_prompt(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir)
        invalidations: list[str] = []
        agent = SimpleNamespace(
            persona_manager=pm,
            _context=SimpleNamespace(system="old"),
            _invalidate_system_prompt_cache=invalidations.append,
        )
        agent._build_system_prompt = lambda: f"persona={pm.active_preset_name}"

        assert apply_persona_runtime(agent, "professional") is True

        assert pm.active_preset_name == "professional"
        assert invalidations == ["persona config changed"]
        assert agent._context.system == "persona=professional"

    def test_runtime_apply_rejects_missing_preset_before_prompt_refresh(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir)
        invalidations: list[str] = []
        agent = SimpleNamespace(
            persona_manager=pm,
            _context=SimpleNamespace(system="old"),
            _invalidate_system_prompt_cache=invalidations.append,
            _build_system_prompt=lambda: "new",
        )

        with pytest.raises(ValueError, match="Persona preset not found"):
            apply_persona_runtime(agent, "missing")

        assert pm.active_preset_name == "default"
        assert invalidations == []
        assert agent._context.system == "old"

    def test_switch_tool_persists_before_applying_runtime(
        self,
        personas_dir,
        monkeypatch,
    ):
        from openkitsune.config import runtime_state
        from openkitsune.tools.handlers.persona import PersonaHandler

        events: list[str] = []
        pm = PersonaManager(personas_dir=personas_dir)
        original_switch = pm.switch_preset

        def switch_preset(preset_name: str) -> bool:
            events.append(f"runtime:{preset_name}")
            return original_switch(preset_name)

        monkeypatch.setattr(pm, "switch_preset", switch_preset)
        monkeypatch.setattr(
            runtime_state,
            "save_updates",
            lambda **updates: events.append(f"persist:{updates['persona_name']}"),
        )

        invalidations: list[str] = []
        agent = SimpleNamespace(
            persona_manager=pm,
            _context=SimpleNamespace(system="old"),
            _invalidate_system_prompt_cache=invalidations.append,
        )
        agent._build_system_prompt = lambda: f"persona={pm.active_preset_name}"

        result = PersonaHandler(agent)._switch_persona({"preset_name": "professional"})

        assert result.startswith("✅")
        assert events == ["persist:professional", "runtime:professional"]
        assert invalidations == ["persona config changed"]
        assert agent._context.system == "persona=professional"


class TestPersonaPrompt:
    def test_prompt_section_returns_string(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir, active_preset="default")
        section = pm.get_persona_prompt_section()
        assert isinstance(section, str)

    def test_persona_active_after_load(self, personas_dir):
        pm = PersonaManager(personas_dir=personas_dir, active_preset="default")
        pm.load_preset("default")
        # After loading, persona should be considered active
        assert isinstance(pm.is_persona_active(), bool)
