"""Tests for OrgDelegationValidator."""

from openkitsune.agent.validators import (
    OrgDelegationValidator,
    ValidationContext,
    ValidationResult,
    create_default_registry,
)


class TestOrgDelegationValidator:
    def test_skip_when_no_signal(self):
        v = OrgDelegationValidator()
        ctx = ValidationContext(user_request="any", assistant_response="ok")
        out = v.validate(ctx)
        assert out.result == ValidationResult.SKIP

    def test_pass_with_accepted_count(self):
        v = OrgDelegationValidator()
        ctx = ValidationContext(
            user_request="any",
            assistant_response="ok",
            accepted_child_count=2,
        )
        out = v.validate(ctx)
        assert out.result == ValidationResult.PASS
        assert "2" in out.reason

    def test_pass_with_recent_signal(self):
        v = OrgDelegationValidator()
        ctx = ValidationContext(
            user_request="any",
            assistant_response="ok",
            has_recent_accepted_signal=True,
        )
        out = v.validate(ctx)
        assert out.result == ValidationResult.PASS
        assert "weak signal" in out.reason or "deliverable_accepted" in out.reason

    def test_default_registry_includes_validator(self):
        # Must be wired into the default registry so verify_task_completion
        # can use its PASS verdict.
        registry = create_default_registry()
        names = [v.name for v in registry._validators]  # type: ignore[attr-defined]
        assert "OrgDelegationValidator" in names

    def test_backward_compat_existing_context(self):
        # ValidationContext built from older code paths (no new fields) still works.
        v = OrgDelegationValidator()
        ctx = ValidationContext(
            user_request="x",
            assistant_response="y",
            executed_tools=["read_file"],
        )
        out = v.validate(ctx)
        assert out.result == ValidationResult.SKIP
