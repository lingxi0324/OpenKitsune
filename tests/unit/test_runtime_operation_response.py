from openkitsune.api.runtime_response import runtime_operation_response
from openkitsune.runtime_config_coordinator import RuntimeApplyResult


def test_runtime_operation_response_preserves_payload_and_owns_contract_fields() -> None:
    runtime = RuntimeApplyResult(failed={"agent_pool": "unavailable"})

    response = runtime_operation_response(
        runtime,
        {
            "status": "legacy",
            "operation_status": "connected",
            "runtime": {"status": "legacy"},
            "connection_status": "connected",
            "server": "demo",
        },
    )

    assert response["status"] == "failed"
    assert response["operation_status"] == "ok"
    assert response["runtime"]["failed"] == {"agent_pool": "unavailable"}
    assert response["connection_status"] == "connected"
    assert response["server"] == "demo"


def test_runtime_operation_response_supports_enveloped_apis() -> None:
    runtime = RuntimeApplyResult(refreshed=["plugin_instance"])

    response = runtime_operation_response(runtime, {"data": {"id": "demo"}}, ok=True)

    assert response == {
        "ok": True,
        "status": "ok",
        "operation_status": "ok",
        "data": {"id": "demo"},
        "runtime": runtime.to_dict(),
    }
