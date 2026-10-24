"""流式语音合成 —— 迁移自 hermes-agent ``tools/tts_streaming.py``（按 OpenKitsune 架构瘦身）。

能力:
1. :class:`SentenceChunker` —— 面向 LLM token delta 的增量句子切分器（剔除推理块、
   合并过短片段），语音按句切分，首句即播、不必等全篇合成。
2. :class:`StreamingTTSProvider` ABC + 注册表 —— 支持输出原始 PCM 的引擎
   （openai / gemini / elevenlabs / xai），``stream()`` 产出 int16 mono PCM 块。
3. :func:`stream_tts_to_speaker` —— 高层入口：
   - 配置引擎支持 PCM 流式 → 边合成边播放（sounddevice）；
   - 无分块 API 的引擎（edge 默认）→ 按句子走同步合成路径逐句播放。
4. 抢话闩锁 :func:`mark_speech_interrupted` / :func:`take_speech_interrupted` ——
   打断标记供下一轮对话注入上下文（TTL 防陈旧标记污染无关消息）。

依赖均为可选：sounddevice/numpy（播放）、openai/elevenlabs/websockets（对应流式引擎）。
"""
from __future__ import annotations

import logging
import queue
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any

from .config import get_tts_config
from .tts import synthesize_text

logger = logging.getLogger(__name__)

# 每句 PCM 字节上限（与同步引擎 16MiB 有界响应一致）
_STREAM_SENTENCE_BYTE_CAP = 16 * 1024 * 1024

# ---- 抢话闩锁 ----
SPEECH_INTERRUPTED_NOTE = "[Note: the user interrupted your previous spoken reply before it finished.]"
_INTERRUPT_TTL_S = 120.0
_interrupted_at: float | None = None


def mark_speech_interrupted() -> None:
    """标记一次语音打断（TTS 播放被 barge-in 切断时调用）。"""
    global _interrupted_at
    _interrupted_at = time.monotonic()


def take_speech_interrupted() -> bool:
    """弹出闩锁；TTL 内发生过打断返回 True。"""
    global _interrupted_at
    at, _interrupted_at = _interrupted_at, None
    return at is not None and time.monotonic() - at < _INTERRUPT_TTL_S


