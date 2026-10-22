import json

import httpx
import pytest

from openkitsune.llm.providers.base import LLMProvider
from openkitsune.llm.providers.openai import OpenAIProvider
from openkitsune.llm.types import (
    EndpointConfig,
    LLMError,
    LLMRequest,
    LLMResponse,
    StopReason,
    Usage,
)


def _provider() -> OpenAIProvider:
    return OpenAIProvider(
        EndpointConfig(
            name="test",
            provider="openai",
            api_type="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test",
            model="gpt-test",
        )
    )


def _empty_content_response(**message_extra: object) -> dict:
    return {
        "id": "chatcmpl-test",
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": None, **message_extra},
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
    }


def test_parse_response_recovers_visible_text_from_message_output_without_reasoning():
    response = _provider()._parse_response(
        _empty_content_response(output=[{"type": "output_text", "text": "你好，我在。"}])
    )

    assert response.content[0].text == "你好，我在。"
    assert response.usage.output_tokens == 5


def test_parse_response_recovers_visible_text_from_top_level_output_with_choices():
    data = _empty_content_response()
    data["output"] = [{"type": "message", "content": [{"type": "output_text", "text": "可见回复"}]}]

    response = _provider()._parse_response(data)

    assert response.content[0].text == "可见回复"


def test_parse_response_plain_message_content_is_not_marked_lost():
    provider = _provider()

    response = provider._parse_response(
        {
            "id": "chatcmpl-test",
            "model": "gpt-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Hello from plain content"},
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
        }
    )

    assert response.content[0].text == "Hello from plain content"
    assert provider._last_raw_diagnostic is None


def test_parse_response_records_diagnostic_when_tokens_have_no_recoverable_text():
    provider = _provider()

    response = provider._parse_response(_empty_content_response())

    assert response.content == []
    assert provider._last_raw_diagnostic is not None
    assert provider._last_raw_diagnostic["usage"]["completion_tokens"] == 5


class _TokenOnlyProvider(LLMProvider):
    async def chat(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            id="resp",
            content=[],
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=1, output_tokens=2),
            model="bad-proxy",
        )

    async def chat_stream(self, request: LLMRequest):
        if False:
            yield {}


@pytest.mark.asyncio
async def test_health_check_rejects_token_only_empty_content_response():
    provider = _TokenOnlyProvider(
        EndpointConfig(
            name="token-only",
            provider="openai",
            api_type="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test",
            model="bad-proxy",
        )
    )

    assert await provider.health_check() is False
    assert provider.error_category == "structural"


@pytest.mark.asyncio
async def test_openai_redirect_request_hook_restores_authorization_header():
    provider = _provider()
    client = await provider._get_client()
    try:
        redirected_request = httpx.Request(
            "POST",
            "https://redirected.example.com/v1/chat/completions",
        )

        for hook in client.event_hooks["request"]:
            await hook(redirected_request)

        assert redirected_request.headers["Authorization"] == "Bearer sk-test"
    finally:
        await provider.close()


class _FakeStreamResponse:
    status_code = 200
    headers: dict = {}

    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamClient:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def stream(self, *args, **kwargs):
        return _FakeStreamResponse(self._lines)


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False)


def _stream_events_by_type(events: list[dict], delta_type: str) -> str:
    return "".join(
        ev["delta"].get("text") or ""
        for ev in events
        if ev.get("type") == "content_block_delta"
        and isinstance(ev.get("delta"), dict)
        and ev["delta"].get("type") == delta_type
    )


@pytest.mark.asyncio
async def test_stream_suppresses_degenerate_reasoning_output():
    provider = _provider()
    lines = [
        _sse({"choices": [{"delta": {"reasoning_content": "/"}}]}) for _ in range(40)
    ]
    lines.append(
        _sse(
            {
                "choices": [
                    {"delta": {"content": "正常回复"}, "finish_reason": "stop"}
                ]
            }
        )
    )

    async def _get_client():
        return _FakeStreamClient(lines)

    provider._get_client = _get_client
    events = [ev async for ev in provider._iter_sse_events({"stream": True, "messages": []})]

    assert _stream_events_by_type(events, "thinking") == ""
    assert _stream_events_by_type(events, "text") == "正常回复"


@pytest.mark.asyncio
async def test_stream_keeps_normal_reasoning_output():
    provider = _provider()
    lines = [
        _sse({"choices": [{"delta": {"reasoning_content": "先分析任务的耗时"}}]}),
        _sse({"choices": [{"delta": {"reasoning_content": "根因，再给出建议。"}}]}),
        _sse({"choices": [{"delta": {"content": "分析完成"}, "finish_reason": "stop"}]}),
    ]

    async def _get_client():
        return _FakeStreamClient(lines)

    provider._get_client = _get_client
    events = [ev async for ev in provider._iter_sse_events({"stream": True, "messages": []})]

    assert _stream_events_by_type(events, "thinking") == "先分析任务的耗时根因，再给出建议。"
    assert _stream_events_by_type(events, "text") == "分析完成"


@pytest.mark.asyncio
async def test_stream_suppresses_degenerate_reasoning_with_interleaved_pings():
    provider = _provider()
    lines = []
    for _ in range(40):
        lines.append(_sse({"choices": [{"delta": {"reasoning_content": "/"}}]}))
        lines.append(_sse({"choices": []}))
    lines.append(
        _sse(
            {
                "choices": [
                    {"delta": {"content": "正常回复"}, "finish_reason": "stop"}
                ]
            }
        )
    )

    async def _get_client():
        return _FakeStreamClient(lines)

    provider._get_client = _get_client
    events = [ev async for ev in provider._iter_sse_events({"stream": True, "messages": []})]

    assert _stream_events_by_type(events, "thinking") == ""
    assert _stream_events_by_type(events, "text") == "正常回复"


@pytest.mark.asyncio
async def test_stream_rejects_degenerate_text_output_with_interleaved_pings():
    provider = _provider()
    lines = []
    for _ in range(40):
        lines.append(_sse({"choices": [{"delta": {"content": "/"}}]}))
        lines.append(_sse({"choices": []}))

    async def _get_client():
        return _FakeStreamClient(lines)

    provider._get_client = _get_client
    with pytest.raises(LLMError, match="Degenerate model output"):
        _ = [ev async for ev in provider._iter_sse_events({"stream": True, "messages": []})]


@pytest.mark.asyncio
async def test_stream_passes_single_char_first_chunk_followed_by_normal_text():
    provider = _provider()
    lines = [
        _sse({"choices": [{"delta": {"content": "好"}}]}),
        _sse({"choices": [{"delta": {"content": "的呀"}}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
    ]

    async def _get_client():
        return _FakeStreamClient(lines)

    provider._get_client = _get_client
    events = [ev async for ev in provider._iter_sse_events({"stream": True, "messages": []})]

    assert _stream_events_by_type(events, "text") == "好的呀"


def test_parse_response_rejects_degenerate_text_output():
    provider = _provider()

    with pytest.raises(LLMError, match="Degenerate model output"):
        provider._parse_response(
            {
                "id": "chatcmpl-test",
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "/" * 1024},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 512, "total_tokens": 515},
            }
        )
