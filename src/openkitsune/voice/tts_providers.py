"""TTS 多引擎合成 —— 迁移自 hermes-agent ``tools/tts_tool_providers.py`` / ``tools/tts_tool_openai.py``。

各 ``_generate_<provider>(text, output_path, tts_config)`` 写一个最终编码文件。
包含上游响应有界读取（16MiB 上限防恶意端点喂无限音频）、迷你等云引擎实现，
以及本地引擎（piper/kittentts/neutts）的统一封装入口。
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import re
import uuid
from typing import Any

from . import audio
from .config import (
    DEFAULT_DEEPINFRA_TTS_VOICE,
    DEFAULT_EDGE_VOICE,
    DEFAULT_ELEVENLABS_MODEL_ID,
    DEFAULT_ELEVENLABS_VOICE_ID,
    DEFAULT_GEMINI_TTS_BASE_URL,
    DEFAULT_GEMINI_TTS_MODEL,
    DEFAULT_GEMINI_TTS_VOICE,
    DEFAULT_MINIMAX_BASE_URL,
    DEFAULT_MINIMAX_CN_BASE_URL,
    DEFAULT_MINIMAX_MODEL,
    DEFAULT_MINIMAX_VOICE_ID,
    DEFAULT_MISTRAL_TTS_MODEL,
    DEFAULT_MISTRAL_TTS_VOICE_ID,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_VOICE,
    DEFAULT_XAI_VOICE_ID,
    config_bool,
    get_env_value,
    resolve_provider_key,
)

logger = logging.getLogger(__name__)

TTS_RESPONSE_BODY_LIMIT_BYTES = 16 * 1024 * 1024
TTS_RESPONSE_BODY_CHUNK_BYTES = 64 * 1024


def _require_key(env_var: str, provider_id: str, hint: str) -> str:
    """按 env 解析 API key；缺失抛 ValueError。"""
    api_key = resolve_provider_key(env_var, provider_id) or ""
    if not api_key:
        raise ValueError(f"{env_var} not set. {hint}")
    return api_key


def _tts_response_format_from_path(output_path: str) -> str:
    """按输出扩展名选择 OpenAI 风格 response format。"""
    formats = ((".ogg", "opus"), (".wav", "wav"), (".flac", "flac"))
    return next((fmt for ext, fmt in formats if output_path.endswith(ext)), "mp3")


# ---- 有界上游响应读取 ----
def _response_has_explicit_stream(response: Any) -> bool:
    if not callable(getattr(response, "iter_content", None)):
        return False
    response_type = type(response)
    return response_type.__module__.startswith("requests.") or "iter_content" in vars(response_type)


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _read_tts_response_bytes(response: Any, *, label: str, limit: int | None = None) -> bytes:
    """有界读取上游 TTS 响应（硬字节上限）。"""
    limit = TTS_RESPONSE_BODY_LIMIT_BYTES if limit is None else limit
    chunks: list[bytes] = []
    total = 0
    try:
        if _response_has_explicit_stream(response):
            iterator = response.iter_content(chunk_size=TTS_RESPONSE_BODY_CHUNK_BYTES)
        else:
            content = vars(response).get("content", getattr(type(response), "content", b""))
            iterator = (content,) if isinstance(content, (str, bytes, bytearray)) else ()
        for chunk in iterator:
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            chunk = bytes(chunk)
            total += len(chunk)
            if total > limit:
                _close_response(response)
                raise RuntimeError(f"{label} response exceeds {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        _close_response(response)


def _parse_json_body(response: Any, raw: bytes) -> dict[str, Any]:
    if raw:
        return json.loads(raw.decode("utf-8"))
    if not _response_has_explicit_stream(response):
        json_reader = getattr(response, "json", None)
        if callable(json_reader):
            parsed = json_reader()
            return parsed if isinstance(parsed, dict) else {}
    return {}


def _read_tts_response_json(response: Any, *, label: str, limit: int | None = None) -> dict[str, Any]:
    return _parse_json_body(response, _read_tts_response_bytes(response, label=label, limit=limit))


def _write_bytes(output_path: str, audio_bytes: bytes) -> str:
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    return output_path


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], **extra: Any):
    import requests
    return requests.post(url, headers=headers, json=payload, timeout=60, stream=True, **extra)


# ---- Edge TTS（免费默认）----
def _import_edge_tts():
    import edge_tts
    return edge_tts


async def generate_edge_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """Edge TTS（微软神经语音，免费默认引擎）。

    语音未显式配置时按文本语言自动适配（中文 -> zh-CN-XiaoxiaoNeural，
    日文 -> ja-JP-NanamiNeural，其余英文默认），避免英文语音读中文抛
    ``NoAudioReceived``。可经 ``tts.edge.voice`` 显式固定。
    """
    edge_tts = _import_edge_tts()
    edge_config = tts_config.get("edge") if isinstance(tts_config, dict) and isinstance(
        tts_config.get("edge"), dict) else {}
    voice = edge_config.get("voice") or DEFAULT_EDGE_VOICE
    if not edge_config.get("voice"):
        voice = _auto_edge_voice(text, voice)
    speed = float(edge_config.get("speed", (tts_config or {}).get("speed", 1.0)))
    kwargs: dict[str, Any] = {"voice": voice}
    if speed != 1.0:
        kwargs["rate"] = f"{round((speed - 1.0) * 100):+d}%"
    await edge_tts.Communicate(text, **kwargs).save(output_path)
    return output_path


# 语言 -> edge 默认语音（未显式配置时自动适配；覆盖主流 CJK 与英文）
_EDGE_LANG_VOICES = {
    "zh": "zh-CN-XiaoxiaoNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-AriaNeural",
}


def _auto_edge_voice(text: str, fallback: str = DEFAULT_EDGE_VOICE) -> str:
    """按文本字符分布选 edge 语音：含中文 -> 中文，日文假名 -> 日文，韩文 -> 韩文，
    否则 fallback（英文默认）。"""

    han = kana = hangul = 0
    for ch in text[:2000]:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            han += 1
        elif 0x3040 <= cp <= 0x30FF:
            kana += 1
        elif 0xAC00 <= cp <= 0xD7AF:
            hangul += 1
    if han > 0:
        return _EDGE_LANG_VOICES["zh"]
    if kana > 0:
        return _EDGE_LANG_VOICES["ja"]
    if hangul > 0:
        return _EDGE_LANG_VOICES["ko"]
    return fallback


# ---- ElevenLabs ----
def _elevenlabs_environment_kwargs(el_config: dict[str, Any]) -> dict[str, Any]:
    """SDK 环境 kwargs（base_url/wss_url）；无 base_url 时 SDK 默认。"""
    base_url = (el_config.get("base_url") or "").rstrip("/")
    if not base_url:
        return {}
    from elevenlabs.environment import ElevenLabsEnvironment
    wss_url = (el_config.get("wss_url") or "").rstrip("/") or re.sub(r"^http", "ws", base_url)
    return {"environment": ElevenLabsEnvironment(base=base_url, wss=wss_url)}


def _import_elevenlabs():
    from elevenlabs import ElevenLabs
    return ElevenLabs


def generate_elevenlabs(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """ElevenLabs TTS。"""
    api_key = _require_key("ELEVENLABS_API_KEY", "elevenlabs", "Get one at https://elevenlabs.io/")
    el_config = tts_config.get("elevenlabs") if isinstance(tts_config, dict) else {}
    client = _import_elevenlabs()(api_key=api_key, **_elevenlabs_environment_kwargs(el_config))
    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=el_config.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID),
        model_id=el_config.get("model_id", DEFAULT_ELEVENLABS_MODEL_ID),
        output_format="opus_48000_64" if output_path.endswith(".ogg") else "mp3_44100_128")
    with open(output_path, "wb") as f:
        f.writelines(audio_generator)
    return output_path


# ---- xAI TTS（专用 /v1/tts 端点）----
DEFAULT_XAI_LANGUAGE = "en"
DEFAULT_XAI_SAMPLE_RATE = 24000
DEFAULT_XAI_BIT_RATE = 128000
DEFAULT_XAI_AUTO_SPEECH_TAGS = False
DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_XAI_SPEED_MIN, DEFAULT_XAI_SPEED_MAX, DEFAULT_XAI_SPEED_DEFAULT = 0.7, 1.5, 1.0
DEFAULT_XAI_OPTIMIZE_STREAMING_LATENCY_DEFAULT = 0
DEFAULT_XAI_TEXT_NORMALIZATION_DEFAULT = False

_XAI_INLINE_SPEECH_TAGS = (
    "pause", "long-pause", "hum-tune", "laugh", "chuckle", "giggle", "cry", "tsk",
    "tongue-click", "lip-smack", "breath", "inhale", "exhale", "sigh")
_XAI_WRAPPING_SPEECH_TAGS = (
    "soft", "whisper", "loud", "build-intensity", "decrease-intensity", "higher-pitch",
    "lower-pitch", "slow", "fast", "sing-song", "singing", "laugh-speak", "emphasis")
_XAI_SPEECH_TAG_RE = re.compile(
    rf"(\[(?:{'|'.join(_XAI_INLINE_SPEECH_TAGS)})\]|</?(?:{'|'.join(_XAI_WRAPPING_SPEECH_TAGS)})>)",
    flags=re.IGNORECASE)
_XAI_FIRST_SENTENCE_RE = re.compile(r"^(.{12,120}?[.!?…])\s+(?=\S)", flags=re.DOTALL)


def _clamped_number(raw: Any, cast, lo, hi):
    """解析可选数值旋钮并夹到 [lo, hi]；None/不可解析 -> None。"""
    if raw is None:
        return None
    if raw != "":
        try:
            raw = cast(raw)
        except (TypeError, ValueError):
            return None
    return max(lo, min(hi, raw))


def generate_xai_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """xAI TTS（API 计费；优先 XAI_API_KEY）。"""
    api_key = resolve_provider_key("XAI_API_KEY", "xai") or ""
    if not api_key:
        raise ValueError("No xAI credentials found. Set XAI_API_KEY.")
    xai_config = tts_config.get("xai") if isinstance(tts_config, dict) else {}
    voice_id = str(xai_config.get("voice_id", DEFAULT_XAI_VOICE_ID)).strip() or DEFAULT_XAI_VOICE_ID
    language = str(xai_config.get("language", DEFAULT_XAI_LANGUAGE)).strip() or DEFAULT_XAI_LANGUAGE
    sample_rate = int(xai_config.get("sample_rate", DEFAULT_XAI_SAMPLE_RATE))
    bit_rate = int(xai_config.get("bit_rate", DEFAULT_XAI_BIT_RATE))
    auto_speech_tags = xai_config.get("auto_speech_tags", xai_config.get("speech_tags"))
    if config_bool(auto_speech_tags, DEFAULT_XAI_AUTO_SPEECH_TAGS):
        text = _apply_xai_auto_speech_tags(text)
    speed = _clamped_number(xai_config.get("speed", tts_config.get("speed")), float,
                            DEFAULT_XAI_SPEED_MIN, DEFAULT_XAI_SPEED_MAX)
    optimize_streaming_latency = _clamped_number(
        xai_config.get("optimize_streaming_latency", tts_config.get("optimize_streaming_latency")),
        int, 0, 2)
    text_normalization = config_bool(xai_config.get("text_normalization"),
                                     DEFAULT_XAI_TEXT_NORMALIZATION_DEFAULT)
    base_url = str(xai_config.get("base_url") or get_env_value("XAI_BASE_URL")
                   or DEFAULT_XAI_BASE_URL).strip().rstrip("/")
    codec = "wav" if output_path.endswith(".wav") else "mp3"
    payload: dict[str, Any] = {"text": text, "voice_id": voice_id, "language": language}
    if codec != "mp3" or sample_rate != DEFAULT_XAI_SAMPLE_RATE or bit_rate != DEFAULT_XAI_BIT_RATE:
        output_format: dict[str, Any] = {"codec": codec}
        if sample_rate:
            output_format["sample_rate"] = sample_rate
        if codec == "mp3" and bit_rate:
            output_format["bit_rate"] = bit_rate
        payload["output_format"] = output_format
    if speed is not None and speed != DEFAULT_XAI_SPEED_DEFAULT:
        payload["speed"] = speed
    if optimize_streaming_latency not in (None, DEFAULT_XAI_OPTIMIZE_STREAMING_LATENCY_DEFAULT):
        payload["optimize_streaming_latency"] = optimize_streaming_latency
    if text_normalization:
        payload["text_normalization"] = True
    response = _post_json(f"{base_url}/tts", payload, {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    response.raise_for_status()
    return _write_bytes(output_path, _read_tts_response_bytes(response, label="xAI TTS"))


def _apply_xai_auto_speech_tags(text: str) -> str:
    """保守本地 pass（段落间/首句后插 [pause]）；无显式标签时省略模型重写（OpenKitsune
    无 auxiliary client，直接回退本地标签）。"""
    clean = text.strip()
    if not clean:
        return text
    local = re.sub(r"\s*\n\s*", " ", re.sub(r"\n\s*\n+", " [pause] ", clean))
    if not _XAI_SPEECH_TAG_RE.search(local):
        local = _XAI_FIRST_SENTENCE_RE.sub(r"\1 [pause] ", local, count=1)
    local = re.sub(r"\s{2,}", " ", local).strip()
    return local


# ---- MiniMax TTS ----
def _resolve_minimax_tts_runtime(tts_config: dict[str, Any]) -> tuple[str, str, str]:
    """MiniMax 区域/端点/凭证原子选择：显式 region 优先；否则仅配置 CN 密钥时选 cn。"""
    mm_config = tts_config.get("minimax") if isinstance(tts_config, dict) else {}
    credentials = {
        "global": ("MINIMAX_API_KEY", resolve_provider_key("MINIMAX_API_KEY", "minimax")),
        "cn": ("MINIMAX_CN_API_KEY", resolve_provider_key("MINIMAX_CN_API_KEY", "minimax"))}
    region = str(mm_config.get("region") or "").strip().lower()
    if region and region not in ("global", "cn"):
        raise ValueError("tts.minimax.region must be 'global' or 'cn'")
    if not region:
        region = "cn" if credentials["cn"][1] and not credentials["global"][1] else "global"
    credential_source, api_key = credentials[region]
    if not api_key:
        raise ValueError(f"{credential_source} not set for MiniMax TTS region {region!r}")
    endpoint = str(mm_config.get("base_url") or
                   (DEFAULT_MINIMAX_CN_BASE_URL if region == "cn" else DEFAULT_MINIMAX_BASE_URL)).strip()
    return region, endpoint, api_key


def _raise_minimax_api_error(result: dict[str, Any]) -> None:
    base_resp = result.get("base_resp", {})
    status_code = base_resp.get("status_code", -1)
    if status_code != 0:
        raise RuntimeError(
            f"MiniMax TTS API error (code {status_code}): {base_resp.get('status_msg', 'unknown error')}")


def generate_minimax_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """MiniMax ``t2a_v2``（嵌套 payload，hex 音频）或 legacy ``text_to_speech``（raw body）。"""
    _, base_url, api_key = _resolve_minimax_tts_runtime(tts_config)
    mm_config = tts_config.get("minimax") if isinstance(tts_config, dict) else {}
    model = mm_config.get("model", DEFAULT_MINIMAX_MODEL)
    voice_id = mm_config.get("voice_id", DEFAULT_MINIMAX_VOICE_ID)
    group_id = (str(mm_config.get("group_id") or "").strip()
                or (get_env_value("MINIMAX_GROUP_ID") or "").strip())
    if group_id and "GroupId=" not in base_url:
        base_url = f"{base_url}{'&' if '?' in base_url else '?'}GroupId={group_id}"
    is_t2a_v2 = "t2a_v2" in base_url
    if is_t2a_v2:
        payload = {
            "model": model, "text": text,
            "voice_setting": {
                "voice_id": voice_id, "speed": mm_config.get("speed", 1.0),
                "vol": mm_config.get("vol", 1.0), "pitch": mm_config.get("pitch", 0),
                "emotion": mm_config.get("emotion", "neutral")},
            "audio_setting": {
                "sample_rate": mm_config.get("sample_rate", 32000),
                "bitrate": mm_config.get("bitrate", 128000),
                "format": "mp3", "channel": 1},
        }
    else:
        payload = {"model": model, "text": text, "voice_id": voice_id}
    response = _post_json(base_url, payload, {
        "Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    if is_t2a_v2:
        response.raise_for_status()
        result = _read_tts_response_json(response, label="MiniMax TTS")
        _raise_minimax_api_error(result)
        hex_audio = result.get("data", {}).get("audio", "")
        if not hex_audio:
            raise RuntimeError("MiniMax TTS returned empty audio data")
        return _write_bytes(output_path, bytes.fromhex(hex_audio))
    content_type = response.headers.get("Content-Type", "")
    if "audio/" in content_type:
        return _write_bytes(output_path, _read_tts_response_bytes(response, label="MiniMax TTS"))
    raw_body = b""
    try:
        raw_body = _read_tts_response_bytes(response, label="MiniMax TTS")
        _raise_minimax_api_error(json.loads(raw_body.decode("utf-8")) if raw_body else {})
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        response.raise_for_status()
        raise RuntimeError(
            f"MiniMax TTS returned unexpected Content-Type '{content_type}' ({len(raw_body)} bytes)")
    raise RuntimeError("MiniMax TTS returned no audio data")


# ---- Mistral (Voxtral TTS，base64 音频，原生 Opus) ----
def _import_mistral_client():
    from mistralai import Mistral
    return Mistral


def generate_mistral_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    api_key = _require_key("MISTRAL_API_KEY", "mistral", "Get one at https://console.mistral.ai/")
    mi_config = tts_config.get("mistral") if isinstance(tts_config, dict) else {}
    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if mi_config.get("base_url"):
        client_kwargs["server_url"] = mi_config["base_url"]
    Mistral = _import_mistral_client()
    try:
        with Mistral(**client_kwargs) as client:
            response = client.audio.speech.complete(
                model=mi_config.get("model", DEFAULT_MISTRAL_TTS_MODEL), input=text,
                voice_id=mi_config.get("voice_id") or DEFAULT_MISTRAL_TTS_VOICE_ID,
                response_format=_tts_response_format_from_path(output_path))
            audio_bytes = base64.b64decode(response.audio_data)
    except ValueError:
        raise
    except Exception as e:
        logger.error("Mistral TTS failed: %s", e, exc_info=True)
        raise RuntimeError(f"Mistral TTS failed: {type(e).__name__}") from e
    return _write_bytes(output_path, audio_bytes)


# ---- Google Gemini TTS ----
def generate_gemini_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """Gemini ``generateContent`` + ``responseModalities=["AUDIO"]``。回复为 base64 24kHz
    mono 16-bit PCM，包装为 WAV 后 ffmpeg 转目标容器。"""
    api_key = resolve_provider_key("GEMINI_API_KEY", "gemini") or resolve_provider_key("GOOGLE_API_KEY", "gemini")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set. Get one at https://aistudio.google.com/app/apikey")
    gemini_config = tts_config.get("gemini") if isinstance(tts_config, dict) else {}
    model = str(gemini_config.get("model", DEFAULT_GEMINI_TTS_MODEL)).strip() or DEFAULT_GEMINI_TTS_MODEL
    voice = str(gemini_config.get("voice", DEFAULT_GEMINI_TTS_VOICE)).strip() or DEFAULT_GEMINI_TTS_VOICE
    base_url = str(gemini_config.get("base_url") or get_env_value("GEMINI_BASE_URL")
                   or DEFAULT_GEMINI_TTS_BASE_URL).strip().rstrip("/")
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}},
    }
    headers = {"Content-Type": "application/json"}
    response = _post_json(f"{base_url}/models/{model}:generateContent", payload, headers,
                          params={"key": api_key})
    if response.status_code != 200:
        detail = _gemini_error_detail(response)
        raise RuntimeError(f"Gemini TTS API error (HTTP {response.status_code}): {detail}")
    try:
        data = _read_tts_response_json(response, label="Gemini TTS")
        parts = data["candidates"][0]["content"]["parts"]
        audio_part = next((p for p in parts if "inlineData" in p or "inline_data" in p), None)
        if audio_part is None:
            raise RuntimeError("Gemini TTS response contained no audio data")
        audio_b64 = (audio_part.get("inlineData") or audio_part.get("inline_data") or {}).get("data", "")
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Gemini TTS response was malformed: {e}") from e
    if not audio_b64:
        raise RuntimeError("Gemini TTS returned empty audio data")
    return audio.write_wav_bytes_as(audio.wrap_pcm_as_wav(base64.b64decode(audio_b64)), output_path)


def _gemini_error_detail(response: Any) -> str:
    """尽力提取 ``error.message``，否则返回响应体前 300 字符。"""
    raw_body = _read_tts_response_bytes(response, label="Gemini TTS")
    try:
        message = _parse_json_body(response, raw_body).get("error", {}).get("message")
    except Exception:
        message = None
    return message or raw_body.decode("utf-8", errors="replace")[:300]


# ---- OpenAI / DeepInfra（OpenAI-compatible）----
def _import_openai_client():
    from openai import OpenAI
    return OpenAI


def generate_openai_tts(
    text: str, output_path: str, tts_config: dict[str, Any], *, api_key: str | None = None,
    base_url: str | None = None, model: str | None = None, voice: str | None = None,
    speed: float | None = None, instructions: str | None = None,
) -> str:
    """OpenAI ``audio.speech.create`` 形状。显式 kwargs 供 DeepInfra 等 OpenAI 兼容后端
    注入凭证/模型/音色；否则走 ``tts.openai`` 配置 + 环境密钥链。"""
    oai_config = tts_config.get("openai") if isinstance(tts_config, dict) else {}
    if api_key is None:
        api_key = (oai_config.get("api_key") or resolve_provider_key("OPENAI_API_KEY", "openai")
                   or resolve_provider_key("VOICE_TOOLS_OPENAI_KEY", "openai"))
        if not api_key:
            raise ValueError("No OpenAI audio credentials. Set OPENAI_API_KEY or tts.openai.api_key.")
    if model is None:
        model = oai_config.get("model", DEFAULT_OPENAI_MODEL)
    if voice is None:
        voice = oai_config.get("voice", DEFAULT_OPENAI_VOICE)
    if base_url is None:
        base_url = oai_config.get("base_url") or DEFAULT_OPENAI_BASE_URL
    if speed is None:
        speed_default = tts_config.get("speed", 1.0) if isinstance(tts_config, dict) else 1.0
        speed = float(oai_config.get("speed", speed_default))
    create_kwargs: dict[str, Any] = {
        "model": model, "voice": voice, "input": text,
        "response_format": _tts_response_format_from_path(output_path),
        "extra_headers": {"x-idempotency-key": str(uuid.uuid4())}}
    if speed != 1.0:
        create_kwargs["speed"] = max(0.25, min(4.0, speed))
    if instructions:
        create_kwargs["instructions"] = instructions
    if oai_config.get("language"):
        create_kwargs["extra_body"] = {"lang_code": oai_config["language"]}
    client = _import_openai_client()(api_key=api_key, base_url=base_url)
    try:
        client.audio.speech.create(**create_kwargs).stream_to_file(output_path)
        return output_path
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def generate_deepinfra_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    """DeepInfra TTS（OpenAI 兼容）。"""
    api_key = resolve_provider_key("DEEPINFRA_API_KEY", "deepinfra")
    if not api_key:
        raise ValueError("DEEPINFRA_API_KEY not set. Set the env var directly.")
    di_config = tts_config.get("deepinfra") if isinstance(tts_config, dict) else {}
    model = di_config.get("model") or "deepinfra-tts"
    return generate_openai_tts(
        text, output_path, tts_config, api_key=api_key,
        base_url=di_config.get("base_url") or "https://api.deepinfra.com/v1/openai",
        model=model, voice=di_config.get("voice", DEFAULT_DEEPINFRA_TTS_VOICE),
        speed=float(di_config.get("speed", tts_config.get("speed", 1.0))))