# 句子边界：
# - ASCII .!? 后接空白/换行；
# - 中文 。！？ 后接任何后续字符（CJK 文本通常无空白分隔，直接按句读断开，
#   支持后跟引号/括号/换行/结尾）；
# - 空行（段落级边界）。
SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])(?:\s|\n)"
    r"|(?<=[。！？])(?=[\u4e00-\u9fff0-9A-Za-z“”‘’\"'（）()【】「」『』《》…—]|\s|\n|$)"
    r"|(?:\n\n)"
)
# 推理块标签（与 OpenKitsune 提示模板中的推理标签对齐；可按需扩展）
_THINK_TAG_NAMES = ("think", "thinking", "reasoning", "analysis")
_THINK_NAMES = "|".join(re.escape(name) for name in _THINK_TAG_NAMES)
_THINK_BLOCK_RE = re.compile(rf"<({_THINK_NAMES})[\s>].*?</\1>", flags=re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(rf"<(?:{_THINK_NAMES})(?=[\s>]|$)", flags=re.IGNORECASE)


class SentenceChunker:
    """增量句子切分器：吸收 LLM token delta，返回已完整、可立即朗读的句子。

    剔除 ``<think>`` 等推理块（即使跨 delta 拆分也能匹配），短于 *min_len* 的
    片段并入下一句。*min_len* 默认 20 适合英文；中文短句（5-7 字）即可成句，
    语音场景可配置调低以让首句独立朗读。
    """

    def __init__(self, min_len: int = 20) -> None:
        self.min_len = min_len
        self.buf = ""

    @classmethod
    def from_config(cls, tts_config: dict) -> SentenceChunker:
        """读取 ``tts.streaming.min_len``（下限 1）。"""
        try:
            return cls(min_len=max(1, int((tts_config.get("streaming") or {}).get("min_len", 20))))
        except (AttributeError, TypeError, ValueError):
            return cls()

    def feed(self, delta: str) -> list[str]:
        """吸收 *delta*，返回此刻可朗读的完整句子列表。"""
        self.buf = _THINK_BLOCK_RE.sub("", self.buf + delta)
        if _THINK_OPEN_RE.search(self.buf):
            return []  # 推理块未闭合——闭合标签可能在下个 delta 到达
        out: list[str] = []
        start = 0
        while m := SENTENCE_BOUNDARY_RE.search(self.buf, start):
            head = self.buf[: m.end()]
            if len(head.strip()) < self.min_len:
                start = m.end()
                continue
            out.append(head)
            self.buf = self.buf[m.end():]
            start = 0
        return out

    def flush(self) -> list[str]:
        """排空尾部（文本结束或长空闲冲刷）；不朗读未闭合推理块。"""
        tail, self.buf = _THINK_BLOCK_RE.sub("", self.buf), ""
        if m := _THINK_OPEN_RE.search(tail):
            tail = tail[: m.start()]
        tail = tail.strip()
        return [tail] if tail else []


class StreamingTTSProvider(ABC):
    """产出 int16 小端 mono PCM 块的流式引擎。

    ``sample_rate`` 在 ``stream()`` 产出首个分块前是暂定值：引擎可在收到上游
    真实格式后更新实例属性，调用方应在拉取首个分块后再打开输出设备/写 WAV 头。
    """

    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2  # bytes/sample (int16)

    def __init__(self, tts_config: dict, section: dict) -> None:
        self.tts_config = tts_config
        self.section = section

    @staticmethod
    @abstractmethod
    def available() -> bool:
        """当前凭据/SDK 可用即 True。"""

    @abstractmethod
    def stream(self, text: str) -> Iterator[bytes]:
        """为 *text* 产出 PCM 块；失败抛异常（调用方记录）。"""


_REGISTRY: dict[str, type[StreamingTTSProvider]] = {}


def register(name: str) -> Callable[[type[StreamingTTSProvider]], type[StreamingTTSProvider]]:
    def _wrap(cls: type[StreamingTTSProvider]) -> type[StreamingTTSProvider]:
        _REGISTRY[name] = cls
        return cls
    return _wrap


def _try_instantiate(name: str, tts_config: dict) -> StreamingTTSProvider | None:
    cls = _REGISTRY.get(name)
    if cls is None or not cls.available():
        return None
    try:
        return cls(tts_config, tts_config.get(name) or {})
    except Exception as exc:  # pragma: no cover - 防御性
        logger.debug("streaming provider %s init failed: %s", name, exc)
        return None


# ``tts.streaming.provider: auto`` 的优先级（分块延迟/质量优先；edge 无分块 PCM API）
_PROVIDER_PRIORITY: list[str] = ["elevenlabs", "gemini", "openai", "xai"]


def resolve_streaming_provider(
    tts_config: dict, preferred: str | None = None,
) -> StreamingTTSProvider | None:
    """返回配置引擎的可用于流式的引擎；None 表示“无分块 API”——上层走逐句同步路径。

    ``tts.streaming.provider`` 为固定名时钉住该引擎（不可用即 None）；
    ``auto`` 按 ``_PROVIDER_PRIORITY`` 取第一个可用；未配置则取当前 TTS provider
    （或 *preferred*）。绝不静默换引擎来换取流式。
    """
    from .tts import get_tts_provider
    pinned = str((tts_config.get("streaming") or {}).get("provider") or "").lower().strip()
    if pinned == "auto":
        for name in _PROVIDER_PRIORITY:
            if (inst := _try_instantiate(name, tts_config)) is not None:
                return inst
        return None
    name = pinned or (preferred or get_tts_provider(tts_config)).lower().strip()
    return _try_instantiate(name, tts_config)


def _capped(chunks: Iterator[bytes], label: str) -> Iterator[bytes]:
    """透传分块，越过每句字节上限即截断（防失控上游）。"""
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > _STREAM_SENTENCE_BYTE_CAP:
            logger.warning("%s exceeded %d bytes for one sentence; truncating", label, _STREAM_SENTENCE_BYTE_CAP)
            return
        yield chunk


def _resolve_key(env_var: str, provider_id: str) -> str:
    """provider 密钥解析（config[tts.<provider>.api_key] > 环境变量）。"""
    from .config import resolve_provider_key
    return resolve_provider_key(env_var, provider_id)


@register("elevenlabs")
class ElevenLabsStreamer(StreamingTTSProvider):
    """ElevenLabs 分块 HTTP → ``pcm_24000``。"""

    @staticmethod
    def available() -> bool:
        return bool(_resolve_key("ELEVENLABS_API_KEY", "elevenlabs"))

    def stream(self, text: str) -> Iterator[bytes]:
        from .config import DEFAULT_ELEVENLABS_MODEL_ID, DEFAULT_ELEVENLABS_VOICE_ID
        from .tts_providers import _elevenlabs_environment_kwargs, _import_elevenlabs
        client = _import_elevenlabs()(
            api_key=_resolve_key("ELEVENLABS_API_KEY", "elevenlabs"),
            **_elevenlabs_environment_kwargs(self.section))
        yield from client.text_to_speech.convert(
            text=text, voice_id=self.section.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID),
            model_id=self.section.get("streaming_model_id",
                                      self.section.get("model_id", DEFAULT_ELEVENLABS_MODEL_ID)),
            output_format="pcm_24000")


