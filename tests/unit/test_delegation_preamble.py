"""Tests for delegation preamble injection and preset skill fixes.

Validates:
1. Delegation preamble injected for main agent (is_sub_agent=False)
2. Delegation preamble NOT injected for sub-agents
3. Preset skills: code-reviewer fixed, brand-guidelines removed
"""

from __future__ import annotations


class TestDelegationPreambleInjection:
    """Test that the delegation preamble is correctly injected/omitted."""

    def _build_prompt(self, is_sub_agent: bool) -> str:
        """Build a system prompt with given sub_agent settings."""
        from openkitsune.config import settings
        from openkitsune.prompt.builder import build_system_prompt

        identity_dir = settings.identity_path

        return build_system_prompt(
            identity_dir=identity_dir,
            tools_enabled=True,
            is_sub_agent=is_sub_agent,
        )

    def test_preamble_present_for_main_agent(self):
        """Main agent should get delegation preamble (multi-agent always on)."""
        prompt = self._build_prompt(is_sub_agent=False)
        assert "协作优先原则" in prompt
        assert "delegate_to_agent" in prompt

    def test_preamble_absent_for_sub_agent(self):
        """Sub-agents should NOT get delegation preamble."""
        prompt = self._build_prompt(is_sub_agent=True)
        assert "协作优先原则" not in prompt

    def test_preamble_lives_in_dynamic_region_not_cached_static_prefix(self):
        """委派前言是 FULL-only 内容：必须位于 System 静态前缀（缓存区）之外。

        FULL/MINIMAL 共享同一缓存前缀（test_prompt_cache_stability 的架构不变量），
        因此前言只能注入 Runtime 动态区——不能放在身份内容之前。
        """
        from openkitsune.prompt import builder as prompt_builder

        prompt = self._build_prompt(is_sub_agent=False)
        static, _ = prompt_builder.split_static_dynamic(prompt)
        assert "协作优先原则" in prompt
        assert "协作优先原则" not in static

    def test_preamble_contains_priority_override(self):
        """Preamble must explicitly override solo-agent philosophy."""
        prompt = self._build_prompt(is_sub_agent=False)
        assert "立即委派" in prompt
        assert "才自己处理" in prompt

    def test_identity_still_present(self):
        """Identity layer should still be present even with preamble."""
        prompt = self._build_prompt(is_sub_agent=False)
        assert "协作优先原则" in prompt
        assert len(prompt) > 500


class TestPresetSkillFixes:
    """Test that preset agent skills are correctly named."""

    def test_no_code_reviewer_in_presets(self):
        from openkitsune.agents.presets import SYSTEM_PRESETS

        for p in SYSTEM_PRESETS:
            for skill in p.skills:
                assert "code-reviewer" not in skill, (
                    f"Preset {p.id} still has 'code-reviewer' (should be 'code-review')"
                )

    def test_no_brand_guidelines_in_presets(self):
        from openkitsune.agents.presets import SYSTEM_PRESETS

        for p in SYSTEM_PRESETS:
            for skill in p.skills:
                assert "brand-guidelines" not in skill, (
                    f"Preset {p.id} still has 'brand-guidelines' (doesn't exist)"
                )

    def test_code_assistant_has_code_review(self):
        from openkitsune.agents.presets import SYSTEM_PRESETS

        code_assistant = next(p for p in SYSTEM_PRESETS if p.id == "code-assistant")
        has_review = any("code-review" in s for s in code_assistant.skills)
        assert has_review, "code-assistant should have 'code-review' skill"

    def test_devops_engineer_has_code_review(self):
        from openkitsune.agents.presets import SYSTEM_PRESETS

        devops = next(p for p in SYSTEM_PRESETS if p.id == "devops-engineer")
        has_review = any("code-review" in s for s in devops.skills)
        assert has_review, "devops-engineer should have 'code-review' skill"

    def test_default_agent_has_all_skills_mode(self):
        from openkitsune.agents.presets import SYSTEM_PRESETS
        from openkitsune.agents.profile import SkillsMode

        default = next(p for p in SYSTEM_PRESETS if p.id == "default")
        assert default.skills == []
        assert default.skills_mode == SkillsMode.ALL


class TestPromptAssemblerParamPassing:
    """Test that is_sub_agent param is correctly passed through the chain."""

    def test_build_system_prompt_accepts_is_sub_agent(self):
        """build_system_prompt should accept is_sub_agent parameter."""
        import inspect

        from openkitsune.prompt.builder import build_system_prompt

        sig = inspect.signature(build_system_prompt)
        assert "is_sub_agent" in sig.parameters

    def test_assembler_compiled_accepts_is_sub_agent(self):
        """PromptAssembler methods should accept is_sub_agent."""
        import inspect

        from openkitsune.core.prompt_assembler import PromptAssembler

        for method_name in ("build_system_prompt_compiled", "_build_compiled_sync"):
            method = getattr(PromptAssembler, method_name)
            sig = inspect.signature(method)
            assert "is_sub_agent" in sig.parameters, f"{method_name} missing is_sub_agent param"
