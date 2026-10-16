from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_identity_write_preserves_success_when_runtime_refresh_fails(
    tmp_path, monkeypatch
) -> None:
    from openkitsune.api.routes import identity
    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    result = RuntimeApplyResult(failed={"identity": "compiler unavailable"})
    coordinator = SimpleNamespace(refresh_identity=lambda *_args, **_kwargs: result)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(runtime_config_coordinator=coordinator))
    )
    monkeypatch.setattr(identity, "_identity_dir", lambda: tmp_path)

    response = await identity.write_identity_file(
        identity.FileWriteRequest(name="SOUL.md", content="# Persisted identity"),
        request,
    )

    assert response["saved"] is True
    assert response["operation_status"] == "ok"
    assert response["status"] == "failed"
    assert response["runtime"]["failed"]["identity"] == "compiler unavailable"
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "# Persisted identity"


@pytest.mark.asyncio
async def test_manual_compile_uses_coordinator_prompt_rebuild(tmp_path, monkeypatch) -> None:
    from openkitsune.api.routes import identity
    from openkitsune.runtime_config_coordinator import RuntimeApplyResult

    calls: list[str] = []
    runtime = RuntimeApplyResult(refreshed=["global_agent_prompt"])
    coordinator = SimpleNamespace(
        rebuild_agent_prompt=lambda: calls.append("rebuild") or runtime,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(runtime_config_coordinator=coordinator))
    )
    monkeypatch.setattr(identity, "_identity_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "openkitsune.prompt.compiler.compile_all",
        lambda path: calls.append(f"compile:{path}"),
    )
    monkeypatch.setattr("openkitsune.prompt.compiler.get_compiled_content", lambda _path: {})

    response = await identity.compile_identity(request, mode="rules")

    assert calls == [f"compile:{tmp_path}", "rebuild"]
    assert response["status"] == "ok"
    assert response["runtime"]["refreshed"] == ["global_agent_prompt"]