def _sample_rate_from_headers(headers) -> int | None:
    """OpenAI 兼容端点广告的采样率：``X-Audio-Sample-Rate`` 或 Content-Type ``rate=``。"""
    if not headers:
        return None
    raw = headers.get("x-audio-sample-rate")
    if raw is None:
        m = re.search(r"(?:^|[;\s])rate\s*=\s*(\d+)", str(headers.get("content-type") or ""), re.IGNORECASE)
        raw = m.group(1) if m else None
    try:
        rate = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


@register("openai")
class OpenAIStreamer(StreamingTTSProvider):
    """OpenAI ``speech`` with ``response_format=pcm``（官方 24 kHz mono int16）。

    兼容服务器可能返回其它采样率：``tts.openai.pcm_sample_rate`` 预设期望值，
    响应头（``X-Audio-Sample-Rate`` / Content-Type ``rate=``）在产出首块前覆盖。
    """

    def __init__(self, tts_config: dict, section: dict) -> None:
        super().__init__(tts_config, section)
        configured = section.get("pcm_sample_rate", self.sample_rate)
        if (isinstance(configured, bool) or not isinstance(configured, (int, float, str))
                or not str(configured).strip().isdigit() or int(str(configured).strip()) <= 0):
            logger.warning("Invalid tts.openai.pcm_sample_rate %r; using %d Hz", configured, self.sample_rate)
        else:
            self.sample_rate = int(str(configured).strip())

    @staticmethod
    def available() -> bool:
        return bool(_resolve_key("OPENAI_API_KEY", "openai") or _resolve_key("VOICE_TOOLS_OPENAI_KEY", "openai"))

    def stream(self, text: str) -> Iterator[bytes]:
        from openai import OpenAI

        from .tts_providers import DEFAULT_OPENAI_BASE_URL
        api_key = (self.section.get("api_key")
                   or _resolve_key("OPENAI_API_KEY", "openai")
                   or _resolve_key("VOICE_TOOLS_OPENAI_KEY", "openai"))
        base_url = self.section.get("base_url") or DEFAULT_OPENAI_BASE_URL
        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            with client.audio.speech.with_streaming_response.create(
                model=self.section.get("model", "gpt-4o-mini-tts"),
                voice=self.section.get("voice", "alloy"),
                input=text, response_format="pcm",
            ) as response:
                rate = _sample_rate_from_headers(getattr(response, "headers", None))
                if rate is not None and rate != self.sample_rate:
                    logger.info("TTS endpoint reports %d Hz PCM (expected %d Hz); honoring it",
                                rate, self.sample_rate)
                    self.sample_rate = rate
                yield from _capped(response.iter_bytes(), "OpenAI streaming TTS")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()


