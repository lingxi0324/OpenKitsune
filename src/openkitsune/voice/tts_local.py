"""本地设备端 TTS 引擎 —— 迁移自 hermes-agent ``tools/tts_tool_local.py``。

NeuTTS / Piper / KittenTTS 三者均原生合成 WAV，再转换/重命名到目标容器。
Piper 与 KittenTTS 以小型 LRU 缓存（每进程至多 3 个已加载模型）避免多音色内存膨胀。
依赖可选：缺失时 :func:`generate_local_tts` 抛 ImportError 且不进入可用引擎列表。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_KITTENTTS_MODEL = "KittenML/kitten-tts-nano-0.8-int8"  # 25MB
DEFAULT_KITTENTTS_VOICE = "Jasper"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
DEFAULT_NEUTTS_MODEL = "neuphonic/neutts-air-q4-gguf"

_TTS_MODEL_CACHE_MAX = 3

_piper_voice_cache: dict[str, Any] = {}
_kittentts_model_cache: dict[str, Any] = {}


def _tts_cache_get_or_load(cache: dict[str, Any], key: str, load: Callable[[], Any]) -> Any:
    """从缓存取或加载 *key*，LRU 上限 ``_TTS_MODEL_CACHE_MAX``（命中刷新新鲜度）。"""
    if key in cache:
        cache[key] = cache.pop(key)
        return cache[key]
    value = load()
    cache[key] = value
    while len(cache) > _TTS_MODEL_CACHE_MAX:
        cache.pop(next(iter(cache)), None)
    return value


def _run_helper(cmd: list, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)


def _section(tts_config: Any, key: str) -> dict[str, Any]:
    section = tts_config.get(key) if isinstance(tts_config, dict) else None
    return section if isinstance(section, dict) else {}


def _wav_sidecar_path(output_path: str) -> str:
    """WAV 原生引擎写入路径（转换前）。"""
    return output_path if output_path.endswith(".wav") else output_path.rsplit(".", 1)[0] + ".wav"


def _finalize_wav_output(wav_path: str, output_path: str) -> str:
    """把 WAV 原生引擎输出放到请求容器：有 ffmpeg 时转码，否则重命名（扩展名误导但可播放）。"""
    if wav_path == output_path:
        return output_path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import os
        os.rename(wav_path, output_path)
        return output_path
    from .audio import _ffmpeg_run, _remove_quietly
    _ffmpeg_run(ffmpeg, ["-i", wav_path, "-y", "-loglevel", "error", output_path], check=True, capture=False)
    _remove_quietly(wav_path)
    return output_path


# ---- NeuTTS（子进程，~500MB 模型用后即退）----
def _import_neutts_synth_script() -> str:
    """定位 ``neutts_synth.py``（与本模块同目录）。"""
    script = Path(__file__).parent / "neutts_synth.py"
    if not script.exists():
        raise RuntimeError("NeuTTS synth script not found; local TTS engine 'neutts' unavailable")
    return str(script)


def _generate_neutts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    neutts_config = _section(tts_config, "neutts")
    wav_path = _wav_sidecar_path(output_path)
    script = _import_neutts_synth_script()
    ref_audio = str(neutts_config.get("ref_audio") or "").strip()
    ref_text = str(neutts_config.get("ref_text") or "").strip()
    if not ref_audio or not os.path.isfile(ref_audio):
        raise RuntimeError(
            "NeuTTS needs tts.neutts.ref_audio in data/voice_config.json "
            "(a short recording of the voice to clone)")
    if not ref_text or not os.path.isfile(ref_text):
        raise RuntimeError(
            "NeuTTS needs tts.neutts.ref_text in data/voice_config.json "
            "(transcript of ref_audio)")
    cmd = [
        sys.executable, script,
        "--text", text,
        "--out", wav_path,
        "--ref-audio", ref_audio,
        "--ref-text", ref_text,
        "--model", str(neutts_config.get("model") or DEFAULT_NEUTTS_MODEL),
        "--device", str(neutts_config.get("device") or "cpu")]
    result = _run_helper(cmd, 120)
    if result.returncode != 0:
        error_lines = [line for line in result.stderr.strip().splitlines() if not line.startswith("OK:")]
        raise RuntimeError(f"NeuTTS synthesis failed: {chr(10).join(error_lines) or 'unknown error'}")
    return _finalize_wav_output(wav_path, output_path)


# ---- Piper（本地神经 VITS，44 语言）----
def _get_piper_voices_dir() -> Path:
    """``<project_root>/data/piper-voices/``（音色下载随工作区走）。"""
    try:
        from openkitsune.config import settings
        root = Path(settings.project_root) / "data" / "piper-voices"
    except Exception:
        root = Path.cwd() / "data" / "piper-voices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_piper_voice_path(voice: str, download_dir: Path) -> str:
    """解析音色（.onnx 路径或名称，首次自动下载）为具体 .onnx；失败抛 RuntimeError。"""
    voice = voice or DEFAULT_PIPER_VOICE
    candidate = Path(voice).expanduser()
    if candidate.suffix.lower() == ".onnx" and candidate.exists():
        return str(candidate)
    cached = download_dir / f"{voice}.onnx"
    if cached.exists() and (download_dir / f"{voice}.onnx.json").exists():
        return str(cached)
    logger.info("[Piper] Downloading voice '%s' to %s (first use)", voice, download_dir)
    try:
        result = _run_helper(
            [sys.executable, "-m", "piper.download_voices", voice, "--download-dir", str(download_dir)], 300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Piper voice download timed out after 300s for '{voice}'") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "no stderr output"
        raise RuntimeError(f"Piper voice download failed for '{voice}': {stderr[:400]}")
    if not cached.exists():
        raise RuntimeError(
            f"Piper voice download completed but {cached} is missing — "
            "check voice name (https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md)")
    return str(cached)


def _import_piper():
    from piper import PiperVoice
    return PiperVoice


def _load_piper_voice_for_config(tts_config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    PiperVoice = _import_piper()
    piper_config = _section(tts_config, "piper")
    voice_name = piper_config.get("voice") or DEFAULT_PIPER_VOICE
    download_dir = Path(piper_config.get("voices_dir") or _get_piper_voices_dir()).expanduser()
    download_dir.mkdir(parents=True, exist_ok=True)
    use_cuda = bool(piper_config.get("use_cuda", False))
    model_path = _resolve_piper_voice_path(voice_name, download_dir)

    def _load_piper_voice():
        logger.info("[Piper] Loading voice: %s", model_path)
        v = PiperVoice.load(model_path, use_cuda=use_cuda)
        logger.info("[Piper] Voice loaded")
        return v

    cache_key = f"{model_path}::cuda={use_cuda}"
    return _tts_cache_get_or_load(_piper_voice_cache, cache_key, _load_piper_voice), piper_config


_PIPER_ADVANCED_KNOBS = ("length_scale", "noise_scale", "noise_w_scale", "volume",
                         "normalize_audio", "speaker_id")


def _generate_piper_tts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    voice, piper_config = _load_piper_voice_for_config(tts_config)
    _raw_speaker = piper_config.get("speaker_id", 0)
    speaker_id = _raw_speaker if type(_raw_speaker) is int else 0
    syn_config = None
    if any(k in piper_config for k in _PIPER_ADVANCED_KNOBS):
        try:
            from piper import SynthesisConfig  # type: ignore
            syn_config = SynthesisConfig(
                length_scale=float(piper_config.get("length_scale", 1.0)),
                noise_scale=float(piper_config.get("noise_scale", 0.667)),
                noise_w_scale=float(piper_config.get("noise_w_scale", 0.8)),
                volume=float(piper_config.get("volume", 1.0)),
                normalize_audio=bool(piper_config.get("normalize_audio", True)),
                speaker_id=speaker_id)
        except ImportError:
            logger.warning("[Piper] SynthesisConfig not available — advanced knobs ignored")
    wav_path = _wav_sidecar_path(output_path)
    with wave.open(wav_path, "wb") as wav_file:
        if syn_config is not None:
            voice.synthesize_wav(text, wav_file, syn_config=syn_config)
        else:
            voice.synthesize_wav(text, wav_file)
    return _finalize_wav_output(wav_path, output_path)


# ---- KittenTTS（本地 ONNX，25-80MB 模型，CPU only）----
def _import_kittentts():
    from kittentts import KittenTTS
    return KittenTTS


def _load_kittentts_model_for_config(tts_config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    KittenTTS = _import_kittentts()
    kt_config = _section(tts_config, "kittentts")
    model_name = kt_config.get("model", DEFAULT_KITTENTTS_MODEL)

    def _load_kittentts_model():
        logger.info("[KittenTTS] Loading model: %s", model_name)
        m = KittenTTS(model_name)
        logger.info("[KittenTTS] Model loaded successfully")
        return m

    return _tts_cache_get_or_load(_kittentts_model_cache, model_name, _load_kittentts_model), kt_config


def _generate_kittentts(text: str, output_path: str, tts_config: dict[str, Any]) -> str:
    model, kt_config = _load_kittentts_model_for_config(tts_config)
    audio_arr = model.generate(  # numpy 24kHz
        text, voice=kt_config.get("voice", DEFAULT_KITTENTTS_VOICE),
        speed=kt_config.get("speed", 1.0), clean_text=kt_config.get("clean_text", True))
    import soundfile as sf
    wav_path = _wav_sidecar_path(output_path)
    sf.write(wav_path, audio_arr, 24000)
    return _finalize_wav_output(wav_path, output_path)


# ---- 统一入口 ----
class _LocalTTSDispatch:
    """按 provider 名分发到本地引擎（延迟导入，缺失抛 ImportError）。"""

    SUPPORTED = frozenset({"piper", "kittentts", "neutts"})

    def __call__(self, text: str, output_path: str, tts_config: dict[str, Any]) -> str:
        provider = str(tts_config.get("_provider") or "piper").lower().strip()
        if provider == "piper":
            return _generate_piper_tts(text, output_path, tts_config)
        if provider == "kittentts":
            return _generate_kittentts(text, output_path, tts_config)
        if provider == "neutts":
            return _generate_neutts(text, output_path, tts_config)
        raise ValueError(f"Unknown local TTS provider '{provider}'")


generate_local_tts = _LocalTTSDispatch()
