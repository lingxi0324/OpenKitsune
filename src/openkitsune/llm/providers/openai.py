"""
OpenAI Provider

支持 OpenAI API 格式的调用，包括：
- OpenAI 官方 API
- DashScope（通义千问）
- Kimi（Moonshot AI）
- OpenRouter
- 硅基流动
- 云雾 API
- 其他 OpenAI 兼容 API
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from json import JSONDecodeError

import httpx

from ..cache import build_cached_system_blocks
from ..converters.messages import convert_messages_to_openai
from ..converters.tools import (
    convert_tool_calls_from_openai,
    convert_tools_to_openai,
    has_text_tool_calls,
    parse_text_tool_calls,
)
from ..model_registry import get_model_capabilities, resolve_output_token_budget
from ..thinking import (
    is_minimax_endpoint,
    minimax_thinking_depth,
    normalize_thinking_depth,
    reasoning_effort_for_depth,
    thinking_budget_for_depth,
)
from ..types import (
    AuthenticationError,
    EndpointConfig,
    LLMError,
    LLMRequest,
    LLMResponse,
    RateLimitError,
    StopReason,
    TextBlock,
    ToolUseBlock,
    Usage,
    normalize_base_url,
)
from .base import LLMProvider
from .proxy_utils import (
    build_httpx_timeout,
    get_httpx_transport,
    get_proxy_config,
    should_bypass_proxy,
)

logger = logging.getLogger(__name__)


# Remote streaming requests should fail over promptly when the upstream sends no
# data. Non-streaming calls retain their configured/dynamic timeout, while local
# inference keeps its longer timeout because slow first tokens are expected.
REMOTE_STREAM_READ_TIMEOUT_CAP_SECONDS = 90.0

# 连接被对端中断（服务端进程崩溃/被强杀/网关关闭连接）的识别关键字。
# 这类错误与超时、普通 HTTP 错误不同：上游（如本地 model-manager 网关背后
# 的 llama-server）通常会由服务管理自动拉起，值得在首块到达前做一次同端点
# 原地重试，避免把瞬时崩溃误判为端点永久不可用。
_CONNECTION_CLOSED_KEYWORDS = (
    "closed connection",
    "incomplete chunked",
    "peer closed",
    "remote protocol",
    "connection reset",
    "connection aborted",
    "connection closed",
    "broken pipe",
    "server disconnected",
    "unexpected eof",
    "unexpected end",
    "eof",
    "connection lost",
    "stream ended",
    "chunked read",
)


def _is_connection_closed_error(exc: Exception) -> bool:
    """判断异常是否为对端中断连接（区别于超时/普通网络不可达）。

    覆盖 httpx 的 RemoteProtocolError / ConnectError / ReadError / NetworkError，
    以及上游错误消息中的连接关闭关键字。
    """
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in _CONNECTION_CLOSED_KEYWORDS)


def _parse_openai_usage(data: dict) -> dict[str, int]:
    """Keep total input tokens and cache subsets consistent across response paths."""

    def count(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    details = data.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    if "prompt_cache_hit_tokens" in data:
        cached = count(data["prompt_cache_hit_tokens"])
    else:
        cached = count(details.get("cached_tokens")) or count(data.get("cached_tokens"))
    total_input = count(data.get("prompt_tokens"))
    if "prompt_tokens" not in data and "prompt_cache_miss_tokens" in data:
        total_input = cached + count(data["prompt_cache_miss_tokens"])
    return {
        "input_tokens": total_input,
        "output_tokens": count(data.get("completion_tokens")),
        "cache_read_input_tokens": min(cached, total_input),
        "cache_creation_input_tokens": count(details.get("cache_creation_input_tokens")),
    }


def _safe_dig(data: object, *keys: str) -> object:
    """Walk nested dicts safely; returns ``None`` if any key is missing."""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


def _extract_reasoning_delta(value: object) -> str:
    """Best-effort extraction for reasoning deltas from OpenAI-compatible gateways."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_reasoning_delta(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "text",
            "delta",
            "content",
            "reasoning",
            "reasoning_content",
            "thinking",
            "summary_text",
        ):
            if key in value:
                extracted = _extract_reasoning_delta(value.get(key))
                if extracted:
                    return extracted
    return ""


def _is_stream_only_error(error: str) -> bool:
    """检测错误是否表明端点仅支持流式请求（stream-only relay/中转站）。"""
    err_lower = error.lower()
    return (
        "stream must be set to true" in err_lower
        or "stream is required" in err_lower
        or ("text/event-stream" in err_lower and "invalid json" in err_lower)
    )


def _is_empty_response_error(error: str) -> bool:
    """检测错误是否为非流式空响应（可能流式模式能正常返回内容）。

    仅匹配 _chat_non_stream 产生的 "choices/output 为空" 错误，
    不匹配流式路径的空响应错误。
    """
    err_lower = error.lower()
    if "stream" in err_lower:
        return False
    return "empty response" in err_lower or "no choices" in err_lower or "no output" in err_lower


def _humanize_upstream_error(status: int, body: str) -> str:
    """把云端 LLM 的英文错误转成对小白用户更友好的中文摘要。

    原始 body 仍会通过 logger.error 留档以便排查；这里只控制传播给用户那条
    LLMError 的 message。完全找不到匹配时回退到一个通用 HTTP 提示。

    例外：如果是 stream-only relay（"stream must be set to true" 等），
    必须保留原文，以便 chat() 的 except 分支识别后自动切到流式重试。
    """
    if _is_stream_only_error(body or ""):
        return body or f"API error ({status})"
    body_l = (body or "").lower()

    # 内容安全审核（DashScope DataInspectionFailed / OpenAI moderation /
    # 国内云模型绿网拦截等）。返回字符串中必须保留 data_inspection_failed
    # 关键字，下游 errors.classify_error / reasoning_engine 方案 D /
    # 前端 chatHelpers.classifyError 共同依赖此关键字判定 content_filter。
    if (
        "data_inspection" in body_l
        or "datainspectionfailed" in body_l
        or "inappropriate content" in body_l
        or "content_filter" in body_l
    ):
        return (
            f"云端模型的内容安全审核未通过 (HTTP {status}, data_inspection_failed)。"
            "请尝试换一种表述、清空对话上下文，或切换到对内容审核更宽松的模型端点。"
        )

    if "invalidparameter" in body_l and (
        "url" in body_l or "image" in body_l or "vision" in body_l
    ):
        return "云端模型未能访问到您发送的图片（图片需可公网访问或采用内嵌方式），请稍后重试或更换更小的图片"
    if "appidnoautherror" in body_l or 'code":11200' in body_l or 'code":"11200' in body_l:
        return (
            "讯飞模型授权或额度异常 (xfyun_auth_or_quota, AppIdNoAuthError/code 11200)。"
            "请检查 Coding Plan 订阅、模型权限和当日用量。"
        )
    if status == 401 or "authenticationerror" in body_l or "invalid api key" in body_l:
        return "API Key 无效或已过期，请到设置中心检查模型端点凭据"
    if status == 429 or "rate limit" in body_l:
        return "调用频率已超过上游限制，请稍后再试"
    if (
        status == 402
        or "insufficientquota" in body_l
        or "insufficient_quota" in body_l
        or "balance" in body_l
    ):
        return "云端账户余额不足或额度已用尽 (quota_exhausted)，请充值后再继续使用"
    if status == 408 or "timeout" in body_l:
        return "云端响应超时，请稍后重试或换个模型"
    if status == 404 or "modelnotfound" in body_l or "model not found" in body_l:
        return "目标模型不存在或当前账号无权限调用该模型"
    if status >= 500:
        return f"云端服务暂时不可用 (HTTP {status})，请稍后重试"
    return f"云端模型调用失败 (HTTP {status})"


def _extract_retry_after_seconds(body: str, headers=None) -> float | None:
    """从 429/503 响应提取上游建议的重试等待秒数。

    本地 model-manager 的 503 把 retry_after_sec 放在 JSON body 内
    （{"error":{...,"retry_after_sec":3}}），OpenAI 兼容网关也可能放在
    Retry-After 头。两者都尝试；body 内字段优先（头部格式见 retry.py
    parse_retry_after，这里统一解析以覆盖两种形态）。
    """
    if body:
        m = re.search(r'"retry_after_sec"\s*:\s*(\d+(?:\.\d+)?)', body)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        m2 = re.search(
            r"retry[-_]after[\"'\s:=]+(\d+(?:\.\d+)?)", body, flags=re.IGNORECASE
        )
        if m2:
            try:
                return float(m2.group(1))
            except ValueError:
                pass
    if headers:
        for key in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
            value = headers.get(key)
            if value:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    continue
    return None


def _is_model_loading_503(status: int, body: str) -> bool:
    """判断是否为本地模型冷启动/显存协调期间的瞬时 503。

    model-manager 在 llama-server 加载模型期间返回
    type=model_loading / model_suppressed，加载完成即自动恢复，
    适合在 provider 内做有限等待重试；其余 503 交 client 层退避处理。
    """
    if status != 503 or not body:
        return False
    body_l = body.lower()
    return (
        "model_loading" in body_l
        or "model_suppressed" in body_l
        or "loading model" in body_l
        or "正在加载" in body_l
        or "恢复中" in body_l
    )


