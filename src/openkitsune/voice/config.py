"""
语音能力统一配置 —— 迁移自 hermes-agent 的 TTS/STT 配置解析逻辑。

数据来源（按优先级）:
1. 环境变量（最高，含工作区 .env）
2. ``data/voice_config.json``（可选，用户显式配置）
3. 内置默认值

覆盖三大能力:
- vad:    录音采样率、静音阈值、静音自动停止时长、最大录音时长
- stt:    本地 faster-whisper（模型/设备/反幻觉阈值）+ 在线 STT（复用 llm_endpoints.json 的 stt_endpoints）
- tts:    默认 provider、各 provider 的 voice/model/key/base_url、输出目录
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---- 默认值（与 hermes-agent 对齐） ----
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
SILENCE_RMS_THRESHOLD = 200
SILENCE_DURATION_SECONDS = 1.2
MAX_WAIT_SECONDS = 15.0
MIN_SPEECH_SECONDS = 0.3
MAX_DIP_SECONDS = 0.3
MAX_RECORDING_SECONDS = 0.0  # 0 = 不限

DEFAULT_TTS_PROVIDER = "edge"
DEFAULT_TTS_OUTPUT_DIR = "data/voice_cache"  # 相对 project_root
DEFAULT_LOCAL_STT_MODEL = "base"

# ---- TTS provider 默认参数 ----
DEFAULT_EDGE_VOICE = "en-US-AriaNeural"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_VOICE = "alloy"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_MINIMAX_MODEL = "speech-02-hd"
DEFAULT_MINIMAX_VOICE_ID = "English_expressive_narrator"
DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/v1/t2a_v2"
DEFAULT_MINIMAX_CN_BASE_URL = "https://api.minimaxi.com/v1/t2a_v2"
DEFAULT_MISTRAL_TTS_MODEL = "voxtral-mini-tts-2603"
DEFAULT_MISTRAL_TTS_VOICE_ID = "c69964a6-ab8b-4f8a-9465-ec0925096ec8"  # Paul - Neutral
DEFAULT_XAI_VOICE_ID = "eve"
DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_GEMINI_TTS_VOICE = "Kore"
DEFAULT_GEMINI_TTS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
DEFAULT_KITTENTTS_MODEL = "KittenML/kitten-tts-nano-0.8-int8"
DEFAULT_KITTENTTS_VOICE = "Jasper"
DEFAULT_NEUTTS_MODEL = "neuphonic/neutts-air-q4-gguf"
DEFAULT_DEEPINFRA_TTS_VOICE = "default"

# provider -> 单请求输入字符上限（官方文档 / 实践值）
PROVIDER_MAX_TEXT_LENGTH: dict[str, int] = {
    "edge": 5000,
    "openai": 4096,
    "deepinfra": 4096,
    "xai": 15000,
    "minimax": 10000,
    "mistral": 4000,
    "gemini": 32000,
    "elevenlabs": 10000,
    "piper": 5000,
    "kittentts": 2000,
    "neutts": 2000,
}
FALLBACK_MAX_TEXT_LENGTH = 4000

# 内置 TTS provider 名（与 hermes 保持一致）；非内置名可经 tts.providers.<name> 声明命令型引擎
BUILTIN_TTS_PROVIDERS = frozenset({
    "edge", "elevenlabs", "openai", "deepinfra", "minimax", "xai", "mistral", "gemini",
    "piper", "kittentts", "neutts",
})

# 原生输出 Opus 的 provider（voice bubble 场景）；其余需 ffmpeg 转码
NATIVE_OPUS_PROVIDERS = frozenset({"openai", "elevenlabs", "mistral", "gemini"})

# 需要 ffmpeg 转 Ogg/Opus 的 provider
FFMPEG_OPUS_PROVIDERS = frozenset({"edge", "neutts", "minimax", "xai", "kittentts", "piper"})

# 语音气泡平台（原生 Ogg/Opus 交付）
OPUS_VOICE_PLATFORMS = frozenset({"telegram", "matrix", "feishu", "whatsapp", "signal"})

_TRUE_WORDS = {"1", "true", "yes", "on", "enabled"}
_FALSE_WORDS = {"0", "false", "no", "off", "disabled"}

# 环境变量 -> (provider 名, 配置键)。TTS/在线 STT key 统一从这里解析。
PROVIDER_KEY_ENV: dict[str, str] = {
    "ELEVENLABS_API_KEY": "elevenlabs",
    "OPENAI_API_KEY": "openai",
    "VOICE_TOOLS_OPENAI_KEY": "openai",
    "DEEPINFRA_API_KEY": "deepinfra",
    "MINIMAX_API_KEY": "minimax",
    "MINIMAX_CN_API_KEY": "minimax",
    "XAI_API_KEY": "xai",
    "MISTRAL_API_KEY": "mistral",
    "GEMINI_API_KEY": "gemini",
    "GOOGLE_API_KEY": "gemini",
    "GROQ_API_KEY": "groq",
}

_voice_config_path: Path | None = None
_voice_config: dict[str, Any] = {}


def set_voice_config_path(path: str | Path | None) -> None:
    """覆盖 voice 配置路径（测试 / 多工作区场景）。"""
    global _voice_config_path, _voice_config
    _voice_config_path = Path(path) if path else None
    _voice_config = {}


def get_voice_config_path() -> Path:
    """``<project_root>/data/voice_config.json``（可被 set_voice_config_path 覆盖）。"""
    if _voice_config_path is not None:
        return _voice_config_path
    try:
        from openkitsune.config import settings
        return Path(settings.project_root) / "data" / "voice_config.json"
    except Exception:
        return Path.cwd() / "data" / "voice_config.json"


def load_voice_config() -> dict[str, Any]:
    """加载 voice 配置段（{} 缺失/损坏时）。"""
    global _voice_config
    if _voice_config:
        return _voice_config
    path = get_voice_config_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _voice_config = raw
                logger.info("Loaded voice config from %s", path)
    except Exception as e:
        logger.warning("Failed to load voice config %s: %s", path, e)
    return _voice_config


def reload_voice_config() -> dict[str, Any]:
    """强制重读 voice 配置（配置变更后调用）。"""
    global _voice_config
    _voice_config = {}
    return load_voice_config()


def section(config: dict[str, Any] | None, key: str) -> dict[str, Any]:
    """``cfg.<key>`` 作为 dict（null/非 dict 读作空）。"""
    cfg = config if isinstance(config, dict) else {}
    sec = cfg.get(key)
    return sec if isinstance(sec, dict) else {}


def config_bool(value: Any, default: bool = False) -> bool:
    """将常见 YAML/env 布尔写法归一化；乱字符串取默认值。"""
    if isinstance(value, (bool, int, float)):
        return bool(value)
    normalized = value.strip().lower() if isinstance(value, str) else None
    if normalized in _TRUE_WORDS:
        return True
    if normalized in _FALSE_WORDS:
        return False
    return default


def config_number(cfg: dict[str, Any], key: str, default: float, cast=float) -> Any:
    """读取 ``cfg[key]`` 经 *cast* 转换，坏值回退默认。"""
    try:
        return cast(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def get_env_value(name: str, default: str = "") -> str:
    """读环境变量；工作区 .env 已在 openkitsune.llm.config 加载时注入 os.environ。"""
    return os.environ.get(name, default).strip() or default


def resolve_provider_key(env_var: str, provider_id: str) -> str:
    """解析 provider API key：config[tts.<provider>.api_key] > 对应环境变量。

    *provider_id* 仅用于从 voice 配置读取 ``tts.<provider>.api_key``。
    """
    cfg = load_voice_config()
    tts_cfg = section(cfg, "tts")
    prov_cfg = section(tts_cfg, provider_id)
    configured = prov_cfg.get("api_key")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return get_env_value(env_var)


def get_output_dir() -> str:
    """TTS/录音输出目录：config[voice.output_dir] > <project_root>/data/voice_cache。"""
    cfg = load_voice_config()
    configured = cfg.get("output_dir")
    if isinstance(configured, str) and configured.strip():
        return os.path.expandvars(configured.strip())
    try:
        from openkitsune.config import settings
        return str(Path(settings.project_root) / DEFAULT_TTS_OUTPUT_DIR)
    except Exception:
        return DEFAULT_TTS_OUTPUT_DIR


def ensure_output_dir() -> Path:
    """创建并返回输出目录。"""
    path = Path(get_output_dir())
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vad_config() -> dict[str, Any]:
    """VAD 配置段（含默认值合并）。"""
    cfg = section(load_voice_config(), "vad")
    defaults: dict[str, Any] = {
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "silence_threshold": SILENCE_RMS_THRESHOLD,
        "silence_duration": SILENCE_DURATION_SECONDS,
        "max_wait": MAX_WAIT_SECONDS,
        "min_speech_duration": MIN_SPEECH_SECONDS,
        "max_dip_tolerance": MAX_DIP_SECONDS,
        "max_recording_seconds": MAX_RECORDING_SECONDS,
    }
    merged = dict(defaults)
    merged.update({k: v for k, v in cfg.items() if v is not None})
    return merged


def get_stt_config() -> dict[str, Any]:
    """STT 配置段（{} 缺失时）。"""
    return section(load_voice_config(), "stt")


def get_tts_config() -> dict[str, Any]:
    """TTS 配置段（{} 缺失时）。"""
    return section(load_voice_config(), "tts")


def get_tts_provider(tts_config: dict[str, Any] | None = None) -> str:
    """配置的 TTS provider 或免费默认（edge）。"""
    cfg = tts_config if tts_config is not None else get_tts_config()
    provider = (cfg.get("provider") or DEFAULT_TTS_PROVIDER).lower().strip()
    return provider or DEFAULT_TTS_PROVIDER
