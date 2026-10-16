from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from openkitsune.core.policy_v2 import PolicyContext, reset_current_context, set_current_context
from openkitsune.llm.endpoint_manager import EndpointManager
from openkitsune.llm.image_generation import (
    ImageGenerationError,
    ImageGenerationResult,
    build_image_request,
    image_endpoint_url,
    load_image_endpoints,
    parse_image_response,
    request_image,
    select_image_endpoints,
)
from openkitsune.llm.types import EndpointConfig
from openkitsune.tools.handlers.system import SystemHandler


def _endpoint(**overrides) -> EndpointConfig:
    values = {
        "name": "images",
        "provider": "openai",
        "api_type": "openai_images",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "model": "gpt-image-1",
        "priority": 10,
        "capabilities": ["image_generation"],
    }
    values.update(overrides)
    return EndpointConfig(**values)


def test_image_endpoint_urls_support_base_and_full_urls() -> None:
    assert image_endpoint_url(_endpoint()) == "https://api.openai.com/v1/images/generations"
    assert (
        image_endpoint_url(
            _endpoint(base_url="https://relay.example/v1/images/generations")
        )
        == "https://relay.example/v1/images/generations"
    )
    assert image_endpoint_url(
        _endpoint(
            api_type="dashscope",
            provider="dashscope",
            base_url="https://dashscope.aliyuncs.com",
        )
    ).endswith("/api/v1/services/aigc/multimodal-generation/generation")


def test_build_openai_images_request_normalizes_options() -> None:
    endpoint = _endpoint(extra_params={"default_quality": "high"})
    body = build_image_request(
        endpoint,
        prompt="a red kite",
        negative_prompt="text",
        size="1024*1536",
    )

    assert body == {
        "model": "gpt-image-1",
        "prompt": "a red kite\nAvoid: text",
        "n": 1,
        "size": "1024x1536",
        "quality": "high",
    }


def test_build_dashscope_request_uses_native_shape() -> None:
    endpoint = _endpoint(
        provider="dashscope",
        api_type="dashscope",
        model="qwen-image-max",
        extra_params={"default_size": "1664*928"},
    )
    body = build_image_request(
        endpoint,
        prompt="山水画",
        negative_prompt="文字",
        seed=42,
        watermark=True,
    )

    assert body["model"] == "qwen-image-max"
    assert body["input"]["messages"][0]["content"] == [{"text": "山水画"}]
    assert body["parameters"] == {
        "prompt_extend": True,
        "watermark": True,
        "size": "1664*928",
        "negative_prompt": "文字",
        "seed": 42,
    }


def test_parse_openai_base64_response() -> None:
    payload = b"not-a-real-png"
    result = parse_image_response(
        _endpoint(),
        {"id": "img-1", "data": [{"b64_json": base64.b64encode(payload).decode()}]},
    )

    assert result.request_id == "img-1"
    assert result.image_bytes == payload
    assert result.image_url is None


@pytest.mark.asyncio
async def test_request_image_calls_openai_images_protocol() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/images/generations"
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "gpt-image-1"
        assert body["prompt"] == "draw a lighthouse"
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/image.png"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await request_image(client, _endpoint(), prompt="draw a lighthouse")

    assert result.endpoint_name == "images"
    assert result.image_url == "https://cdn.example/image.png"


def test_image_endpoints_are_loaded_by_priority(tmp_path) -> None:
    manager = EndpointManager(tmp_path)
    manager.save_endpoint(
        {
            "name": "backup",
            "provider": "openai",
            "api_type": "openai_images",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-image-1",
            "priority": 20,
            "capabilities": ["image_generation"],
        },
        api_key="backup-key",
        endpoint_type="image_endpoints",
    )
    manager.save_endpoint(
        {
            "name": "primary",
            "provider": "dashscope",
            "api_type": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com",
            "model": "qwen-image-max",
            "priority": 10,
            "capabilities": ["image_generation"],
        },
        api_key="primary-key",
        endpoint_type="image_endpoints",
    )

    endpoints = load_image_endpoints(tmp_path)

    assert [endpoint.name for endpoint in endpoints] == ["primary", "backup"]
    assert [endpoint.name for endpoint in select_image_endpoints(endpoints, "backup")] == [
        "backup"
    ]


@pytest.mark.asyncio
async def test_generate_image_falls_back_and_saves_base64_result(tmp_path, monkeypatch) -> None:
    primary = _endpoint(name="primary", priority=10)
    backup = _endpoint(name="backup", priority=20)

    async def fake_request(_client, endpoint, **_kwargs):
        if endpoint.name == "primary":
            raise ImageGenerationError("temporary provider failure")
        return ImageGenerationResult(
            endpoint_name="backup",
            model="gpt-image-1",
            request_id="img-fallback",
            image_bytes=b"png-bytes",
        )

    monkeypatch.setattr(
        "openkitsune.llm.image_generation.load_image_endpoints",
        lambda _workspace: [primary, backup],
    )
    monkeypatch.setattr("openkitsune.llm.image_generation.request_image", fake_request)

    context = PolicyContext(
        session_id="image-generation-test",
        working_directory=tmp_path,
        workspace_roots=(tmp_path,),
    )
    token = set_current_context(context)
    try:
        result = json.loads(
            await SystemHandler(SimpleNamespace()).handle(
                "generate_image", {"prompt": "fallback test"}
            )
        )
    finally:
        reset_current_context(token)

    assert result["ok"] is True
    assert result["endpoint"] == "backup"
    saved_path = Path(result["saved_to"])
    assert saved_path == (tmp_path / "gpt-image-1_img-fallback.png").resolve()
    assert saved_path.read_bytes() == b"png-bytes"