# 本地 llama 冷启动横幅的最大重试等待时长（秒）：35B 模型加载约 10~60s，
# 按上游 retry_after_sec=3 轮询，最多等 ~30s；仍未就绪则交给 client 层。
_MODEL_LOADING_MAX_WAIT_SECONDS = 30.0


def _looks_like_llama_banner(text: str) -> bool:
    """判断文本是否为 llama.cpp server/cli 启动横幅（非模型回复）。

    冷启动时 llama-server/llama-cli 的 stdout 横幅会被 model-manager
    原样透出，特征是包含 "Loading model..." 进度、版本 build 信息、
    "available commands" / "/exit or Ctrl+C" 等交互提示。
    """
    if not text:
        return False
    tl = text.lower()
    if "loading model" in tl:
        return True
    if "available commands" in tl and ("/exit" in tl or "/regen" in tl):
        return True
    if ("llama-server" in tl or "llama.cpp" in tl) and "build" in tl:
        return True
    if "modalities" in tl and ("ftype" in tl or "commands" in tl):
        return True
    return False


def _sanitize_local_llama_output(text: str) -> str:
    """清洗 model-manager 本地 llama 冷启动输出中的横幅/回显垃圾。

    冷启动（NativeLlamaProvider / llama-cli 或刚拉起的 llama-server）可能把
    启动横幅 + 提示词回显混进响应，典型形态：
      "Loading model...▄▄ ▄▄██ ... build : b10488-... ftype : ...
       available commands: ... > <|im_start|>system## System...<|im_start|>assistant 真实回复"

    处理：
    1. ChatML 提示词回显 → 截取最后一个 "<|im_start|>assistant" 之后的真实生成内容；
    2. 无 assistant 标记 → 仅剥离横幅段（Loading model / build / model / ftype /
       modalities / available commands / 交互帮助行 / "> " 提示符）；
    3. 都不是 → 原样返回。
    """
    if not text:
        return text

    # 1) ChatML 提示词回显：最后 "<|im_start|>assistant" 之后才是真实生成
    marker = "<|im_start|>assistant"
    if marker in text:
        idx = text.rfind(marker)
        tail = text[idx + len(marker):].lstrip("\n\r ")
        for end in ("<|im_end|>", "<|endoftext|>", "<end_of_turn>", "<|eot_id|>"):
            if tail.endswith(end):
                tail = tail[: -len(end)].rstrip()
        if tail.strip():
            return tail.strip()

    # 2) 无 ChatML 回显：剥离横幅段
    low = text.lower()
    if "loading model" in low or "available commands" in low:
        banner_end = None
        if "available commands" in low:
            seg = text[low.find("available commands"):]
            m = re.search(r">\s*", seg)
            if m:
                banner_end = low.find("available commands") + m.end()
        if banner_end is not None:
            tail = text[banner_end:].strip()
            return tail
        # 找不到交互提示符：按行过滤横幅行
        _BANNER_PREFIXES = (
            "loading model",
            "build",
            "model",
            "ftype",
            "modalities",
            "available commands",
            "stop or exit",
            "/regen",
            "/clear",
            "/read",
            "/glob",
            "system_info:",
            "main:",
            "llama_model_loader:",
            "print_info:",
            "load_tensors:",
            "llama_init_from_gpt_params:",
        )
        lines = text.splitlines()
        kept = []
        for ln in lines:
            ll = ln.lower().strip()
            if not ll or ll == ">" or ll.startswith(_BANNER_PREFIXES):
                continue
            kept.append(ln)
        return "\n".join(kept).strip()

    return text.strip()


