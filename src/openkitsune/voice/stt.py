"""语音识别（STT）统一入口 —— 整合 hermes-agent 本地/在线识别能力与 OpenKitsune 在线 STT。

能力分层:
1. :class:`LocalSTT` —— 本地 faster-whisper：
   - 模型缓存（``data/models/whisper``），空闲卸载线程（5 分钟无识别释放显存）
   - CUDA → CPU 自动回退，int8 量化
   - 反幻觉过滤：Silero VAD 段裁剪 + ``no_speech_prob``/``avg_logprob`` 阈值门控
2. :func:`transcribe_audio` —— 统一入口：
   - 配置 ``stt.mode``（``local`` / ``online`` / ``auto``）
   - local: 本地 faster-whisper；online: 复用 ``openkitsune.llm.stt_client.STTClient``（llm_endpoints.json 的 stt_endpoints）
   - auto: 本地不可用（缺依赖/缺模型/识别失败）时回退在线
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import DEFAULT_LOCAL_STT_MODEL, config_bool, config_number, get_stt_config

logger = logging.getLogger(__name__)

# ---- 反幻觉阈值（hermes 迁移值）----
_NO_SPEECH_PROB_MAX = 0.6   # >0.6 视为无语音幻觉
_AVG_LOGPROB_MIN = -1.2     # <-1.2 视为低置信幻觉
_MIN_SEGMENT_CHARS = 2      # 单段少于 2 字符视为噪音
_MIN_SPEECH_RATIO = 0.0     # 语音段比例下限（0=不裁剪）

# 模型卸载空闲时间（秒）
MODEL_IDLE_UNLOAD_SECONDS = 300.0

_WHISPER_MODELS = {
    "tiny": "tiny", "tiny.en": "tiny.en", "base": "base", "base.en": "base.en",
    "small": "small", "small.en": "small.en", "medium": "medium", "medium.en": "medium.en",
    "large": "large", "large-v1": "large-v1", "large-v2": "large-v2", "large-v3": "large-v3",
}


def _model_cache_dir() -> Path:
    """本地模型缓存目录：``<project_root>/data/models/whisper``。"""
    try:
        from openkitsune.config import settings
        return Path(settings.project_root) / "data" / "models" / "whisper"
    except Exception:
        return Path.cwd() / "data" / "models" / "whisper"


class LocalSTT:
    """本地 faster-whisper 转写器（惰性加载，空闲自动卸载）。"""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()
        self._last_use = 0.0
        self._unloader_started = False
        self._device: str = "auto"
        self._compute_type: str = "int8"
        self._model_name: str = DEFAULT_LOCAL_STT_MODEL
        self._language: str | None = None
        self._vad_filter = True
        self._min_silence_ms = 500
        self._beam_size = 5
        self._condition_on_previous_text = False
        self._load_config()

    def _load_config(self) -> None:
        cfg = get_stt_config()
        self._model_name = str(cfg.get("model") or DEFAULT_LOCAL_STT_MODEL).strip() or DEFAULT_LOCAL_STT_MODEL
        device = str(cfg.get("device") or "auto").lower()
        self._device = device if device in ("auto", "cpu", "cuda", "cuda:0", "cuda:1") else "auto"
        compute = str(cfg.get("compute_type") or "int8").lower()
        self._compute_type = compute if compute in ("int8", "int8_float16", "float16", "float32") else "int8"
        lang = cfg.get("language")
        self._language = str(lang).strip() if isinstance(lang, str) and lang.strip() else None
        self._vad_filter = config_bool(cfg.get("vad_filter"), default=True)
        self._min_silence_ms = int(config_number(cfg, "min_silence_ms", 500, cast=int))
        self._beam_size = int(config_number(cfg, "beam_size", 5, cast=int))
        self._condition_on_previous_text = config_bool(cfg.get("condition_on_previous_text"), default=False)

    @property
    def is_available(self) -> bool:
        """faster-whisper 已安装即视为可用（模型惰性加载）。"""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> str:
        return self._device

    def _resolve_device(self) -> tuple[str, str]:
        """解析 'auto' 设备：优先 CUDA（若 faster_whisper 可见），否则 CPU。"""
        if self._device != "auto":
            return self._device, self._compute_type
        try:
            import torch  # noqa: F401
            if torch.cuda.is_available():
                return "cuda", self._compute_type
        except ImportError:
            pass
        return "cpu", "int8"

    def _load(self) -> Any:
        """惰性加载模型（线程安全，CUDA 失败回退 CPU）。"""
        with self._lock:
            if self._model is not None:
                self._last_use = time.monotonic()
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "Local STT requires faster-whisper.\n"
                    "Install with: pip install faster-whisper"
                ) from e
            device, compute = self._resolve_device()
            cache_dir = str(_model_cache_dir())
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            # HF 下载端点：stt.hf_endpoint（如 https://hf-mirror.com）覆盖默认 huggingface.co，
            # 供受限网络下载 Whisper 模型；仅当环境变量未设置时写入，避免覆盖用户显式配置。
            # 同步禁用 XetData（hf_xet）：其 CAS 端点 cas-server.xethub.hf.co 不认 HF_ENDPOINT
            # 且匿名重建 401，镜像场景必须回退经典 LFS HTTP 下载流。
            hf_endpoint = str(get_stt_config().get("hf_endpoint") or "").strip()
            if hf_endpoint and not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = hf_endpoint.rstrip("/")
            if hf_endpoint and not os.environ.get("HF_HUB_DISABLE_XET"):
                os.environ["HF_HUB_DISABLE_XET"] = "1"
            logger.info("Loading local Whisper model '%s' (device=%s, compute=%s)...",
                        self._model_name, device, compute)
            started = time.monotonic()
            try:
                self._model = WhisperModel(
                    self._model_name, device=device, compute_type=compute, download_root=cache_dir)
            except Exception as e:
                logger.warning("Failed to load %s on %s: %s — retrying on CPU", self._model_name, device, e)
                if device == "cpu":
                    raise
                self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8",
                                           download_root=cache_dir)
            self._last_use = time.monotonic()
            logger.info("Whisper model loaded in %.1fs", time.monotonic() - started)
            self._ensure_unloader()
            return self._model

    def _ensure_unloader(self) -> None:
        """启动空闲卸载守护线程（仅一次）。"""
        if self._unloader_started:
            return
        self._unloader_started = True
        threading.Thread(target=self._unload_loop, daemon=True).start()

    def _unload_loop(self) -> None:
        while True:
            time.sleep(30.0)
            with self._lock:
                idle = self._model is not None and (time.monotonic() - self._last_use) > MODEL_IDLE_UNLOAD_SECONDS
                if idle:
                    model, self._model = self._model, None
            if idle:
                try:
                    import gc
                    if hasattr(model, "model"):
                        with contextlib.suppress(Exception):
                            model.model.to("cpu")
                    gc.collect()
                    logger.info("Local Whisper model unloaded after idle")
                except Exception:
                    pass

    def transcribe(self, audio_path: str, language: str | None = None) -> str | None:
        """转写本地音频为文本；失败/异常返回 None。"""
        if not os.path.isfile(audio_path):
            logger.error("Audio file not found: %s", audio_path)
            return None
        try:
            model = self._load()
            self._last_use = time.monotonic()
            lang = language or self._language
            segments, info = model.transcribe(
                audio_path,
                language=lang,
                vad_filter=self._vad_filter,
                vad_parameters={"min_silence_duration_ms": self._min_silence_ms},
                beam_size=self._beam_size,
                condition_on_previous_text=self._condition_on_previous_text,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text and seg.text.strip())
            text = self._filter_hallucination(text, info)
            if text:
                logger.info("Local STT result (%s, lang=%s): %.60s", self._model_name,
                            info.language if info else lang, text)
            return text or None
        except Exception as e:
            logger.warning("Local STT failed: %s", e)
            return None

    @staticmethod
    def _filter_hallucination(text: str, info: Any) -> str:
        """依据段级/全局概率过滤幻觉（如无音频时重复“谢谢观看”）。"""
        if not text:
            return ""
        try:
            no_speech = getattr(info, "no_speech_prob", 0.0) or 0.0
            avg_logprob = getattr(info, "avg_logprob", 0.0) or 0.0
            duration = getattr(info, "duration", 0.0) or 0.0
        except Exception:
            return text
        if no_speech > _NO_SPEECH_PROB_MAX:
            logger.info("STT hallucination filtered (no_speech_prob=%.2f > %.2f)", no_speech, _NO_SPEECH_PROB_MAX)
            return ""
        if avg_logprob < _AVG_LOGPROB_MIN:
            logger.info("STT hallucination filtered (avg_logprob=%.2f < %.2f)", avg_logprob, _AVG_LOGPROB_MIN)
            return ""
        if duration > 0 and len(text) < _MIN_SEGMENT_CHARS:
            logger.info("STT noise filtered (only %d chars in %.1fs)", len(text), duration)
            return ""
        return text.strip()


class OnlineSTT:
    """在线 STT 封装：复用 ``openkitsune.llm.stt_client.STTClient``。"""

    def __init__(self, endpoints: list[Any] | None = None) -> None:
        self._client: Any = None
        self._endpoints = list(endpoints or [])
        if self._endpoints:
            self._ensure_client()

    def _ensure_client(self) -> None:
        if self._client is None:
            from ..llm.stt_client import STTClient
            self._client = STTClient(self._endpoints)

    @classmethod
    def from_config(cls) -> OnlineSTT:
        """从 llm_endpoints.json 的 stt_endpoints 构建。"""
        try:
            from ..llm.config import load_endpoints_config
            _, _, stt_endpoints, _ = load_endpoints_config()
            return cls(stt_endpoints)
        except Exception as e:
            logger.debug("Could not load STT endpoints: %s", e)
            return cls()

    @property
    def is_available(self) -> bool:
        self._ensure_client()
        return bool(self._client and self._client.is_available)

    def transcribe(self, audio_path: str, language: str | None = None) -> str | None:
        """同步转写（内部跑事件循环）。"""
        self._ensure_client()
        if not self._client or not self._client.is_available:
            logger.warning("[STT] No online STT endpoints configured")
            return None
        try:
            return asyncio.run(self._client.transcribe(audio_path, language=language))
        except RuntimeError:
            # 已存在事件循环（如已在 asyncio 上下文）——复用
            try:
                loop = asyncio.get_event_loop()
                return loop.run_until_complete(self._client.transcribe(audio_path, language=language))
            except Exception as e:
                logger.warning("Online STT failed: %s", e)
                return None
        except Exception as e:
            logger.warning("Online STT failed: %s", e)
            return None

    async def transcribe_async(self, audio_path: str, language: str | None = None) -> str | None:
        """异步转写（供 asyncio 环境直接调用）。"""
        self._ensure_client()
        if not self._client or not self._client.is_available:
            return None
        return await self._client.transcribe(audio_path, language=language)


def build_local_stt() -> LocalSTT:
    """构建本地 STT（配置驱动）。"""
    return LocalSTT()


def build_online_stt() -> OnlineSTT:
    """构建在线 STT（llm_endpoints.json stt_endpoints）。"""
    return OnlineSTT.from_config()


def transcribe_audio(audio_path: str, language: str | None = None) -> str | None:
    """统一语音识别入口。

    ``stt.mode``: ``local`` / ``online`` / ``auto``（默认，本地优先，失败回退在线）。
    纯本地模式（local）在本地不可用时返回 None 而非报错。
    """
    cfg = get_stt_config()
    mode = str(cfg.get("mode") or "auto").lower().strip()
    if mode not in ("local", "online", "auto"):
        logger.warning("Unknown stt.mode=%r, falling back to auto", mode)
        mode = "auto"

    errors: list[str] = []
    if mode in ("local", "auto"):
        local = build_local_stt()
        if local.is_available:
            text = local.transcribe(audio_path, language=language)
            if text:
                return text
            errors.append("local faster-whisper failed")
            if mode == "local":
                return None
        elif mode == "local":
            logger.warning("Local STT unavailable (faster-whisper not installed)")
            return None
        else:
            errors.append("local faster-whisper not installed")

    if mode in ("online", "auto"):
        online = build_online_stt()
        if online.is_available:
            text = online.transcribe(audio_path, language=language)
            if text:
                return text
            errors.append("online STT failed")
        else:
            errors.append("no online STT endpoints configured")

    logger.warning("STT failed via all paths: %s", "; ".join(errors))
    return None
