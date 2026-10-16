"""Provider adapters and endpoint resolution for text-to-image generation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from .endpoint_manager import EndpointManager
from .types import EndpointConfig

SUPPORTED_IMAGE_API_TYPES = {"dashscope", "openai_images"}


class ImageGenerationError(RuntimeError):
    """An image provider returned an unusable response."""


@dataclass(frozen=True)
class ImageGenerationResult:
    endpoint_name: str
    model: str
    request_id: str | None = None
    image_url: str | None = None
    image_bytes: bytes | None = None


def load_image_endpoints(workspace_dir: str | Path) -> list[EndpointConfig]:
    """Load enabled image endpoints in priority order."""
    manager = EndpointManager(Path(workspace_dir))
    endpoints: list[EndpointConfig] = []
    for raw in manager.list_endpoints("image_endpoints"):
        if raw.get("enabled", True) is False:
            continue
        try:
            endpoint = EndpointConfig.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if endpoint.api_type.strip().lower() not in SUPPORTED_IMAGE_API_TYPES:
            continue
        endpoints.append(endpoint)
    endpoints.sort(key=lambda item: (item.priority, item.name))
    return endpoints


def select_image_endpoints(
    endpoints: list[EndpointConfig], requested_name: str = ""
) -> list[EndpointConfig]:
    """Return the requested endpoint or the full priority-sorted fallback chain."""
    requested = requested_name.strip().lower()
    if not requested:
        return endpoints
    selected = [item for item in endpoints if item.name.strip().lower() == requested]
    if not selected:
        available = ", ".join(item.name for item in endpoints) or "none"
        raise ImageGenerationError(
            f"Image endpoint {requested_name!r} was not found (available: {available})"
        )
    return selected


def _append_path(base_url: str, suffix: str) -> str:
    """Append a protocol path while preserving query strings (notably Azure api-version)."""
    parts = urlsplit(base_url.strip())
    path = parts.path.rstrip("/")
    if not path.endswith(suffix):
        path = f"{path}{suffix}"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def image_endpoint_url(endpoint: EndpointConfig) -> str:
    api_type = endpoint.api_type.strip().lower()
    if api_type == "dashscope":
        suffix = "/api/v1/services/aigc/multimodal-generation/generation"
        return _append_path(endpoint.base_url, suffix)
    if api_type == "openai_images":
        return _append_path(endpoint.base_url, "/images/generations")
    raise ImageGenerationError(f"Unsupported image API type: {endpoint.api_type}")


def _request_overrides(endpoint: EndpointConfig) -> dict:
    extra = endpoint.extra_params or {}
    value = extra.get("request_params", {})
    return dict(value) if isinstance(value, dict) else {}


def _effective_option(endpoint: EndpointConfig, name: str, provided, fallback):
    if provided not in (None, ""):
        return provided
    extra = endpoint.extra_params or {}
    return extra.get(f"default_{name}", fallback)


def build_image_request(
    endpoint: EndpointConfig,
    *,
    prompt: str,
    model: str = "",
    negative_prompt: str = "",
    size: str = "",
    quality: str = "",
    style: str = "",
    seed: int | None = None,
    prompt_extend: bool = True,
    watermark: bool = False,
) -> dict:
    """Build a provider-specific request body from the unified tool arguments."""
    api_type = endpoint.api_type.strip().lower()
    effective_model = model.strip() or endpoint.model
    effective_size = str(_effective_option(endpoint, "size", size, "1024x1024"))

    if api_type == "dashscope":
        body: dict = {
            "model": effective_model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": {
                "prompt_extend": bool(prompt_extend),
                "watermark": bool(watermark),
                "size": effective_size.replace("x", "*"),
            },
        }
        if negative_prompt:
            body["parameters"]["negative_prompt"] = negative_prompt
        if seed is not None:
            body["parameters"]["seed"] = int(seed)
        body.update(_request_overrides(endpoint))
        return body

    if api_type == "openai_images":
        effective_prompt = prompt
        if negative_prompt:
            effective_prompt = f"{prompt}\nAvoid: {negative_prompt}"
        body = {
            "model": effective_model,
            "prompt": effective_prompt,
            "n": 1,
            "size": effective_size.replace("*", "x"),
        }
        effective_quality = str(_effective_option(endpoint, "quality", quality, ""))
        effective_style = str(_effective_option(endpoint, "style", style, ""))
        if effective_quality:
            body["quality"] = effective_quality
        if effective_style:
            body["style"] = effective_style
        body.update(_request_overrides(endpoint))
        return body

    raise ImageGenerationError(f"Unsupported image API type: {endpoint.api_type}")


def parse_image_response(endpoint: EndpointConfig, data: dict) -> ImageGenerationResult:
    """Normalize DashScope and OpenAI Images responses."""
    api_type = endpoint.api_type.strip().lower()
    request_id = data.get("request_id") or data.get("requestId") or data.get("id")

    if api_type == "dashscope":
        try:
            image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
        except (KeyError, IndexError, TypeError) as exc:
            code = data.get("code")
            message = data.get("message")
            raise ImageGenerationError(
                f"DashScope response did not contain an image (code={code}, message={message})"
            ) from exc
        return ImageGenerationResult(
            endpoint_name=endpoint.name,
            model=endpoint.model,
            request_id=str(request_id) if request_id else None,
            image_url=str(image_url),
        )

    if api_type == "openai_images":
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageGenerationError("OpenAI Images response did not contain data[0]") from exc
        image_url = item.get("url") if isinstance(item, dict) else None
        image_b64 = item.get("b64_json") if isinstance(item, dict) else None
        if image_url:
            return ImageGenerationResult(
                endpoint_name=endpoint.name,
                model=endpoint.model,
                request_id=str(request_id) if request_id else None,
                image_url=str(image_url),
            )
        if image_b64:
            try:
                decoded = base64.b64decode(image_b64, validate=True)
            except (ValueError, TypeError) as exc:
                raise ImageGenerationError("OpenAI Images returned invalid base64 data") from exc
            return ImageGenerationResult(
                endpoint_name=endpoint.name,
                model=endpoint.model,
                request_id=str(request_id) if request_id else None,
                image_bytes=decoded,
            )
        raise ImageGenerationError("OpenAI Images response contained neither url nor b64_json")

    raise ImageGenerationError(f"Unsupported image API type: {endpoint.api_type}")


async def request_image(
    client: httpx.AsyncClient,
    endpoint: EndpointConfig,
    **kwargs,
) -> ImageGenerationResult:
    """Call one configured image endpoint and normalize its response."""
    api_key = (endpoint.get_api_key() or "").strip()
    if not api_key:
        raise ImageGenerationError(
            f"API key is missing for image endpoint {endpoint.name!r} ({endpoint.api_key_env or 'no env var'})"
        )
    response = await client.post(
        image_endpoint_url(endpoint),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=build_image_request(endpoint, **kwargs),
        timeout=max(1, endpoint.timeout),
    )
    if response.status_code >= 400:
        raise ImageGenerationError(
            f"{endpoint.name}: HTTP {response.status_code}: {(response.text or '')[:800]}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ImageGenerationError(
            f"{endpoint.name}: provider returned non-JSON: {(response.text or '')[:800]}"
        ) from exc
    if not isinstance(data, dict):
        raise ImageGenerationError(f"{endpoint.name}: provider returned a non-object JSON response")
    result = parse_image_response(endpoint, data)
    effective_model = str(kwargs.get("model") or endpoint.model)
    return ImageGenerationResult(
        endpoint_name=result.endpoint_name,
        model=effective_model,
        request_id=result.request_id,
        image_url=result.image_url,
        image_bytes=result.image_bytes,
    )