class _BearerAuth(httpx.Auth):
    """Bearer token auth that persists across cross-origin redirects.

    httpx strips the Authorization header on cross-origin redirects for security.
    Some OpenAI-compatible gateways (e.g., GitCode api-ai) internally redirect to
    a different host, causing the token to be lost and a 401 response.
    Using httpx's auth mechanism re-attaches credentials after every redirect.
    """

    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 API Provider"""

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None
        self._client_loop_id: int | None = None  # 记录创建客户端时的事件循环 ID
        self._stream_only: bool = config.stream_only
        self._last_raw_diagnostic: dict | None = None

    @property
    def api_key(self) -> str:
        """获取 API Key"""
        return self.config.get_api_key() or ""

    @property
    def base_url(self) -> str:
        """获取 base URL，自动剥离用户误粘贴的 OpenAI 兼容端点路径后缀。"""
        return normalize_base_url(self.config.base_url)

    @property
    def _api_url(self) -> str:
        """完整 API 端点 URL，子类可覆写以切换协议（如 Responses API）。"""
        return f"{self.base_url}/chat/completions"

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端

        注意：httpx.AsyncClient 绑定到创建时的事件循环。
        如果事件循环变化（如定时任务创建新循环），需要重新创建客户端。
        """
        import asyncio

        try:
            current_loop = asyncio.get_running_loop()
            current_loop_id = id(current_loop)
        except RuntimeError:
            current_loop_id = None

        # 检查是否需要重新创建客户端
        need_recreate = (
            self._client is None
            or self._client.is_closed
            or self._client_loop_id != current_loop_id
        )

        if need_recreate:
            # 安全关闭旧客户端
            if self._client is not None and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception:
                    pass  # 忽略关闭错误

            # 获取代理和网络配置
            proxy = get_proxy_config()
            transport = get_httpx_transport()  # IPv4-only 支持
            is_local = self._is_local_endpoint()

            # 本地端点（Ollama 等）自动放大 read timeout
            # 本地推理受 CPU/GPU 资源限制，推理时间远大于云端 API
            # 默认 read timeout 可能导致频繁超时被误判为故障
            timeout_value = self.config.timeout
            if is_local:
                base_timeout = build_httpx_timeout(timeout_value, default=60.0)
                current_read = (
                    base_timeout.read if isinstance(base_timeout, httpx.Timeout) else 60.0
                )
                if current_read < 300.0:
                    timeout_value = {"read": 300.0, "connect": 30.0, "write": 30.0, "pool": 30.0}
                    logger.info(
                        f"[OpenAI] Local endpoint '{self.name}': auto-increased read timeout "
                        f"from {current_read}s to 300s (local inference is slower)"
                    )

            # httpx strips Authorization on cross-origin redirects for security.
            # Some OpenAI-compatible gateways (e.g., GitCode api-ai) internally redirect
            # to a different host. Event hooks fire on EVERY request including redirects,
            # so we use one to re-attach the credential that _build_redirect_request strips.
            api_key_for_hook = (self.api_key or "").strip()
            if not api_key_for_hook and is_local:
                api_key_for_hook = "local"

            async def _ensure_auth_on_redirect(request: httpx.Request):
                if api_key_for_hook and "Authorization" not in request.headers:
                    request.headers["Authorization"] = f"Bearer {api_key_for_hook}"

            # trust_env=False: 代理由 get_proxy_config() 显式管理（含可达性验证）。
            # 避免 macOS/Windows 残留系统代理（Clash/V2Ray 等）导致请求被路由到
            # 不存在的代理端口而失败。
            client_kwargs = {
                "timeout": build_httpx_timeout(timeout_value, default=60.0),
                "follow_redirects": True,
                "trust_env": False,
                "event_hooks": {"request": [_ensure_auth_on_redirect]},
            }

            if proxy and not should_bypass_proxy(self.base_url):
                client_kwargs["proxy"] = proxy
                logger.debug(f"[OpenAI] Using proxy: {proxy}")

            if transport:
                client_kwargs["transport"] = transport

            self._client = httpx.AsyncClient(**client_kwargs)
            self._client_loop_id = current_loop_id

        return self._client

    def _estimate_request_timeout(self, body: dict) -> httpx.Timeout | None:
        """根据请求体大小动态计算超时

        大上下文场景下，默认 read timeout 可能不够，需按比例放大以避免
        频繁 ReadTimeout 导致的无效重试。

        本地端点优化：
        - prompt processing 时间与 prompt 大小近似线性（约 100 tok/s）
        - 基础 300 秒覆盖 30k tokens，每多 10k tokens 增加 120 秒
        - 上限 900 秒（15 分钟），覆盖 60k+ tokens 场景

        Returns:
            httpx.Timeout 或 None（不需要覆盖时）
        """
        messages = body.get("messages", [])
        body_chars = sum(
            len(str(m.get("content", ""))) + len(str(m.get("tool_calls", ""))) for m in messages
        )
        tools = body.get("tools", [])
        if tools:
            body_chars += sum(len(str(t)) for t in tools)

        # 估算 token 数：中文约 2 字符/token，工具定义按 3 字符/token 保守估算
        est_tokens = body_chars // 2

        is_local = self._is_local_endpoint()

        # 本地端点：20k tokens 以上就开始动态调整
        # 远程端点：30k tokens 以上才开始
        threshold = 20_000 if is_local else 30_000
        if est_tokens < threshold:
            return None

        if is_local:
            # 本地端点：基础 300 秒（30k tokens），每多 10k tokens 加 120 秒
            # 按 100 tok/s 估算：10k tokens 需要 100 秒，留 20% 余量
            base_read = 300.0
            extra_tokens = max(0, est_tokens - 30_000)
            extra_time = (extra_tokens / 10_000) * 120.0
            new_read = base_read + extra_time
            new_read = min(new_read, 900.0)  # 上限 15 分钟
        else:
            # 远程端点：原有逻辑
            base_read = float(self.config.timeout or 180)
            scale = min(est_tokens / 30_000, 3.0)
            new_read = base_read * scale
            new_read = min(new_read, 540.0)

        if new_read <= 300.0:
            return None

        logger.info(
            f"[OpenAI] '{self.name}': large context (~{est_tokens // 1000}k tokens est.), "
            f"scaling read timeout → {new_read:.0f}s (local={is_local})"
        )
        return httpx.Timeout(
            connect=min(10.0, new_read),
            read=new_read,
            write=min(30.0, new_read),
            pool=min(30.0, new_read),
        )

    def _estimate_stream_timeout(self, body: dict) -> httpx.Timeout | None:
        """Bound remote time-to-first-data and inter-chunk stalls.

        The generic request timeout grows with prompt size, which is useful for
        non-streaming responses but can leave an interactive stream apparently
        frozen for several minutes before endpoint failover starts.
        """
        if self._is_local_endpoint():
            return self._estimate_request_timeout(body)

        dynamic_timeout = self._estimate_request_timeout(body)
        configured_read = float(self.config.timeout or 180)
        if dynamic_timeout is not None:
            configured_read = float(dynamic_timeout.read or configured_read)

        read_timeout = min(configured_read, REMOTE_STREAM_READ_TIMEOUT_CAP_SECONDS)
        if configured_read > read_timeout:
            logger.info(
                "[OpenAI] '%s': capping remote stream read timeout %.0fs -> %.0fs",
                self.name,
                configured_read,
                read_timeout,
            )

        return httpx.Timeout(
            connect=min(10.0, read_timeout),
            read=read_timeout,
            write=min(30.0, read_timeout),
            pool=min(30.0, read_timeout),
        )

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """发送聊天请求（统一的非流式 → 流式自动回退）

        回退策略（按优先级）：
        1. 配置 stream_only → 直接走流式
        2. 代理明确要求 stream → 永久切换流式
        3. 非流式空响应异常 / 非流式成功但内容空+token>0 → 尝试流式，成功则记忆
        """
        await self.acquire_rate_limit()

        if self._stream_only:
            return await self._chat_via_stream(request)

        response: LLMResponse | None = None
        non_stream_error: LLMError | None = None

        try:
            response = await self._chat_non_stream(request)
        except (AuthenticationError, RateLimitError):
            raise
        except LLMError as e:
            non_stream_error = e
            if _is_stream_only_error(str(e)):
                logger.info(
                    f"[OpenAI] '{self.name}': detected stream-only endpoint, "
                    f"retrying with streaming transport"
                )
                self._stream_only = True
                return await self._chat_via_stream(request)

        # 统一判断：非流式未能产出内容 → 尝试流式回退
        _should_fallback = (
            non_stream_error is not None and _is_empty_response_error(str(non_stream_error))
        ) or (response is not None and not response.content and response.usage.output_tokens > 0)

        if _should_fallback:
            _reason = (
                f"non-stream error: {non_stream_error}"
                if non_stream_error
                else f"empty content with {response.usage.output_tokens} output tokens"  # type: ignore[union-attr]
            )
            logger.warning(f"[OpenAI] '{self.name}': {_reason}, attempting stream fallback")
            try:
                stream_response = await self._chat_via_stream(request)
                if stream_response.content:
                    logger.info(
                        f"[OpenAI] '{self.name}': stream fallback recovered content "
                        f"({len(stream_response.content)} blocks), "
                        f"switching to stream-only for this endpoint"
                    )
                    self._stream_only = True
                    return stream_response
                logger.warning(
                    f"[OpenAI] '{self.name}': stream fallback also returned empty content"
                )
            except Exception as stream_err:
                logger.warning(f"[OpenAI] '{self.name}': stream fallback failed: {stream_err}")

        if non_stream_error is not None:
            raise non_stream_error
        return response  # type: ignore[return-value]

    async def _chat_non_stream(self, request: LLMRequest) -> LLMResponse:
        """非流式请求实现（原始路径，逻辑完全不变）。调用方须已获取 rate limit。"""
        client = await self._get_client()

        body = self._build_request_body(request)

        logger.debug(f"OpenAI request to {self.base_url}: model={body.get('model')}")

        req_timeout = self._estimate_request_timeout(body)

        try:
            # ── 本地模型冷启动 503 有限重试（model_loading / model_suppressed）──
            # model-manager 在 llama-server 加载模型期间返回 503 + retry_after_sec，
            # 加载完成即自动恢复。这类瞬时错误在 provider 内按上游建议原地等待，
            # 避免 trait mining 等后台小请求直接失败或误报 ERROR；
            # 超过上限仍未就绪则照常抛错（带上 retry_after_seconds 供 client 层退避）。
            _loading_deadline = time.monotonic() + _MODEL_LOADING_MAX_WAIT_SECONDS
            while True:
                response = await client.post(
                    self._api_url,
                    headers=self._build_headers(),
                    json=body,
                    **({"timeout": req_timeout} if req_timeout else {}),
                )
                if (
                    response.status_code == 503
                    and _is_model_loading_503(response.status_code, response.text or "")
                    and time.monotonic() < _loading_deadline
                ):
                    wait_s = (
                        _extract_retry_after_seconds(response.text or "", response.headers)
                        or 3.0
                    )
                    logger.info(
                        "[OpenAIProvider] '%s': model loading (503), "
                        "waiting %.1fs before retry",
                        self.name,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                    continue
                break

            if response.status_code >= 400:
                body = (response.text or "")[:500]
                logger.error(
                    "[OpenAIProvider] upstream non-stream error status=%s body=%s",
                    response.status_code,
                    body[:1000],
                )
                if response.status_code == 401:
                    raise AuthenticationError(
                        _humanize_upstream_error(401, body),
                        status_code=401,
                        raw_body=body,
                    )
                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    raw_body = f"{body}\nretry-after: {retry_after}" if retry_after else body
                    raise RateLimitError(
                        _humanize_upstream_error(429, body),
                        status_code=429,
                        raw_body=raw_body,
                        retry_after_seconds=_extract_retry_after_seconds(
                            body, response.headers
                        ),
                    )
                # 503 上游声明了重试等待秒数（body 内 retry_after_sec / Retry-After 头）：
                # 传给 client 层 _get_retry_delay，使其按上游建议等待而非过早退避重试。
                raise LLMError(
                    _humanize_upstream_error(response.status_code, body),
                    status_code=response.status_code,
                    raw_body=body,
                    retry_after_seconds=_extract_retry_after_seconds(
                        body, response.headers
                    ),
                )

            try:
                data = response.json()
            except JSONDecodeError:
                content_type = response.headers.get("content-type", "")
                body_preview = (response.text or "")[:500]
                raise LLMError(
                    "Invalid JSON response from OpenAI-compatible endpoint "
                    f"(status={response.status_code}, content-type={content_type}, "
                    f"body_preview={body_preview!r})"
                )

            # 某些 OpenAI 兼容 API 在 HTTP 200 响应体内返回错误（不走标准 HTTP 状态码）
            if "error" in data and data["error"]:
                err_obj = (
                    data["error"]
                    if isinstance(data["error"], dict)
                    else {"message": str(data["error"])}
                )
                err_msg = err_obj.get("message", str(err_obj))
                err_code = err_obj.get("code", "")
                logger.warning(
                    f"[OpenAI] '{self.name}': API returned 200 with error in body: "
                    f"code={err_code}, message={err_msg}"
                )
                raise LLMError(f"API error in response body: {err_msg}")

            # HTTP 200 但 choices 为空 —— 尝试 Responses API 解析
            choices = data.get("choices")
            if not choices:
                _output = data.get("output")
                if isinstance(_output, list) and _output:
                    self.mark_healthy()
                    return self._parse_responses_api(data, _output)
                body_preview = json.dumps(data, ensure_ascii=False)[:500]
                logger.warning(
                    f"[OpenAI] '{self.name}': API returned 200 but choices is empty. "
                    f"Response preview: {body_preview}"
                )
                self.mark_unhealthy(
                    f"Empty choices in 200 response (model={data.get('model', '?')})",
                    is_local=self._is_local_endpoint(),
                )
                raise LLMError(
                    f"API returned empty response (no choices) from '{self.name}'. "
                    f"This usually indicates the model is unavailable, rate-limited, "
                    f"or the API key lacks permission. Response: {body_preview}"
                )

            self.mark_healthy()
            self._last_raw_diagnostic = None
            result = self._parse_response(data)
            # 附加原始响应诊断（content lost 时由 _parse_response 设置）
            _diag = self._last_raw_diagnostic
            if _diag and not result.content:
                result._raw_diagnostic = _diag  # type: ignore[attr-defined]
            return result

        except httpx.TimeoutException as e:
            detail = f"{type(e).__name__}: {e}"
            self.mark_unhealthy(f"Timeout: {detail}", is_local=self._is_local_endpoint())
            raise LLMError(f"Request timeout: {detail}")
        except httpx.RequestError as e:
            detail = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}({repr(e)})"
            self.mark_unhealthy(f"Request error: {detail}", is_local=self._is_local_endpoint())
            raise LLMError(f"Request failed: {detail}")

    async def _iter_sse_events(self, body: dict) -> AsyncIterator[dict]:
        """SSE 传输层：发送流式请求，解析 SSE 行，yield 转换后的事件。

        body 须已包含 "stream": True。调用方须已获取 rate limit。
        子类可覆写以适配不同 SSE 格式（如 Responses API 的 named events）。
        """
        client = await self._get_client()
        req_timeout = self._estimate_stream_timeout(body)
        has_content = False
        received_chunks = 0

        # 本地模型冷启动 503 有限重试（同非流式路径）：model_loading /
        # model_suppressed 是加载完成后必然恢复的瞬时错误，按上游
        # retry_after_sec 原地等待后重试整个流式请求。
        _loading_deadline = time.monotonic() + _MODEL_LOADING_MAX_WAIT_SECONDS
        # 对端中断连接（RemoteProtocolError 等）在首块到达前的原地重试次数：
        # 本地 llama-server 崩溃后 model-manager 会自动拉起（几十秒内），
        # 首块前重试一次可避免一次崩溃就触发跨端点 failover / 标记不健康。
        _conn_closed_retries = 0
        _MAX_CONN_CLOSED_RETRIES = 1
        while True:
            try:
                async with client.stream(
                    "POST",
                    self._api_url,
                    headers=self._build_headers(),
                    json=body,
                    **({"timeout": req_timeout} if req_timeout else {}),
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        error_text = error_body.decode(errors="replace")[:500]
                        if (
                            response.status_code == 503
                            and _is_model_loading_503(response.status_code, error_text)
                            and time.monotonic() < _loading_deadline
                        ):
                            wait_s = (
                                _extract_retry_after_seconds(error_text, response.headers)
                                or 3.0
                            )
                            logger.info(
                                "[OpenAIProvider] '%s': model loading (503 stream), "
                                "waiting %.1fs before retry",
                                self.name,
                                wait_s,
                            )
                            await asyncio.sleep(wait_s)
                            continue
                        logger.error(
                            "[OpenAIProvider] upstream stream error status=%s body=%s",
                            response.status_code,
                            error_text,
                        )
                        if response.status_code == 401:
                            raise AuthenticationError(
                                _humanize_upstream_error(401, error_text),
                                status_code=401,
                                raw_body=error_text,
                            )
                        if response.status_code == 429:
                            retry_after = response.headers.get("retry-after")
                            raw_body = (
                                f"{error_text}\nretry-after: {retry_after}"
                                if retry_after
                                else error_text
                            )
                            raise RateLimitError(
                                _humanize_upstream_error(429, error_text),
                                status_code=429,
                                raw_body=raw_body,
                                retry_after_seconds=_extract_retry_after_seconds(
                                    error_text, response.headers
                                ),
                            )
                        raise LLMError(
                            _humanize_upstream_error(response.status_code, error_text),
                            status_code=response.status_code,
                            raw_body=error_text,
                            retry_after_seconds=_extract_retry_after_seconds(
                                error_text, response.headers
                            ),
                        )

                    first_line_raw = None
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        if first_line_raw is None:
                            first_line_raw = line

                        if line.startswith("data: "):
                            data = line[6:]
                            if data.strip() and data != "[DONE]":
                                try:
                                    event = json.loads(data)
                                    has_content = True
                                    received_chunks += 1
                                    converted = self._convert_stream_event(event)
                                    if isinstance(converted, list):
                                        for ev in converted:
                                            yield ev
                                    else:
                                        yield converted
                                except json.JSONDecodeError:
                                    continue
                        elif not has_content and not line.startswith(":"):
                            try:
                                err_data = json.loads(line)
                                if "error" in err_data:
                                    err_obj = err_data["error"]
                                    err_msg = (
                                        err_obj.get("message", str(err_obj))
                                        if isinstance(err_obj, dict)
                                        else str(err_obj)
                                    )
                                    raise LLMError(f"Stream error from '{self.name}': {err_msg}")
                            except json.JSONDecodeError:
                                if "error" in line.lower():
                                    raise LLMError(f"Stream error from '{self.name}': {line[:500]}")

                    if has_content:
                        self.mark_healthy()
                    else:
                        preview = (first_line_raw or "")[:300]
                        logger.warning(
                            f"[OpenAI] '{self.name}': stream returned 200 but no content chunks. "
                            f"First line: {preview!r}"
                        )
                        self.mark_unhealthy(
                            f"Empty stream response (model={body.get('model', '?')})",
                            is_local=self._is_local_endpoint(),
                        )
                        raise LLMError(
                            f"Stream returned empty response from '{self.name}'. "
                            f"Model may be unavailable or rate-limited."
                        )

            except httpx.TimeoutException as e:
                detail = f"{type(e).__name__}: {e}"
                self.mark_unhealthy(f"Timeout: {detail}", is_local=self._is_local_endpoint())
                timeout_phase = "stalled" if has_content else "first-byte timeout"
                raise LLMError(
                    f"Stream {timeout_phase} after {received_chunks} chunk(s): {detail}"
                )
            except httpx.RequestError as e:
                detail = f"{type(e).__name__}: {e}" if str(e) else f"{type(e).__name__}({repr(e)})"
                conn_closed = _is_connection_closed_error(e)
                # 对端中断连接且首块未到达：本地服务端崩溃后会自动重启，
                # 做一次同端点原地重试（短退避），避免立刻触发跨端点 failover。
                if (
                    conn_closed
                    and not has_content
                    and _conn_closed_retries < _MAX_CONN_CLOSED_RETRIES
                ):
                    _conn_closed_retries += 1
                    self.mark_unhealthy(
                        f"Stream connection closed before first chunk: {detail}",
                        category="transient",
                        is_local=self._is_local_endpoint(),
                    )
                    logger.warning(
                        "[OpenAI] '%s': connection closed before first chunk "
                        "(attempt %d/%d), retrying same stream after short backoff: %s",
                        self.name,
                        _conn_closed_retries,
                        _MAX_CONN_CLOSED_RETRIES + 1,
                        detail,
                    )
                    await asyncio.sleep(1.5)
                    continue
                category = "transient" if conn_closed else ""
                self.mark_unhealthy(
                    f"Stream request error: {detail}",
                    category=category,
                    is_local=self._is_local_endpoint(),
                )
                hint = (
                    " (connection closed by upstream — server may have crashed/restarted)"
                    if conn_closed
                    else ""
                )
                raise LLMError(
                    f"Stream request failed after {received_chunks} chunk(s): {detail}{hint}",
                    connection_closed=conn_closed,
                )

            break

    async def _chat_via_stream(self, request: LLMRequest) -> LLMResponse:
        """流式传输 → 同步响应适配器：收集流式事件，组装为 LLMResponse。

        用于 stream-only 端点（如 Codex relay）。调用方须已获取 rate limit。
        """
        body = self._build_request_body(request)
        body["stream"] = True

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[str, dict] = {}
        current_tool_id: str | None = None
        stop_reason = StopReason.END_TURN
        response_model = self.config.model
        stream_usage: dict | None = None

        async for event in self._iter_sse_events(body):
            event_type = event.get("type")

            if event_type == "usage":
                stream_usage = event.get("usage")
                continue

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                delta_type = delta.get("type")

                if delta_type == "text":
                    text_parts.append(delta.get("text") or "")
                elif delta_type == "reasoning":
                    reasoning_parts.append(delta.get("text") or "")
                elif delta_type == "tool_use":
                    call_id = delta.get("id")
                    if call_id:
                        if call_id not in tool_calls:
                            tool_calls[call_id] = {
                                "name": delta.get("name") or "",
                                "arguments": "",
                            }
                        elif delta.get("name") and not tool_calls[call_id]["name"]:
                            tool_calls[call_id]["name"] = delta["name"]
                        current_tool_id = call_id
                        extra = delta.get("extra_content")
                        if extra and "extra_content" not in tool_calls[call_id]:
                            tool_calls[call_id]["extra_content"] = extra
                    target_id = call_id or current_tool_id
                    if target_id and target_id in tool_calls:
                        tool_calls[target_id]["arguments"] += delta.get("arguments") or ""

            elif event_type == "message_stop":
                raw_reason = event.get("stop_reason", "stop")
                _stop_map = {
                    "stop": StopReason.END_TURN,
                    "length": StopReason.MAX_TOKENS,
                    "tool_calls": StopReason.TOOL_USE,
                    "function_call": StopReason.TOOL_USE,
                }
                stop_reason = _stop_map.get(raw_reason, StopReason.END_TURN)

            elif event_type == "error":
                raise LLMError(f"Stream error from '{self.name}': {event.get('error', 'unknown')}")

        content_blocks: list = []
        text = "".join(text_parts)
        if text:
            content_blocks.append(TextBlock(text=text))

        for call_id, tc in tool_calls.items():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": tc["arguments"]}
            content_blocks.append(
                ToolUseBlock(
                    id=call_id,
                    name=tc["name"],
                    input=args,
                    provider_extra=tc.get("extra_content"),
                )
            )

        if tool_calls and stop_reason != StopReason.MAX_TOKENS:
            stop_reason = StopReason.TOOL_USE

        _reasoning_text = "".join(reasoning_parts)
        has_any_tool_calls = bool(tool_calls)

        # 防御层：与 _parse_response 对齐 — reasoning 作为可见文本 fallback
        if not content_blocks and not has_any_tool_calls and _reasoning_text:
            logger.warning(
                f"[STREAM] content empty but reasoning has {len(_reasoning_text)} chars "
                f"from {self.name} — using reasoning as visible text fallback"
            )
            content_blocks.append(TextBlock(text=_reasoning_text))
            _reasoning_text = ""

        # 从流尾部 usage chunk 获取 token 统计（不再始终为零）
        _usage = Usage()
        if stream_usage:
            _usage = Usage(
                input_tokens=stream_usage.get("prompt_tokens", 0),
                output_tokens=stream_usage.get("completion_tokens", 0),
            )

        if not content_blocks and _usage.output_tokens > 0:
            logger.error(
                f"[STREAM] ⚠️ CONTENT LOST: {_usage.output_tokens} output tokens "
                f"but content is empty from {self.name} (stream_only adapter)"
            )

        return LLMResponse(
            id="",
            content=content_blocks,
            stop_reason=stop_reason,
            usage=_usage,
            model=response_model,
            reasoning_content=_reasoning_text or None,
        )

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[dict]:
        """流式聊天请求"""
        await self.acquire_rate_limit()
        body = self._build_request_body(request)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        async for event in self._iter_sse_events(body):
            yield event

    def _is_local_endpoint(self) -> bool:
        """检查是否为本地/局域网端点（Ollama/LM Studio/vLLM 等）

        覆盖 loopback + RFC 1918 私有地址 + link-local，与 proxy_utils._is_private_host 对齐。
        """
        from .proxy_utils import should_bypass_proxy

        url = self.base_url.lower()
        if any(host in url for host in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")):
            return True
        return should_bypass_proxy(self.base_url)

    def _get_auth(self) -> _BearerAuth:
        """获取认证信息（通过 httpx Auth 机制，确保重定向时不丢失凭据）"""
        api_key = (self.api_key or "").strip()
        if not api_key:
            if self._is_local_endpoint():
                api_key = "local"
            else:
                hint = ""
                if self.config.api_key_env:
                    hint = f" (env var {self.config.api_key_env} is not set)"
                raise AuthenticationError(
                    f"Missing API key for endpoint '{self.name}'{hint}. "
                    "Set the environment variable or configure api_key/api_key_env."
                )
        return _BearerAuth(api_key)

    def _build_headers(self) -> dict:
        """构建请求头（含 Authorization，不依赖 httpx auth 机制）"""
        api_key = (self.api_key or "").strip()
        if not api_key:
            if self._is_local_endpoint():
                api_key = "local"
            else:
                hint = ""
                if self.config.api_key_env:
                    hint = f" (env var {self.config.api_key_env} is not set)"
                raise AuthenticationError(
                    f"Missing API key for endpoint '{self.name}'{hint}. "
                    "Set the environment variable or configure api_key/api_key_env."
                )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # 避免部分打包环境缺少可用 zstd 解码器时，httpx 在业务错误分类前失败。
            "Accept-Encoding": "gzip, deflate",
        }

        if "openrouter" in self.base_url.lower():
            headers["HTTP-Referer"] = "https://github.com/openkitsune"
            headers["X-Title"] = "OpenKitsune"

        return headers

    def _build_request_body(self, request: LLMRequest) -> dict:
        """构建请求体"""
        # 转换消息格式（传递 provider 以正确处理视频等多媒体内容）
        thinking_enabled = request.enable_thinking and self.config.has_capability("thinking")

        # thinking-only 模型（deepseek-reasoner、QwQ 等）无法关闭思考，
        # 即使 fallback 降级了 enable_thinking=False，
        # 仍必须注入 reasoning_content 并保持 thinking 启用，否则 API 返回 400
        is_always_thinking = False
        if not thinking_enabled and self.config.has_capability("thinking"):
            from ..capabilities import is_thinking_only

            is_always_thinking = is_thinking_only(
                self.config.model,
                provider_slug=self.config.provider,
            )
            if is_always_thinking:
                thinking_enabled = True

        _vision_available = self.config.has_capability("vision") and not getattr(
            self,
            "_vision_payload_unsupported",
            False,
        )
        messages = convert_messages_to_openai(
            request.messages,
            request.system,
            provider=self.config.provider,
            enable_thinking=thinking_enabled,
            model=self.config.model,
            vision_available=_vision_available,
        )

        body = {
            "model": self.config.model,
            "messages": messages,
        }

        # max_tokens 处理策略：
        # - 调用方/端点显式给值时尽量尊重，但已知模型不能超过其真实输出上限；
        # - 未显式给值时用模型默认输出预算；
        # - 未知模型保留历史 16k 兜底，避免对中转/自定义模型过度限制。
        #
        # 特殊情况 — OpenAI o1/o3/o4 推理模型：
        # 这些模型拒绝 max_tokens 参数，要求使用 max_completion_tokens。
        # 检测方式：模型名含 "o1-"/"o3-"/"o4-" 且 provider 为 openai。
        _model_lower = self.config.model.lower()
        _is_openai_reasoning = self.config.provider == "openai" and any(
            tag in _model_lower for tag in ("o1-", "o3-", "o4-", "/o1", "/o3", "/o4")
        )
        _token_key = "max_completion_tokens" if _is_openai_reasoning else "max_tokens"

        body[_token_key] = resolve_output_token_budget(
            self.config.model,
            request_max_tokens=request.max_tokens,
            endpoint_max_tokens=self.config.max_tokens,
        )

        # 工具
        if request.tools:
            body["tools"] = convert_tools_to_openai(request.tools)
            body["tool_choice"] = "auto"

        # 温度
        if request.temperature != 1.0:
            body["temperature"] = request.temperature

        # 停止序列
        if request.stop_sequences:
            body["stop"] = request.stop_sequences

        # 额外参数（服务商特定）
        if self.config.extra_params:
            body.update(self.config.extra_params)
        if request.extra_params:
            body.update(request.extra_params)

        is_minimax = is_minimax_endpoint(
            self.config.provider,
            self.base_url,
            self.config.model,
        )

        # ── 本地端点检测 ──
        # Ollama / LM Studio 等本地推理引擎不支持 OpenAI 风格的
        # thinking: {"type": "enabled"} 嵌套参数，但 Ollama 0.9+ 支持
        # enable_thinking (bool) 来控制双模模型（如 qwen3.5）的思考模式。
        is_local = self._is_local_endpoint()

        # DashScope 思考模式 — 必须在 extra_params 之后，以覆盖其中的 enable_thinking
        if self.config.provider == "dashscope" and self.config.has_capability("thinking"):
            ds_thinking = bool(request.enable_thinking)
            if not ds_thinking and is_always_thinking:
                ds_thinking = True
            body["enable_thinking"] = ds_thinking
            if ds_thinking and request.thinking_depth:
                budget = thinking_budget_for_depth(request.thinking_depth)
                if budget:
                    body["thinking_budget"] = budget
            elif not ds_thinking:
                body.pop("thinking_budget", None)

        # SiliconFlow 思考模式
        #
        # SiliconFlow API 有两类思考模型（参考官方文档）：
        #
        # A 类 - 双模模型（支持 enable_thinking 切换）：
        #   Qwen3 系列, Hunyuan-A13B, GLM-4.6V/4.5V, DeepSeek-V3.1/V3.2 系列
        #   → 发送 enable_thinking (bool) + thinking_budget
        #
        # B 类 - 天然思考模型（始终思考，不接受 enable_thinking）：
        #   Kimi-K2-Thinking, DeepSeek-R1, QwQ-32B, GLM-Z1 系列
        #   → 只发送 thinking_budget 控制深度，不发送 enable_thinking
        #   → 向这些模型发送 enable_thinking 会导致 400:
        #     "Value error, current model does not support parameter enable_thinking"
        #
        # 两类模型都不支持 OpenAI 风格的 thinking: {"type": "enabled"} + reasoning_effort
        elif self.config.provider in (
            "siliconflow",
            "siliconflow-intl",
        ) and self.config.has_capability("thinking"):
            from ..capabilities import is_thinking_only

            sf_thinking_only = is_thinking_only(
                self.config.model, provider_slug=self.config.provider
            )

            if sf_thinking_only:
                # B 类：天然思考模型 — 只允许 thinking_budget 控制深度
                # 必须清理 extra_params 可能泄漏的 enable_thinking
                body.pop("enable_thinking", None)
                if request.thinking_depth:
                    budget = thinking_budget_for_depth(request.thinking_depth)
                    if budget:
                        body["thinking_budget"] = budget
            else:
                # A 类：双模模型 — enable_thinking 切换 + thinking_budget
                body["enable_thinking"] = bool(request.enable_thinking)
                if request.enable_thinking:
                    if request.thinking_depth:
                        budget = thinking_budget_for_depth(request.thinking_depth)
                        if budget:
                            body["thinking_budget"] = budget
                else:
                    body.pop("thinking_budget", None)

            # 清理不适用于 SiliconFlow 的 OpenAI 风格参数（可能由 extra_params 引入）
            body.pop("thinking", None)
            body.pop("reasoning_effort", None)

        # 本地端点思考模式（Ollama 0.9+ 等）
        #
        # Ollama 0.9+ 的 OpenAI 兼容 API 支持 enable_thinking (bool) 来切换
        # 双模模型（如 qwen3.5）的思考模式。Thinking-only 模型（如 qwen3）
        # 通过 <think> 标签自行输出思考内容，无需 API 参数控制。
        # 不使用 OpenAI 风格的 thinking: {"type": "enabled"} 或 reasoning_effort。
        elif is_local and self.config.has_capability("thinking"):
            if request.enable_thinking:
                body["enable_thinking"] = True

        # OpenRouter 思考模式
        #
        # OpenRouter 使用独立的 reasoning API（不兼容 OpenAI thinking / DashScope enable_thinking）：
        #   请求: reasoning: {"effort": "high"} 或 {"enabled": true}
        #   响应: message.reasoning (str) 包含推理过程
        # 文档: https://openrouter.ai/docs/use-cases/reasoning-tokens
        elif self.config.provider == "openrouter" and self.config.has_capability("thinking"):
            body.pop("enable_thinking", None)
            body.pop("thinking", None)
            body.pop("reasoning_effort", None)

            if request.enable_thinking or is_always_thinking:
                depth_map = {"low": "low", "medium": "medium", "high": "high", "max": "high"}
                depth = normalize_thinking_depth(request.thinking_depth or "medium")
                effort = depth_map.get(depth or "medium", "medium")
                body["reasoning"] = {"effort": effort}
            else:
                body.pop("reasoning", None)

        # OpenAI 兼容端点思考模式（火山引擎/DeepSeek/vLLM 等）
        #
        # 背景：
        # - 原生 OpenAI o1/o3 系列天然就是思考模型，只需 reasoning_effort 控制深度
        # - 但其他 OpenAI-compatible 端点（火山引擎/DeepSeek/vLLM 等）需要显式传
        #   thinking: {"type": "enabled"} 来启用思考模式，reasoning_effort 只是可选的深度控制
        # - 如果只传 reasoning_effort 而不启用 thinking，火山引擎等 API 会返回 400:
        #   "Invalid combination of reasoning_effort and thinking type: medium + disabled"
        #
        # 排除: DashScope、SiliconFlow、本地端点、OpenRouter（上面已各自处理）
        elif self.config.has_capability("thinking") and not is_local:
            body.pop("enable_thinking", None)

            if request.enable_thinking or is_always_thinking:
                if "thinking" not in body:
                    thinking_type = "adaptive" if is_minimax else "enabled"
                    body["thinking"] = {"type": thinking_type}
                if request.thinking_depth:
                    effort = reasoning_effort_for_depth(
                        provider=self.config.provider,
                        base_url=self.base_url,
                        model=self.config.model,
                        depth=request.thinking_depth,
                    )
                    if effort:
                        body["reasoning_effort"] = effort
            else:
                body.pop("reasoning_effort", None)
                if "thinking" in body:
                    body["thinking"] = {"type": "disabled"}

        # MiniMax accepts only low/medium/high for the top-level thinking_depth
        # field. OpenKitsune's UI exposes "max"; clamp it at the provider boundary.
        if is_minimax:
            depth = minimax_thinking_depth(request.thinking_depth or body.get("thinking_depth"))
            if depth:
                body["thinking_depth"] = depth
            else:
                body.pop("thinking_depth", None)

        # ── 本地端点清理 ──
        # 移除可能通过 extra_params 泄漏的、本地引擎不支持的思考参数。
        # enable_thinking (bool) 不在此列：Ollama 0.9+ 原生支持，
        # 其他本地引擎（LM Studio / 旧版 Ollama）对未知简单字段静默忽略。
        if is_local:
            _stripped = [
                k for k in ("thinking", "thinking_budget", "reasoning_effort") if k in body
            ]
            for _key in _stripped:
                body.pop(_key, None)
            if _stripped:
                logger.debug(
                    f"[OpenAI] Local endpoint '{self.name}': stripped thinking params {_stripped}"
                )

        # ── 端点级 thinking 参数剥离 ──
        # 若端点曾因 thinking/reasoning_effort 返回 400，
        # 客户端自愈逻辑已在 provider 上标记 _thinking_params_unsupported，
        # 此处作为最终安全网，确保不再发送任何 thinking 相关参数。
        if getattr(self, "_thinking_params_unsupported", False):
            for _tp in ("thinking", "reasoning_effort", "enable_thinking", "thinking_budget"):
                body.pop(_tp, None)

        # ── 请求体卫生检查 ──
        # extra_params 的 body.update() 是盲覆盖，可能将精心计算的参数（如 max_tokens）
        # 替换为无效值。在 return 前做最终校验，确保发出的请求体始终合法。
        for _tk in ("max_tokens", "max_completion_tokens"):
            _tv = body.get(_tk)
            if _tv is not None and (not isinstance(_tv, int) or _tv <= 0):
                body.pop(_tk, None)

        # ── DashScope Explicit Prompt Cache ──
        # DashScope OpenAI 兼容模式支持 Anthropic 风格的 cache_control 字段，
        # 命中后输入 token 按 20% 计费、TTFT 显著降低。激活条件：
        #   1) provider == "dashscope"
        #   2) 模型在 model_registry 中标记 supports_cache=True
        #   3) system prompt 含 SYSTEM_PROMPT_DYNAMIC_BOUNDARY 切割标记
        # 仅切割 system 一处即可（DashScope cache 走 message content blocks，
        # tools 数组层面不接受 cache_control）。命中情况通过 _parse_response /
        # 流式 chunk_usage 中的 prompt_tokens_details.cached_tokens 统计。
        if self.config.provider == "dashscope":
            try:
                _caps = get_model_capabilities(self.config.model)
                if _caps.supports_cache and body.get("messages"):
                    _msgs = body["messages"]
                    if _msgs and _msgs[0].get("role") == "system":
                        _sys_content = _msgs[0].get("content")
                        if isinstance(_sys_content, str) and _sys_content:
                            _blocks = build_cached_system_blocks(_sys_content)
                            if _blocks:
                                _msgs[0] = {"role": "system", "content": _blocks}
            except Exception as _cache_err:
                logger.debug(f"[CACHE] DashScope cache_control injection skipped: {_cache_err}")

        from ..request_budget import validate_request_body

        validate_request_body(body, self.config)
        return body

    @staticmethod
    def _extract_from_responses_output(output: list) -> str:
        """从 OpenAI Responses API 的 output 数组中提取文本内容。"""
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            itype = item.get("type", "")
            if itype == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict):
                        ptype = part.get("type", "")
                        if ptype in ("output_text", "text"):
                            texts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        texts.append(part)
            elif itype in ("text", "output_text"):
                texts.append(item.get("text", ""))
        return "".join(texts)

    @staticmethod
    def _extract_text_value(value: object) -> str:
        """Best-effort text extraction from non-standard OpenAI-compatible fields."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "".join(OpenAIProvider._extract_text_value(item) for item in value).strip()
        if isinstance(value, dict):
            for key in (
                "text",
                "output_text",
                "content",
                "value",
                "message",
                "response",
                "refusal",
                "thinking",
            ):
                if key in value:
                    recovered = OpenAIProvider._extract_text_value(value.get(key))
                    if recovered:
                        return recovered
        return ""

    def _recover_empty_content_text(
        self, message: dict, choice: dict, data: dict
    ) -> tuple[str, str]:
        """Recover visible text from compatibility gateways with empty message.content.

        PR-C1: extended to cover the dashscope OpenAI-compat gateway, which
        sometimes returns the actual text in non-standard locations
        (``message.reasoning_content`` for thinking models, ``data.output.text``
        / ``data.output.choices[0].message.content`` for native dashscope
        passthroughs, or ``choice.delta.content`` for accidentally streamed
        chunks).
        """
        # 1) reasoning_content / message-level fallbacks
        for source, value in (
            ("message.reasoning_content", message.get("reasoning_content")),
            ("message.output", message.get("output")),
            ("message.text", message.get("text")),
            ("message.thinking", message.get("thinking")),
            ("message.refusal", message.get("refusal")),
            ("choice.text", choice.get("text")),
        ):
            recovered = self._extract_text_value(value)
            if recovered:
                return source, recovered

        # 2) choice.delta.content — when an OpenAI-compat proxy accidentally
        #    sends a stream-style payload through the non-stream endpoint.
        delta = choice.get("delta") if isinstance(choice, dict) else None
        if isinstance(delta, dict):
            recovered = self._extract_text_value(delta.get("content"))
            if recovered:
                return "choice.delta.content", recovered

        # 3) Responses API style array
        output = data.get("output")
        if isinstance(output, list) and output:
            recovered = self._extract_from_responses_output(output)
            if recovered:
                return "data.output", recovered.strip()

        # 4) Native dashscope passthrough: data.output.{text,choices,...}
        if isinstance(output, dict):
            recovered = self._extract_text_value(output.get("text"))
            if recovered:
                return "data.output.text", recovered
            choices_in_output = output.get("choices")
            if isinstance(choices_in_output, list):
                for inner in choices_in_output:
                    if not isinstance(inner, dict):
                        continue
                    inner_msg = inner.get("message") or {}
                    recovered = self._extract_text_value(inner_msg.get("content"))
                    if recovered:
                        return "data.output.choices.message.content", recovered
                    recovered = self._extract_text_value(inner.get("text"))
                    if recovered:
                        return "data.output.choices.text", recovered

        for source, value in (
            ("data.text", data.get("text")),
            ("data.output_text", data.get("output_text")),
            ("data.response", data.get("response")),
            ("data.result.output_text", _safe_dig(data, "result", "output_text")),
            ("data.result.text", _safe_dig(data, "result", "text")),
        ):
            recovered = self._extract_text_value(value)
            if recovered:
                return source, recovered

        return "", ""

    def _parse_responses_api(self, data: dict, output: list) -> LLMResponse:
        """解析 OpenAI Responses API 格式的响应。"""
        text = self._extract_from_responses_output(output)
        content_blocks = [TextBlock(text=text)] if text else []

        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens") or usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("output_tokens") or usage_data.get("completion_tokens", 0),
        )

        if content_blocks:
            logger.info(f"[PARSE] Parsed Responses API format: {len(text)} chars from {self.name}")
        else:
            logger.warning(
                f"[PARSE] Responses API format detected but no text extracted from {self.name}, "
                f"output_items={len(output)}"
            )

        return LLMResponse(
            id=data.get("id", ""),
            content=content_blocks,
            stop_reason=StopReason.END_TURN,
            usage=usage,
            model=data.get("model", self.config.model),
        )

    def _parse_response(self, data: dict) -> LLMResponse:
        """解析响应"""
        self._last_raw_diagnostic = None
        choices = data.get("choices", [])
        if not choices:
            # Responses API 兼容：部分中转代理使用 output 字段返回内容
            _output = data.get("output")
            if isinstance(_output, list) and _output:
                return self._parse_responses_api(data, _output)
            return LLMResponse(
                id=data.get("id", ""),
                content=[],
                stop_reason=StopReason.END_TURN,
                usage=Usage(),
                model=data.get("model", self.config.model),
            )

        choice = choices[0]
        message = choice.get("message", {})
        content_blocks = []
        has_tool_calls = False

        # 文本内容 — 兼容 string 和 array 两种格式
        # 部分 OpenAI 兼容 API (如 Google Gemini OpenAI-compat) 返回 content 为数组:
        #   [{"type": "text", "text": "..."}, ...]
        raw_content = message.get("content")
        _thinking_from_content: list[str] = []
        if isinstance(raw_content, list):
            text_content = ""
            for part in raw_content:
                if isinstance(part, dict):
                    ptype = part.get("type", "")
                    if ptype == "text" or ptype == "output_text":
                        text_content += part.get("text", "")
                    elif ptype == "thinking":
                        _tval = part.get("thinking", "") or part.get("text", "")
                        if _tval:
                            _thinking_from_content.append(_tval)
                    elif "text" in part and ptype not in ("tool_use", "image"):
                        text_content += part.get("text", "")
                elif isinstance(part, str):
                    text_content += part
            if not text_content and raw_content and not _thinking_from_content:
                logger.warning(
                    f"[PARSE] content is list but no text parts extracted: "
                    f"types={[p.get('type') if isinstance(p, dict) else type(p).__name__ for p in raw_content[:3]]}"
                )
        else:
            text_content = raw_content or ""

        # 原生工具调用
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            converted = convert_tool_calls_from_openai(tool_calls)
            if converted:
                content_blocks.extend(converted)
                has_tool_calls = True
            logger.info(
                f"[TOOL_CALLS] Received {len(tool_calls)} native tool calls from {self.name}"
            )
            # 容错日志：有 tool_calls 但未能转换（通常是兼容网关字段不规范）
            if not converted:
                try:
                    first = tool_calls[0] if isinstance(tool_calls, list) and tool_calls else {}
                    func = (first.get("function") or {}) if isinstance(first, dict) else {}
                    logger.warning(
                        "[TOOL_CALLS] tool_calls present but none converted "
                        f"(first.type={getattr(first, 'get', lambda *_: None)('type') if isinstance(first, dict) else type(first)}, "
                        f"first.function.name={func.get('name') if isinstance(func, dict) else None}, "
                        f"first.function.arguments_type={type(func.get('arguments')).__name__ if isinstance(func, dict) else None})"
                    )
                except Exception:
                    pass

        # 文本格式工具调用解析（降级方案）
        # 当模型不支持原生工具调用时，解析文本中的 <function_calls> 格式
        # 同时检查 reasoning_content 中是否嵌入了工具调用
        _tool_calls_from_reasoning = False
        combined_for_check = text_content
        # reasoning_content: DeepSeek/Kimi 等使用 reasoning_content 字段
        # reasoning: OpenRouter 使用 reasoning 字段（字符串或包含 content 的对象）
        reasoning_content = message.get("reasoning_content") or ""
        if not reasoning_content:
            _or_reasoning = message.get("reasoning")
            if isinstance(_or_reasoning, str) and _or_reasoning:
                reasoning_content = _or_reasoning
            elif isinstance(_or_reasoning, dict):
                reasoning_content = _or_reasoning.get("content", "") or ""
        # 收集 content 数组中的 thinking 块到 reasoning_content (#415)
        if _thinking_from_content:
            _joined = "\n".join(_thinking_from_content)
            reasoning_content = reasoning_content + "\n" + _joined if reasoning_content else _joined
            logger.info(
                f"[PARSE] Extracted {len(_thinking_from_content)} thinking block(s) "
                f"({len(_joined)} chars) from content array into reasoning_content"
            )
        if not has_tool_calls and not text_content and reasoning_content:
            if has_text_tool_calls(reasoning_content):
                combined_for_check = reasoning_content
                _tool_calls_from_reasoning = True
                logger.info(
                    f"[TEXT_TOOL_PARSE] Detected tool calls embedded in reasoning_content from {self.name}"
                )

        if not has_tool_calls and combined_for_check and has_text_tool_calls(combined_for_check):
            logger.info(f"[TEXT_TOOL_PARSE] Detected text-based tool calls from {self.name}")
            clean_text, text_tool_calls = parse_text_tool_calls(combined_for_check)

            if text_tool_calls:
                if _tool_calls_from_reasoning:
                    if clean_text.strip():
                        text_content = clean_text
                        logger.info(
                            f"[TEXT_TOOL_PARSE] Preserved {len(clean_text)} chars of clean_text "
                            f"from reasoning_content"
                        )
                else:
                    text_content = clean_text
                content_blocks.extend(text_tool_calls)
                has_tool_calls = True
                logger.info(
                    f"[TEXT_TOOL_PARSE] Extracted {len(text_tool_calls)} tool calls "
                    f"from {'reasoning_content' if _tool_calls_from_reasoning else 'text'}"
                )

        # ── pull usage early so empty-content fallbacks below can reference token counts ──
        usage_data = data.get("usage", {})
        _out_tokens = int(
            usage_data.get("output_tokens") or usage_data.get("completion_tokens") or 0
        )

        # Reasoning 模型容错：content 为空但 reasoning 有内容
        # 当 reasoning 模型被 max_tokens 截断时，所有输出可能都在 reasoning 字段，
        # content 为空。此时尝试从 reasoning 中提取结构化内容作为兜底。
        if not text_content and not has_tool_calls and reasoning_content:
            import re

            yaml_match = re.search(
                r"```(?:yaml)?\s*\n(.+?)```",
                reasoning_content,
                re.DOTALL,
            )
            if yaml_match:
                text_content = yaml_match.group(1).strip()
                logger.warning(
                    f"[PARSE] content is empty but found structured data in reasoning "
                    f"({len(text_content)} chars extracted from {len(reasoning_content)} chars reasoning)"
                )
            else:
                # [fix 2026-10-17] 截断的思考碎片（finish=length 且 reasoning 很短）
                # 只是模型思考到一半被 max_tokens 切断，不是可用回复：
                # 不提升为可见文本（避免把 "Here's a thinking process:" 当答案），
                # 保留 reasoning_content 供调用方（如健康检查）作为"已响应"信号。
                _finish_reason = (
                    choice.get("finish_reason") if isinstance(choice, dict) else ""
                )
                # [fix 2026-10-18] 短思考碎片（<200 字符）无论 finish_reason 均不提升：
                # 例如 31 字符的思考过程不可能是可用回复，
                # 避免每次健康/探测请求触发 WARN 刷屏。
                _short_reasoning = len(reasoning_content) < 200
                _truncated_fragment = _finish_reason == "length" and _short_reasoning
                if _truncated_fragment or _short_reasoning:
                    logger.info(
                        f"[PARSE] reasoning-only fragment from {self.name} "
                        f"({len(reasoning_content)} chars, finish={_finish_reason or '?'}): "
                        f"content empty, reasoning kept as reasoning_content, "
                        f"not promoted as visible text"
                    )
                    # 不修改 text_content / reasoning_content / content_blocks
                else:
                    # 1. 把 reasoning 全文作为 visible text fallback (优于直接放弃)
                    text_content = reasoning_content
                    reasoning_content = ""
                    content_blocks.insert(0, TextBlock(text=text_content))
                    logger.warning(
                        f"[PARSE] content is empty; using reasoning_content "
                        f"({len(text_content)} chars) as visible text fallback from {self.name}"
                    )

        # 非标准 OpenAI-compatible 代理容错：有 token 但 message.content 为空时，
        # 不要求一定存在 reasoning_content，尽量从其他常见字段恢复可见文本。
        # [fix 2026-10-17] 截断思考碎片场景已明确保留 reasoning_content 且不提升，
        # 此处跳过，避免 _recover_empty_content_text 又把 reasoning 重新提升为可见文本。
        recovered_from: str = ""
        if (
            not text_content
            and not has_tool_calls
            and not content_blocks
            and not reasoning_content
            and _out_tokens > 0
        ):
            recovered_source, recovered_text = self._recover_empty_content_text(
                message, choice, data
            )
            if recovered_text:
                text_content = recovered_text
                content_blocks.insert(0, TextBlock(text=text_content))
                recovered_from = recovered_source
                # PR-C2: 已经成功恢复，不要打 ERROR；INFO 级足够运维观察
                logger.info(
                    f"[PARSE] auto-recovered {len(recovered_text)} chars from {recovered_source} "
                    f"(content empty, {_out_tokens} output tokens, endpoint={self.name})"
                )

        # ── 本地 llama 冷启动横幅防护 ──
        # llama-server / llama-cli 冷启动时可能把 "Loading model..." 横幅 +
        # 提示词回显当作响应内容（NativeLlamaProvider 降级路径），这类文本
        # 不是模型回复：剥离横幅后若没有真实内容则整体丢弃，避免 ReAct
        # 把启动横幅当成 final_answer 发给用户。
        if text_content and _looks_like_llama_banner(text_content):
            _orig_banner = text_content
            _cleaned_banner = _sanitize_local_llama_output(_orig_banner)
            # 移除已插入的横幅块（reasoning fallback / auto-recover 路径可能已插入）
            content_blocks = [
                b
                for b in content_blocks
                if not (
                    isinstance(b, TextBlock)
                    and (b.text == _orig_banner or _looks_like_llama_banner(b.text))
                )
            ]
            if _cleaned_banner:
                logger.warning(
                    f"[PARSE] Stripped llama startup banner from {self.name} "
                    f"({len(_orig_banner)} -> {len(_cleaned_banner)} chars)"
                )
                text_content = _cleaned_banner
                reasoning_content = ""
            else:
                logger.warning(
                    f"[PARSE] Dropped llama startup banner from {self.name} "
                    f"({len(_orig_banner)} chars, no real content)"
                )
                text_content = ""
                reasoning_content = ""

        # Add recovered/plain text before diagnosing content loss.  The previous
        # order logged false CONTENT LOST errors whenever message.content was a
        # plain string that had not yet been converted into a TextBlock.
        if text_content and not any(
            isinstance(b, TextBlock) and b.text == text_content for b in content_blocks
        ):
            content_blocks.insert(0, TextBlock(text=text_content))

        # 仍然为空 → 记录详细诊断信息（帮助定位代理格式变化）
        # [fix 2026-10-17] reasoning-only 响应（content 空但 reasoning 有值）是
        # 推理模型的正常形态，不是 CONTENT LOST；跳过诊断，避免告警刷屏。
        if not content_blocks and _out_tokens > 0 and not reasoning_content:
            msg_keys = sorted(k for k in message if k != "role")
            msg_preview = {
                k: (
                    str(v)[:200]
                    if isinstance(v, str)
                    else f"[{type(v).__name__}, len={len(v)}]"
                    if isinstance(v, (list, dict))
                    else str(v)[:100]
                )
                for k, v in message.items()
                if k != "role"
            }
            _extra_keys = sorted(
                k
                for k in data
                if k
                not in (
                    "id",
                    "object",
                    "created",
                    "model",
                    "choices",
                    "usage",
                    "system_fingerprint",
                )
            )
            _choice_keys = sorted(
                k for k in choice if k not in ("message", "index", "finish_reason", "logprobs")
            )
            _token_details = usage_data.get("completion_tokens_details")
            # PR-C2: 降级为 WARN（不再误触发 endpoint cooldown）
            logger.warning(
                f"[PARSE] CONTENT LOST: {_out_tokens} output tokens but content_blocks "
                f"is empty from {self.name}. message keys={msg_keys}, "
                f"preview={msg_preview}, "
                f"extra_data_keys={_extra_keys}, extra_choice_keys={_choice_keys}, "
                f"token_details={_token_details}"
            )
            # 附加原始响应摘要供 llm_debug 保存
            self._last_raw_diagnostic = {
                "endpoint": self.name,
                "data_keys": sorted(data.keys()),
                "choice_keys": sorted(choice.keys()),
                "message_keys": msg_keys,
                "message_preview": msg_preview,
                "extra_data_keys": _extra_keys,
                "extra_choice_keys": _choice_keys,
                "token_details": _token_details,
                "usage": usage_data,
            }
            # PR-C3: 把完整原始响应 dump 到 data/llm_debug/empty_response_*.json
            # 供后续根因分析或向 dashscope 提工单。受 feature flag 控制。
            try:
                from ...core.feature_flags import is_enabled as _ff_enabled

                if _ff_enabled("openai_empty_response_dump_v1"):
                    self._dump_empty_response(data)
            except Exception:
                pass

        # 解析停止原因
        finish_reason = choice.get("finish_reason", "stop")
        if has_tool_calls and finish_reason == "length":
            # finish_reason=length + tool_calls = 输出被截断，工具参数可能不完整
            stop_reason = StopReason.MAX_TOKENS
        elif has_tool_calls:
            stop_reason = StopReason.TOOL_USE
        else:
            stop_reason_map = {
                "stop": StopReason.END_TURN,
                "length": StopReason.MAX_TOKENS,
                "tool_calls": StopReason.TOOL_USE,
                "function_call": StopReason.TOOL_USE,
            }
            stop_reason = stop_reason_map.get(finish_reason, StopReason.END_TURN)

        usage = Usage(**_parse_openai_usage(usage_data))

        return LLMResponse(
            id=data.get("id", ""),
            content=content_blocks,
            stop_reason=stop_reason,
            usage=usage,
            model=data.get("model", self.config.model),
            reasoning_content=reasoning_content,
            recovered_from=recovered_from,
        )

    def _dump_empty_response(self, data: dict) -> None:
        """PR-C3: 把无可恢复内容的 raw response 写到 llm_debug 便于排查。"""
        try:
            from datetime import datetime

            from ...config import settings as _settings

            debug_dir = _settings.project_root / "data" / "llm_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = debug_dir / f"empty_response_{self.name}_{ts}.json"
            payload = {
                "endpoint": self.name,
                "model": self.config.model,
                "raw_response": data,
            }
            filename.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info(f"[PARSE] Empty response dumped to {filename}")
        except Exception as exc:
            logger.debug(f"[PARSE] dump empty_response failed: {exc}")

    def _convert_stream_event(self, event: dict) -> dict | list[dict]:
        """转换流式事件为统一格式。

        同一个 chunk 可能同时携带 reasoning_content + content + finish_reason
        （DeepSeek 等模型的特殊行为），因此返回 dict 或 list[dict]。
        """
        choices = event.get("choices", [])
        if not choices:
            usage = event.get("usage")
            if usage:
                return {
                    "type": "message_delta",
                    "delta": {},
                    "usage": _parse_openai_usage(usage),
                }
            return {"type": "ping"}

        choice = choices[0]
        delta = choice.get("delta", {})
        events: list[dict] = []

        # 1) Thinking: reasoning_content (DeepSeek R1, Qwen3) / reasoning
        # (OpenRouter) plus common proxy variants.
        reasoning = (
            _extract_reasoning_delta(delta.get("reasoning_content"))
            or _extract_reasoning_delta(delta.get("reasoning"))
            or _extract_reasoning_delta(delta.get("reasoning_delta"))
            or _extract_reasoning_delta(delta.get("reasoning_details"))
            or _extract_reasoning_delta(event.get("reasoning_content"))
            or _extract_reasoning_delta(event.get("reasoning"))
        )
        if reasoning:
            events.append(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking", "text": reasoning},
                }
            )

        # 2) Text content
        if delta.get("content"):
            events.append(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text", "text": delta["content"]},
                }
            )

        # 3) Tool calls
        if "tool_calls" in delta:
            tool_calls = delta["tool_calls"]
            if tool_calls:
                tc = tool_calls[0]
                d = {
                    "type": "tool_use",
                    "id": tc.get("id"),
                    "name": tc.get("function", {}).get("name"),
                    "arguments": tc.get("function", {}).get("arguments"),
                }
                extra = tc.get("extra_content")
                if extra:
                    d["extra_content"] = extra
                events.append(
                    {
                        "type": "content_block_delta",
                        "delta": d,
                    }
                )

        # 4) Finish reason → message_stop
        if choice.get("finish_reason"):
            stop_evt = {
                "type": "message_stop",
                "stop_reason": choice["finish_reason"],
            }
            chunk_usage = event.get("usage")
            if chunk_usage:
                stop_evt["usage"] = _parse_openai_usage(chunk_usage)
            events.append(stop_evt)

        if not events:
            return {"type": "ping"}
        return events[0] if len(events) == 1 else events

    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
