"""语音能力包 —— 整合语音检测（VAD）、语音识别（STT）、语音合成（TTS）。

迁移自 hermes-agent 语音栈（voice_mode / transcription_* / tts_tool_*），
按 OpenKitsune 架构重构：

- :mod:`.vad`     语音检测：RMS 能量检测、静音自动停止、预卷、抢话检测、全双工监听
- :mod:`.stt`     语音识别：本地 faster-whisper + 在线 STTClient（llm_endpoints.json stt_endpoints）
- :mod:`.tts`     语音合成：edge/openai/deepinfra/elevenlabs/minimax/xai/mistral/gemini/piper/kittentts/neutts
- :mod:`.tts_streaming`  流式语音播报：句子增量切分、PCM 流式引擎、逐句播放、抢话闩锁
- :mod:`.audio`   音频工具：WAV 包装、ffmpeg 转码、容器嗅探、长文本分块、交付打包
- :mod:`.config`  语音配置（data/voice_config.json + 环境变量）
- :mod:`.text_normalize`  朗读文本清理（Markdown/符号归一化）
"""

from __future__ import annotations

from .config import (
    BUILTIN_TTS_PROVIDERS,
    get_tts_config,
    get_tts_provider,
    load_voice_config,
    reload_voice_config,
)
from .stt import (
    LocalSTT,
    OnlineSTT,
    build_local_stt,
    build_online_stt,
    transcribe_audio,
)
from .text_normalize import prepare_spoken_text
from .tts import (
    list_available_providers,
    resolve_max_text_length,
    synthesize_text,
)
from .tts_streaming import (
    SentenceChunker,
    mark_speech_interrupted,
    stream_tts_to_speaker,
    take_speech_interrupted,
)
from .vad import (
    AudioRecorder,
    create_audio_recorder,
    full_duplex_listen,
    is_audio_output_active,
    listen_for_speech,
    mark_audio_output_active,
    play_audio_file,
    stop_playback,
)

__all__ = [
    # config
    "BUILTIN_TTS_PROVIDERS",
    "get_tts_config",
    "get_tts_provider",
    "load_voice_config",
    "reload_voice_config",
    # stt
    "LocalSTT",
    "OnlineSTT",
    "build_local_stt",
    "build_online_stt",
    "transcribe_audio",
    "prepare_spoken_text",
    # tts
    "list_available_providers",
    "resolve_max_text_length",
    "synthesize_text",
    # tts_streaming
    "SentenceChunker",
    "mark_speech_interrupted",
    "stream_tts_to_speaker",
    "take_speech_interrupted",
    # vad
    "AudioRecorder",
    "create_audio_recorder",
    "full_duplex_listen",
    "is_audio_output_active",
    "listen_for_speech",
    "mark_audio_output_active",
    "play_audio_file",
    "stop_playback",
]