@register("gemini")
class GeminiStreamer(StreamingTTSProvider):
    """Gemini ``streamGenerateContent?alt=sse`` → SSE base64 PCM 块（24 kHz），有界流式体。"""

    @staticmethod
    def available() -> bool:
        return bool(_resolve_key("GEMINI_API_KEY", "gemini") or _resolve_key("GOOGLE_API_KEY", "gemini"))

    def stream(self, text: str) -> Iterator[bytes]:
        import base64
        import json as _json

        import requests

        from .config import get_env_value
        from .tts_providers import (
            DEFAULT_GEMINI_TTS_BASE_URL,
            DEFAULT_GEMINI_TTS_MODEL,
            DEFAULT_GEMINI_TTS_VOICE,
        )
        api_key = (_resolve_key("GEMINI_API_KEY", "gemini") or _resolve_key("GOOGLE_API_KEY", "gemini"))
        model = str(self.section.get("model", DEFAULT_GEMINI_TTS_MODEL)).strip() or DEFAULT_GEMINI_TTS_MODEL
        voice = str(self.section.get("voice", DEFAULT_GEMINI_TTS_VOICE)).strip() or DEFAULT_GEMINI_TTS_VOICE
        base_url = str(self.section.get("base_url") or get_env_value("GEMINI_BASE_URL")
                       or DEFAULT_GEMINI_TTS_BASE_URL).strip().rstrip("/")
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
        url = f"{base_url}/models/{model}:streamGenerateContent"

        def _sse_chunks() -> Iterator[bytes]:
            with requests.post(url, params={"alt": "sse", "key": api_key}, json=payload,
                               timeout=60, stream=True) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        parts = _json.loads(line[len("data: "):])["candidates"][0]["content"]["parts"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    for part in parts:
                        b64 = (part.get("inlineData") or part.get("inline_data") or {}).get("data", "")
                        if not b64:
                            continue
                        try:
                            yield base64.b64decode(b64)
                        except (ValueError, TypeError) as exc:
                            logger.warning("Gemini SSE: bad base64 audio: %s", exc)

        yield from _capped(_sse_chunks(), "Gemini streaming TTS")


@register("xai")
class XAIStreamer(StreamingTTSProvider):
    """xAI WebSocket TTS → base64 PCM ``audio.delta`` 帧（24 kHz mono int16）。

    协议：voice/language/codec/sample_rate 走 URL query；发送 ``text.delta`` +
    ``text.done``；服务器流式 JSON ``audio.delta``（``delta`` 为 base64 PCM）直至
    ``audio.done``。异步 WS 循环跑在后台线程喂队列，``stream()`` 边到边出。
    """

    sample_rate = 24000
    _RECV_TIMEOUT_S = 60

    @staticmethod
    def available() -> bool:
        return bool(_resolve_key("XAI_API_KEY", "xai"))

    def stream(self, text: str) -> Iterator[bytes]:
        yield from self._queued_frames(text)

    def _queued_frames(self, text: str) -> Iterator[bytes]:
        import asyncio
        import queue
        import threading

        q: queue.Queue[object] = queue.Queue(maxsize=64)
        done = object()
        stop = threading.Event()

        def _put(item: object) -> bool:
            while not stop.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def _pump_thread() -> None:
            try:
                asyncio.run(self._pump(text, q))
            except BaseException as exc:  # 交给消费侧
                _put(exc)
            finally:
                _put(done)

        threading.Thread(target=_pump_thread, name="xai-tts-pump", daemon=True).start()
        try:
            while True:
                item = q.get()
                if item is done:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop.set()

    async def _pump(self, text: str, q) -> None:
        import asyncio
        import base64
        import json as _json
        from urllib.parse import urlencode

        import websockets

        api_key = _resolve_key("XAI_API_KEY", "xai")
        if not api_key:
            raise RuntimeError("No xAI credentials for streaming TTS")
        voice = str(self.section.get("voice_id", "eve")).strip() or "eve"
        language = str(self.section.get("language", "en")).strip() or "en"
        base = str(self.section.get("streaming_url") or "wss://api.x.ai/v1/tts").strip()
        params = urlencode({"voice": voice, "language": language, "codec": "pcm",
                            "sample_rate": self.sample_rate})
        sep = "&" if "?" in base else "?"
        ws_url = f"{base}{sep}{params}"

        def _put(item: object) -> bool:
            while True:
                try:
                    q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue

        async with websockets.connect(ws_url, additional_headers={"Authorization": f"Bearer {api_key}"}) as ws:
            await ws.send(_json.dumps({"type": "text.delta", "delta": text}))
            await ws.send(_json.dumps({"type": "text.done"}))
            enqueued = 0
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=self._RECV_TIMEOUT_S)
                except TimeoutError:
                    raise RuntimeError(f"xAI streaming TTS: no audio for {self._RECV_TIMEOUT_S}s")
                except websockets.exceptions.ConnectionClosedOK:
                    return
                except websockets.exceptions.ConnectionClosedError as exc:
                    raise RuntimeError(f"xAI WS closed mid-stream: {exc}") from exc
                if isinstance(message, (bytes, bytearray, memoryview)):
                    continue
                try:
                    envelope = _json.loads(message)
                except (ValueError, TypeError):
                    continue
                msg_type = envelope.get("type")
                if msg_type == "audio.delta":
                    b64 = envelope.get("delta") or ""
                    if b64:
                        pcm = base64.b64decode(b64)
                        enqueued += len(pcm)
                        if enqueued > _STREAM_SENTENCE_BYTE_CAP:
                            logger.warning("xAI streaming TTS exceeded %d bytes; closing upstream",
                                           _STREAM_SENTENCE_BYTE_CAP)
                            return
                        if not _put(pcm):
                            return
                elif msg_type == "audio.done":
                    return
                elif msg_type == "error":
                    detail = envelope.get("message") or envelope.get("error") or envelope
                    raise RuntimeError(f"xAI streaming TTS error: {detail}")


