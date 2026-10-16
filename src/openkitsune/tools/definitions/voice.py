"""
语音工具定义

包含语音检测、语音识别、语音合成相关工具:
- text_to_speech:     将文本合成为语音（多引擎：edge/openai/elevenlabs/minimax/xai/mistral/gemini/本地）
- transcribe_audio:   将音频文件转写为文本（本地 faster-whisper / 在线 STT）
- voice_record:       麦克风录音 + VAD 语音检测（静音自动停止），返回 WAV
- voice_listen:       持续监听说话（Barge-in 抢话检测），返回是否触发
"""

VOICE_TOOLS = [
    {
        "name": "text_to_speech",
        "category": "Voice",
        "description": "Convert text into an audio file (TTS) using configurable engines (edge/openai/elevenlabs/minimax/xai/mistral/gemini/piper/kittentts/neutts). Use when the user asks to speak, read aloud, or generate voice audio.",
        "detail": """将文本合成为语音音频文件。

**引擎选择**：
- 默认 `edge`（微软神经语音，免费无需 Key）
- `openai` / `deepinfra`：OpenAI 兼容（需 API Key）
- `elevenlabs`：需 ELEVENLABS_API_KEY
- `minimax`：需 MINIMAX_API_KEY（或 MINIMAX_CN_API_KEY）
- `xai`：需 XAI_API_KEY
- `mistral`：需 MISTRAL_API_KEY
- `gemini`：需 GEMINI_API_KEY
- `piper` / `kittentts` / `neutts`：本地引擎（首次自动下载模型）

**文本清理**：自动去除 Markdown 标记、展开符号（°C/¥/$ 等）、移除 emoji，
生成适合朗读的语音脚本；长文本自动按引擎上限分块合成后合并。

**输出**：默认生成 mp3；可指定 wav/ogg。`voice_compatible=true` 时输出
Ogg/Opus 语音气泡格式（telegram/飞书等平台原生可播放）。

**注意**：
- 输出文件路径需通过 deliver_artifacts 交付给用户
- 文本为空或清理后无内容会失败
- 需要用户先确认是否要朗读（涉及外部 API 调用时）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "待合成为语音的文本内容",
                },
                "provider": {
                    "type": "string",
                    "enum": [
                        "edge",
                        "openai",
                        "deepinfra",
                        "elevenlabs",
                        "minimax",
                        "xai",
                        "mistral",
                        "gemini",
                        "piper",
                        "kittentts",
                        "neutts",
                    ],
                    "description": "TTS 引擎（默认 edge，免费）",
                },
                "output_path": {
                    "type": "string",
                    "description": "输出文件路径（.mp3/.wav/.ogg），可选；默认自动生成",
                },
                "voice_compatible": {
                    "type": "boolean",
                    "description": "输出 Ogg/Opus 语音气泡格式（适配聊天平台语音消息）",
                },
                "format": {
                    "type": "string",
                    "enum": ["mp3", "wav", "ogg"],
                    "description": "输出格式（默认 mp3）",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "transcribe_audio",
        "category": "Voice",
        "description": "Transcribe an audio file to text (STT). Supports local faster-whisper (offline, private) and online endpoints (OpenAI Whisper / DashScope Qwen-ASR). Use when the user uploads voice messages or audio and wants the content.",
        "detail": """将音频文件转写为文本。

**识别路径**（按 stt.mode 配置，默认 auto）：
- `local`：本地 faster-whisper（离线、隐私安全，首次自动下载模型）
- `online`：OpenAI Whisper API / DashScope Qwen-ASR（llm_endpoints.json 的 stt_endpoints）
- `auto`：本地优先，失败回退在线

**本地模型配置**（data/voice_config.json）：
```json
{"stt": {"mode": "auto", "model": "base", "language": "zh", "device": "auto"}}
```

**支持格式**：mp3, mp4, wav, webm, m4a, ogg, flac

**注意**：
- 音频过长（>25MB）时先压缩/截断再转写
- 转写失败返回错误信息""",
        "input_schema": {
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": "待转写的音频文件路径",
                },
                "language": {
                    "type": "string",
                    "description": "语言代码（如 zh/en/ja），可选；默认自动检测",
                },
            },
            "required": ["audio_path"],
        },
    },
    {
        "name": "voice_record",
        "category": "Voice",
        "description": "Record audio from the microphone with voice activity detection (VAD): auto-stops on silence after speech, returns a WAV file. Use when the user wants to record their voice.",
        "detail": """麦克风录音 + 语音活动检测（VAD）。

**行为**：
- 检测到语音后开始正式录音（带预卷缓冲，不丢开头）
- 说话结束连续静音 1.2 秒自动停止（可配置）
- 最长等待 15 秒无语音自动停止
- 过短/过安静录音自动丢弃

**配置**（data/voice_config.json）：
```json
{"vad": {"silence_threshold": 200, "silence_duration": 1.2, "max_wait": 15}}
```

**注意**：
- 需要麦克风权限（sounddevice/numpy）
- 返回的 WAV 路径需通过 deliver_artifacts 交付""",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {
                    "type": "string",
                    "description": "录音输出路径（.wav），可选；默认自动生成",
                },
            },
        },
    },
    {
        "name": "voice_listen",
        "category": "Voice",
        "description": "Listen for speech with barge-in detection (interrupting playback). Returns whether speech was detected and optionally the captured audio. Use to detect user interruption during TTS playback or voice conversations.",
        "detail": """持续监听说话（Barge-in 抢话检测）。

**行为**：
- 阻塞监听直到检测到持续语音（约 300ms 连续超阈值）
- 自动校准环境噪声底（前 400ms），只对明显高于环境的语音触发
- `capture=true` 时录制打断话语（带预卷缓冲），返回 WAV 路径
- 停止条件：检测到语音、或超时

**注意**：
- 需要麦克风（sounddevice/numpy）
- 超时返回 None/False""",
        "input_schema": {
            "type": "object",
            "properties": {
                "capture": {
                    "type": "boolean",
                    "description": "是否录制检测到的语音（返回 WAV 路径而非布尔）",
                },
                "timeout": {
                    "type": "number",
                    "description": "最长监听秒数（默认 15）",
                },
                "output_path": {
                    "type": "string",
                    "description": "捕获录音输出路径（.wav），可选",
                },
            },
        },
    },
]
