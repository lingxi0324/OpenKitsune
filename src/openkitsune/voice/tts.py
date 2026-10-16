"""语音合成（TTS）统一入口 —— 迁移自 hermes-agent ``tools/tts_tool.py`` 及周边模块。

能力:
1. 多引擎分发：edge（免费默认）/ openai / deepinfra / elevenlabs / minimax / xai /
   mistral / gemini / piper / kittentts / neutts（见 :data:`BUILTIN_TTS_PROVIDERS`）
2. 文本预处理：``prepare_spoken_text``（Markdown/符号清理）
3. 长文本分块：按 provider 请求上限拆分逐块合成，再 ffmpeg 合并
4. 交付策略：``tts.output_format``（mp3/wav/ogg）与平台上传上限打包
5. 容器修复：后端忽略请求格式时嗅探魔数并转码/改名
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import audio
from .config import (
    BUILTIN_TTS_PROVIDERS,
    FALLBACK_MAX_TEXT_LENGTH,
    NATIVE_OPUS_PROVIDERS,
    OPUS_VOICE_PLATFORMS,
    PROVIDER_MAX_TEXT_LENGTH,
    get_tts_config,
    get_tts_provider,
)
from .text_normalize import prepare_spoken_text
from .tts_providers import (
    generate_deepinfra_tts,
    generate_edge_tts,
    generate_elevenlabs,
    generate_gemini_tts,
    generate_minimax_tts,
    generate_mistral_tts,
    generate_openai_tts,
    generate_xai_tts,
)

logger = logging.getLogger(__name__)

# 引擎输出特征：原生 Opus（语音气泡友好）或需 ffmpeg 转码
_NATIVE_OPUS = frozenset({"openai", "elevenlabs", "mistral", "gemini"})
_FFMPEG_OPUS = frozenset({"edge", "neutts", "minimax", "xai", "kittentts", "piper"})
# 需 ffmpeg 才能合并多分块（其余可 concat demuxer 合并）
_NEEDS_FFMPEG_CONCAT = _FFMPEG_OPUS

# 响应字节上限（上游防御）
DEFAULT_RESPONSE_BYTE_LIMIT = 16 * 1024 * 1024


def _section(tts_config: Any, key: str) -> Dict[str, Any]:
    return audio._section(tts_config, key)


def _positive_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def resolve_max_text_length(provider: Optional[str], tts_config: Optional[Dict[str, Any]] = None) -> int:
    """provider 输入字符上限：``tts.<provider>.max_text_length`` > 内置表 > 兜底。"""
    if not provider:
        return FALLBACK_MAX_TEXT_LENGTH
    key = provider.lower().strip()
    cfg = tts_config or {}
    prov_cfg = _section(cfg, key)
    override = _positive_int(prov_cfg.get("max_text_length"))
    if override:
        return override
    if key == "elevenlabs":
        model_id = prov_cfg.get("model_id")
        mapped = audio_elevenlabs_model_cap(str(model_id).strip()) if model_id else None
        if mapped:
            return mapped
    return PROVIDER_MAX_TEXT_LENGTH.get(key, FALLBACK_MAX_TEXT_LENGTH)


def audio_elevenlabs_model_cap(model_id: str) -> Optional[int]:
    """ElevenLabs 模型感知字符上限（官方模型表）。"""
    caps = {
        "eleven_v3": 5000, "eleven_ttv_v3": 5000,
        "eleven_multilingual_v2": 10000, "eleven_multilingual_v1": 10000,
        "eleven_english_sts_v2": 10000, "eleven_english_sts_v1": 10000,
        "eleven_flash_v2": 30000, "eleven_flash_v2_5": 40000}
    return caps.get(model_id)


def _is_command_provider(provider: str, tts_config: Dict[str, Any]) -> bool:
    """命令 provider（本地可执行文件合成）暂不迁移；返回 False。"""
    return False


def _resolve_engine(provider: str) -> Optional[Callable]:
    """返回 provider 对应的同步/异步生成函数；未知返回 None。"""
    engines: Dict[str, Callable] = {
        "edge": generate_edge_tts,          # async
        "openai": generate_openai_tts,
        "deepinfra": generate_deepinfra_tts,
        "elevenlabs": generate_elevenlabs,
        "minimax": generate_minimax_tts,
        "xai": generate_xai_tts,
        "mistral": generate_mistral_tts,
        "gemini": generate_gemini_tts,
    }
    local_engine = _resolve_local_engine(provider)
    if local_engine is not None:
        return local_engine
    return engines.get(provider.lower().strip())


def _resolve_local_engine(provider: str) -> Optional[Callable]:
    """本地引擎（piper/kittentts/neutts）延迟导入；未安装返回 None。

    返回绑定 provider 的局部函数，供 ``_run_engine`` 直接调用。
    """
    key = provider.lower().strip()
    try:
        from .tts_local import generate_local_tts
        if key in generate_local_tts.SUPPORTED:
            def _bound(text: str, output_path: str, cfg: Dict[str, Any]) -> str:
                local_cfg = dict(cfg)
                local_cfg["_provider"] = key
                return generate_local_tts(text, output_path, local_cfg)
            return _bound
    except Exception:
        pass
    return None


def _is_async_engine(provider: str) -> bool:
    return provider.lower().strip() == "edge"


def _run_engine(engine: Callable, text: str, output_path: str, tts_config: Dict[str, Any],
                provider: str) -> str:
    """执行引擎（async 用事件循环；sync 直调）。

    支持三种调用上下文：
    - 无事件循环：``asyncio.run()`` 新建循环
    - 已有 running loop：在线程池中 ``asyncio.run()``（不污染调用方循环）
    """
    if not _is_async_engine(provider):
        return engine(text, output_path, tts_config)
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if not in_loop:
        return asyncio.run(engine(text, output_path, tts_config))
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, engine(text, output_path, tts_config)).result()


def _default_output_path(provider: str, fmt: str, output_dir: str) -> str:
    """默认输出路径 ``tts_<timestamp>.<fmt>``。"""
    from .config import ensure_output_dir
    ensure_output_dir()
    return str(Path(output_dir) / f"tts_{os.path.getpid()}_{int(__import__('time').time() * 1000)}.{fmt}")


def _resolve_output_format(tts_config: Dict[str, Any], output_path: Optional[str],
                           provider: str, voice_compatible: bool) -> str:
    """输出格式：显式路径扩展名 > ``tts.output_format`` > provider/平台推断。"""
    if output_path and Path(output_path).suffix.lower() in (".mp3", ".wav", ".ogg", ".opus", ".flac"):
        return Path(output_path).suffix.lower().lstrip(".")
    fmt = str((tts_config.get("output_format") or "mp3").lower()).lstrip(".")
    if fmt not in ("mp3", "wav", "ogg", "opus", "flac"):
        fmt = "mp3"
    if voice_compatible:
        fmt = "ogg"
    return fmt


def _engine_output_path(output_path: str, fmt: str, provider: str) -> str:
    """引擎实际写入路径：ogg 用 .ogg；原生 Opus provider 直接用目标扩展名；其余 mp3/wav。"""
    if fmt in ("ogg", "opus"):
        return output_path
    # 非 ogg 目标：引擎写自身原生格式，后续转码/重命名
    return output_path


def _finalize_output(engine_path: str, output_path: str, provider: str, fmt: str) -> str:
    """将引擎产物落到最终路径：容器匹配时直接重命名/移动；不匹配时 ffmpeg 转码。"""
    if os.path.abspath(engine_path) == os.path.abspath(output_path):
        return output_path
    engine_suffix = Path(engine_path).suffix.lower()
    target_suffix = Path(output_path).suffix.lower()
    ffmpeg = shutil.which("ffmpeg")
    if engine_suffix == target_suffix or target_suffix == ".opus":
        if target_suffix == ".opus" and ffmpeg:
            # 显式 .opus 扩展名：确保真 Opus 编码
            audio.transcode_to_ogg_opus(engine_path, output_path=output_path)
            _remove_quietly(engine_path)
            return output_path
        shutil.move(engine_path, output_path)
        return output_path
    if ffmpeg:
        audio._ffmpeg_run(ffmpeg, ["-i", engine_path, "-y", "-loglevel", "error", output_path],
                          check=True, capture=False)
        _remove_quietly(engine_path)
        return output_path
    shutil.move(engine_path, output_path)
    return output_path


def _remove_quietly(path: Optional[str]) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def synthesize_text(
    text: str,
    *,
    provider: Optional[str] = None,
    output_path: Optional[str] = None,
    tts_config: Optional[Dict[str, Any]] = None,
    voice_compatible: bool = False,
    platform: Optional[str] = None,
    max_text_length: Optional[int] = None,
    format: Optional[str] = None,
) -> Dict[str, Any]:
    """合成语音并返回交付信息。

    Args:
        text: 待朗读文本（自动做 TTS 友好清理）
        provider: 引擎名；None 取配置默认（edge）
        output_path: 输出文件路径；None 时自动生成
        tts_config: 覆盖全局 TTS 配置段
        voice_compatible: 语音气泡兼容（Ogg/Opus 输出）
        platform: 交付平台（telegram/feishu/discord/...），影响上传上限
        max_text_length: 单请求字符上限覆盖
        format: 输出格式覆盖（mp3/wav/ogg）

    Returns:
        ``{"paths": [..], "provider": .., "format": .., "combined": bool}``
    """
    cfg = tts_config if tts_config is not None else get_tts_config()
    provider = (provider or get_tts_provider(cfg)).lower().strip()
    if provider not in BUILTIN_TTS_PROVIDERS:
        raise ValueError(
            f"Unknown TTS provider '{provider}'. Built-in: {sorted(BUILTIN_TTS_PROVIDERS)}")
    engine = _resolve_engine(provider)
    if engine is None:
        raise RuntimeError(f"TTS engine '{provider}' unavailable (missing dependency)")

    spoken = prepare_spoken_text(text, max_chars=None)
    if not spoken:
        raise ValueError("Nothing to speak after text cleanup")

    cap = max_text_length or resolve_max_text_length(provider, cfg)
    chunks = audio.split_text_for_tts(spoken, cap)
    fmt = _resolve_output_format(cfg, output_path, provider, voice_compatible)
    output_dir = str(Path(output_path).parent) if output_path else get_output_dir_path(cfg)

    # 每个分块生成独立文件
    chunk_paths: List[str] = []
    try:
        for index, chunk in enumerate(chunks, start=1):
            if output_path and len(chunks) == 1:
                chunk_out = str(output_path)
            else:
                stem = Path(output_path).stem if output_path else f"tts_{int(__import__('time').time() * 1000)}"
                ext = Path(output_path).suffix if output_path else f".{fmt}"
                chunk_out = str(Path(output_dir) / f"{stem}.part{index:02d}{ext}")
            Path(chunk_out).parent.mkdir(parents=True, exist_ok=True)
            if index == 1:
                logger.info("TTS provider=%s fmt=%s chunks=%d", provider, fmt, len(chunks))
            result = _run_engine(engine, chunk, chunk_out, cfg, provider)
            # 容器修复：.ogg 路径必须真为 Ogg
            if Path(chunk_out).suffix.lower() == ".ogg":
                result = audio.repair_ogg_container(result)
            chunk_paths.append(result)
    except Exception as e:
        for path in chunk_paths:
            _remove_quietly(path)
        raise

    # 单块直接交付
    if len(chunk_paths) == 1:
        return {"paths": chunk_paths, "provider": provider, "format": fmt, "combined": False}

    # 多块合并（目标路径存在时）
    if output_path:
        final_path, combined = _combine_chunks(chunk_paths, output_path, fmt, voice_compatible, cfg)
        return {"paths": final_path, "provider": provider, "format": fmt, "combined": combined}
    return {"paths": chunk_paths, "provider": provider, "format": fmt, "combined": False}


def _combine_chunks(chunk_paths: List[str], output_path: str, fmt: str,
                    voice_compatible: bool, cfg: Dict[str, Any]) -> Tuple[List[str], bool]:
    """按目标路径合并分块（ffmpeg concat）；超限时按平台 profile 打包。"""
    profile = audio.resolve_audio_delivery_profile(None, cfg)
    # 先尝试直接合并
    combined = audio.concat_audio_files(chunk_paths, output_path, voice_compatible=voice_compatible)
    if combined and Path(combined).stat().st_size <= profile.max_file_bytes:
        for path in chunk_paths:
            _remove_quietly(path)
        return [combined], True
    # 失败或超限：按 profile 打包
    final_paths, combined_any = audio.build_audio_delivery_files(
        chunk_paths, output_path, profile, voice_compatible=voice_compatible)
    return final_paths, combined_any


def get_output_dir_path(tts_config: Dict[str, Any]) -> str:
    """输出目录：``tts.output_dir`` > voice 配置 output_dir > data/voice_cache。"""
    from .config import get_output_dir
    configured = tts_config.get("output_dir")
    if isinstance(configured, str) and configured.strip():
        return os.path.expandvars(configured.strip())
    return get_output_dir()


def list_available_providers() -> List[str]:
    """列出可用引擎（本地引擎按依赖可用性过滤）。"""
    available = []
    for provider in sorted(BUILTIN_TTS_PROVIDERS):
        try:
            if _resolve_engine(provider) is not None:
                available.append(provider)
        except Exception:
            continue
    return available