# ── 播放 ──
def _import_audio():
    import numpy  # noqa: F401
    import sounddevice as sd
    return sd, numpy


def play_pcm(pcm: bytes, sample_rate: int) -> bool:
    """播放 raw int16 PCM（sounddevice 阻塞线程）；失败返回 False。"""
    try:
        sd, np = _import_audio()
    except (ImportError, OSError):
        return False
    try:
        data = np.frombuffer(pcm, dtype=np.int16)
        sd.play(data, sample_rate)
        sd.wait()
        return True
    except Exception as e:
        logger.debug("PCM playback failed: %s", e)
        return False


def _play_file_or_pcm(path: str) -> bool:
    from .vad import play_audio_file
    try:
        return play_audio_file(path)
    except Exception as e:
        logger.debug("file playback failed: %s", e)
        return False


# ── 高层入口 ──
def stream_tts_to_speaker(
    text: str,
    tts_config: dict | None = None,
    on_sentence: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """流式朗读 *text* 并返回播放明细。

    策略：
    - 配置引擎支持 PCM 流式（openai/gemini/elevenlabs/xai）→ 逐块边合成边播放；
    - 无分块 API 的引擎（edge 默认）→ ``SentenceChunker`` 按句切分，逐句走
      同步 ``synthesize_text`` 合成并立即播放（首句即出）。
    - *should_stop* 置真时停止后续句子/分块（抢话打断场景）。
    - *on_sentence* 在每句开始朗读前回调（用于界面显示“正在朗读…”）。

    返回 ``{"spoken": [{"text":..,"path":..|None}], "provider":.., "interrupted": bool}``。
    """
    cfg = tts_config if tts_config is not None else get_tts_config()
    from .tts import get_tts_provider
    provider = get_tts_provider(cfg)
    stop = should_stop or (lambda: False)
    spoken: list[dict[str, Any]] = []

    # 路径 1：PCM 流式引擎
    streamer = resolve_streaming_provider(cfg, preferred=provider)
    if streamer is not None and not stop():
        logger.info("Streaming TTS via %s (%d Hz)", streamer.__class__.__name__, streamer.sample_rate)

        chunks: list[bytes] = []
        rate = streamer.sample_rate
        try:
            for chunk in streamer.stream(text):
                if stop():
                    break
                if not chunks:
                    rate = streamer.sample_rate  # 引擎可能在首块前更新采样率
                    mark_speech_interrupted()
                if on_sentence and not chunks:
                    on_sentence(text)
                chunks.append(chunk)
                if len(chunks) >= 8:  # 攒 8 块（约 2-3s）播放一次，降低播放线程压力
                    play_pcm(b"".join(chunks), rate)
                    chunks = []
        except Exception as e:
            logger.warning("Streaming TTS failed mid-stream: %s", e)
        if chunks and not stop():
            play_pcm(b"".join(chunks), rate)
        interrupted = stop()
        if interrupted:
            mark_speech_interrupted()
        spoken.append({"text": text, "path": None})
        return {"spoken": spoken, "provider": provider, "interrupted": interrupted}

    # 路径 2：逐句同步合成（edge 及所有无分块 API 引擎）
    chunker = SentenceChunker.from_config(cfg)
    sentences = [*chunker.feed(text), *chunker.flush()]
    interrupted = False
    for sentence in sentences:
        if stop():
            interrupted = True
            mark_speech_interrupted()
            break
        if on_sentence:
            on_sentence(sentence)
        try:
            result = synthesize_text(sentence, provider=provider, tts_config=cfg)
            played = False
            for path in result["paths"]:
                if _play_file_or_pcm(path):
                    played = True
            spoken.append({"text": sentence, "path": (result["paths"] or [None])[0], "played": played})
        except Exception as e:
            logger.warning("Sentence TTS failed (%s): %s", provider, e)
            spoken.append({"text": sentence, "path": None, "error": str(e)})
    return {"spoken": spoken, "provider": provider, "interrupted": interrupted}
