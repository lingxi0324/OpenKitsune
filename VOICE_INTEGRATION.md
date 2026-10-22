# OpenKitsune 语音能力整合说明

> 迁移自 `C:\Users\Administrator\.hermes\hermes-agent\`（hermes-agent 语音栈），
> 按 OpenKitsune 架构重构后集成。覆盖**语音检测（VAD）、语音识别（STT）、语音合成（TTS）**三大能力。

---

## 1. 迁移来源与策略

### 来源模块（hermes-agent）
| 能力 | hermes 源文件 | 迁移要点 |
|---|---|---|
| 语音检测 VAD | `tools/voice_mode.py` | RMS 能量检测、静音自动停止、预卷缓冲、BargeDetector 抢话检测、全双工监听 |
| 语音识别 STT | `tools/transcription_tools.py` / `transcription_local.py` | 本地 faster-whisper（模型缓存/CUDA 回退/防幻觉过滤）+ 云端多 Provider |
| 语音合成 TTS | `tools/tts_tool.py` / `tts_tool_providers.py` / `tts_tool_openai.py` / `tts_tool_local.py` / `tts_tool_delivery.py` / `tts_text_normalize.py` / `audio_container.py` | 多引擎分发、长文本分块、ffmpeg 交付、容器嗅探修复、朗读文本清理 |

### 迁移策略
- **不照搬 hermes 内部框架**：hermes 语音代码深度耦合 `hermes_cli.config`、`tools.registry`、`gateway`、`agent.provider_registry` 等。
  迁移时按 OpenKitsune 架构重写配置读取、日志、工具注册与交付方式。
- **复用 OpenKitsune 已有能力**：在线 STT 复用 `llm/stt_client.py`（llm_endpoints.json 的 `stt_endpoints`）、
  SILK→WAV 转码复用 `channels/media/audio_utils.py`。
- **工具注册走标准模式**：`tools/definitions/voice.py` 定义 4 个工具，`tools/handlers/voice.py` 实现，
  在 `_agent_runtime.py::_init_handlers` 注册。

---

## 2. 新增代码结构

```
src/openkitsune/voice/
├── __init__.py          # 核心 API 导出
├── config.py            # 语音配置（data/voice_config.json + 环境变量）
├── text_normalize.py    # 朗读文本清理（Markdown/符号/emoji 归一化）
├── audio.py             # WAV 包装、ffmpeg 转码、容器嗅探、长文本分块、交付打包
├── vad.py               # 语音检测：AudioRecorder、listen_for_speech、full_duplex_listen、BargeDetector、播放控制
├── stt.py               # 语音识别：LocalSTT（faster-whisper）+ OnlineSTT（复用 STTClient）
├── tts.py               # 语音合成主分发器（引擎选择、分块、合并、交付）
├── tts_providers.py     # 云引擎：edge/openai/deepinfra/elevenlabs/minimax/xai/mistral/gemini
└── tts_local.py         # 本地引擎：piper/kittentts/neutts
```

### 工具清单（新增 4 个）
| 工具 | 能力 | 默认行为 |
|---|---|---|
| `text_to_speech` | 文本→语音 | edge（免费），自动语言适配 |
| `transcribe_audio` | 音频→文本 | auto：本地 faster-whisper 优先，失败回退在线 |
| `voice_record` | 麦克风录音+VAD | 静音自动停止，返回 WAV |
| `voice_listen` | 持续监听/Barge-in | 抢话检测，可捕获打断语音 |

---

## 3. 配置说明

### 配置文件：`<project_root>/data/voice_config.json`（可选，缺失时用默认值）

```json
{
  "output_dir": "data/voice_cache",
  "vad": {
    "sample_rate": 16000,
    "silence_threshold": 200,
    "silence_duration": 1.2,
    "max_wait": 15.0,
    "min_speech_duration": 0.3,
    "max_dip_tolerance": 0.3,
    "max_recording_seconds": 0
  },
  "stt": {
    "mode": "auto",
    "model": "base",
    "language": "zh",
    "device": "auto"
  },
  "tts": {
    "provider": "edge",
    "output_format": "mp3",
    "edge": {"voice": "zh-CN-XiaoxiaoNeural"},
    "openai": {"model": "gpt-4o-mini-tts", "voice": "alloy"},
    "elevenlabs": {"voice_id": "pNInz6obpgDQGcFmaJgB"},
    "minimax": {"region": "global", "model": "speech-02-hd"},
    "xai": {"voice_id": "eve"},
    "mistral": {"model": "voxtral-mini-tts-2603"},
    "gemini": {"model": "gemini-2.5-flash-preview-tts", "voice": "Kore"},
    "piper": {"voice": "en_US-lessac-medium"},
    "kittentts": {"model": "KittenML/kitten-tts-nano-0.8-int8"},
    "neutts": {"model": "neuphonic/neutts-air-q4-gguf"}
  }
}
```

### 环境变量（API Key）
| 引擎 | 环境变量 |
|---|---|
| OpenAI / DeepInfra | `OPENAI_API_KEY` / `DEEPINFRA_API_KEY` |
| ElevenLabs | `ELEVENLABS_API_KEY` |
| MiniMax | `MINIMAX_API_KEY`（global）/ `MINIMAX_CN_API_KEY`（cn） |
| xAI | `XAI_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |
| Gemini | `GEMINI_API_KEY`（或 `GOOGLE_API_KEY`） |

> 在线 STT（`stt.mode=online`）复用 `data/llm_endpoints.json` 的 `stt_endpoints`（OpenAI Whisper / DashScope Qwen-ASR）。

---

## 4. 依赖

已在 `pyproject.toml` 声明（`[project.optional-dependencies]`）：

| extra | 依赖 | 用途 |
|---|---|---|
| `voice` | `pilk`、`sounddevice`、`numpy`、`faster-whisper`、`edge-tts` | VAD 录音 + 本地/在线 STT + 免费 TTS |
| `voice-tts-cloud` | `openai`、`elevenlabs`、`mistralai` | 云 TTS 引擎 |
| `voice-tts-local` | `piper-tts`、`soundfile` | 本地 TTS 引擎 |

安装方式：`pip install -e ".[voice]"`（可加 `voice-tts-cloud` / `voice-tts-local`）。
ffmpeg 需在 PATH（转码/合并/语音气泡必需）。

---

## 5. 验证记录

| 项 | 结果 |
|---|---|
| 11 个新文件 `py_compile` | ✅ 全部通过 |
| `openkitsune.voice` 导入 | ✅ OK |
| 4 个工具注册进 `BASE_TOOLS` | ✅ 116 个工具 |
| classifier 完整性测试（`test_classifier_completeness.py`） | ✅ 39 passed |
| handler 注册链路（SystemHandlerRegistry） | ✅ 4 工具均 INTERACTIVE |
| **集成测试（`tests/unit/test_voice_integration.py`）** | ✅ **20 passed** |
| edge TTS 中文合成（自动选 zh-CN-XiaoxiaoNeural） | ✅ 64KB mp3 |
| edge TTS 英文合成 | ✅ OK |
| 长文本分块（10660 字符 → 3 块） | ✅ 分块正确 |
| 多块合并（ffmpeg concat，超 10MB 上限打包） | ✅ part01/part02 |
| 两种调用上下文（无/有事件循环） | ✅ 均正常 |
| 容器嗅探（ogg/wav/mp3） | ✅ 识别正确 |
| 文本清理（Markdown/°C/%/emoji） | ✅ 正确 |
| Agent 启动冒烟（voice handler 注册映射） | ✅ 4 工具映射成功 |

### 集成测试覆盖（`tests/unit/test_voice_integration.py`）

20 个用例分 6 组，全部经真实 ToolExecutor 链路执行：

1. **文本清理**（4 例）：Markdown 符号、emoji、`<think>` 块剔除，°C/% 朗读化
2. **长文本分块**（3 例）：上限内不分块、超限正确切分且内容无损、空输入安全
3. **音频工具**（3 例）：WAV 头包装、容器嗅探（ogg/wav/mp3）、WAV 可读性
4. **ToolExecutor 完整链路**（6 例）：`text_to_speech` 真实 edge 合成、未知 provider 报错、空文本报错、`transcribe_audio` 缺失文件报错、无语音文件防幻觉失败路径、未知 voice 工具名拦截
5. **VAD 核心**（2 例）：RMS 阈值判定（响/静音对比）、播放中标记翻转
6. **语音消息衔接**（2 例）：`MessageContent.voices` 的 MediaFile 接口、SILK→WAV 转码工具引用完整性

### 相关回归

- `test_classifier_completeness.py`：39 passed ✅
- `test_tool_progressive_disclosure.py`：1 passed / 2 failed —— **存量失败，与语音改动无关**（该测试自建 Mock context 与硬编码工具列表，不引用 BASE_TOOLS/voice/_init_handlers；失败点在 `_reason_stream_impl` 对 Mock working_messages 调用 `len()`，系测试 fixture 与推理运行时当前实现的版本漂移）

### 已知限制
- **edge 引擎语言适配**：默认英文语音读中文会抛 `NoAudioReceived`，已实现按文本语言自动选
  zh-CN/ja-JP/ko-KR 语音；如需固定请配置 `tts.edge.voice`。
- **edge 端点 403**：微软经典端点自 2026 年起 403，已内置 `edge_tts_compat.py` 补丁
  （自动切换 api.msedgeservices.com），无需人工干预。
- **录音/VAD** 需物理麦克风与 `sounddevice` 依赖（未在本机实测录音，已通过逻辑验证与导入验证）。

### v2.1 完善记录（2026-10-22，对照 hermes-agent 语音栈）

| 项 | 说明 |
|---|---|
| 运行时依赖 | `.venv` 已装 `edge-tts 7.3.1 / sounddevice 0.5.6 / faster-whisper 1.2.1 / pilk 0.2.4 / soundfile 0.14.0`（此前代码已迁移但依赖缺失，语音能力实际不可用） |
| `edge_tts_compat.py` | 新增：edge-tts 端点 403 补丁（api.msedgeservices.com），`generate_edge_tts` 自动应用 |
| `neutts_synth.py` | 新增：NeuTTS 独立合成脚本（hermes 移植），`tts_local._generate_neutts` 增加 ref_audio/ref_text 前置校验与清晰报错 |
| `tts_streaming.py` | 新增：流式 TTS —— `SentenceChunker`（增量句子切分，剔除推理块，兼容中英文句读）+ PCM 流式引擎（openai/gemini/elevenlabs/xai）+ `stream_tts_to_speaker` 高层入口（edge 等无分块 API 引擎按句同步合成逐句播放）+ 抢话闩锁 |
| `tts_command.py` | 新增：命令型 TTS provider（`tts.providers.<name>.command`，占位符引号感知转义、空闲超时+进程树清理）；`tts.py` 的 `_is_command_provider` 由 stub 改为真实解析，非内置 provider 名可解析到命令引擎 |
| `stt.py` hf 镜像 | `stt.hf_endpoint`（如 https://hf-mirror.com）驱动 HF 模型下载；自动禁用 XetData（`HF_HUB_DISABLE_XET`，其 CAS 端点不认镜像且匿名 401），并建议 `huggingface-hub<2`（2.x 新版下载流不兼容镜像） |
| 实测 | edge TTS 中文合成 ✅（29KB mp3）；TTS→STT 闭环 ✅（faster-whisper base 经镜像下载后转写 mp3 成功）；离线测试子集 9 passed |

### v2.1 使用示例（新增能力）

```python
from openkitsune.voice.tts_streaming import stream_tts_to_speaker, SentenceChunker

# 流式朗读（edge 默认按句合成播放；openai/gemini 等配置后走 PCM 流式）
stream_tts_to_speaker("你好，这是一段流式朗读测试。", on_sentence=print)

# 命令型 TTS（data/voice_config.json）
# {"tts": {"providers": {"piper-local": {"type": "command",
#    "command": "piper -f {output_path} < {input_path}", "voice": "zh_CN-huayan-medium"}}}}
from openkitsune.voice import synthesize_text
print(synthesize_text("测试", provider="piper-local")["paths"])
```

---

## 6. 文件变更清单

| 文件 | 变更 |
|---|---|
| `src/openkitsune/voice/*`（11 个新文件） | 新增：语音能力包 |
| `src/openkitsune/tools/definitions/voice.py` | 新增：4 个工具定义 |
| `src/openkitsune/tools/definitions/__init__.py` | 修改：导入并合并 `VOICE_TOOLS` |
| `src/openkitsune/tools/handlers/voice.py` | 新增：语音处理器 |
| `src/openkitsune/core/_agent_runtime.py` | 修改：注册 `voice` handler |
| `pyproject.toml` | 修改：新增 `voice-tts-cloud` / `voice-tts-local`，扩充 `voice` extra |
| `.venv` | 修改：已安装 `edge-tts 7.3.1 / sounddevice / faster-whisper / pilk / soundfile`；`huggingface-hub<2`（镜像兼容）；openkitsune 可编辑安装已重指向 D:\ai\OpenKitsune-main\src |
| `src/openkitsune/voice/edge_tts_compat.py` | 新增（v2.1）：edge 端点 403 补丁 |
| `src/openkitsune/voice/neutts_synth.py` | 新增（v2.1）：NeuTTS 独立合成脚本 |
| `src/openkitsune/voice/tts_streaming.py` | 新增（v2.1）：流式 TTS（句子切分 + PCM 流式引擎 + 播放） |
| `src/openkitsune/voice/tts_command.py` | 新增（v2.1）：命令型 TTS provider |
| `src/openkitsune/voice/tts.py` / `tts_local.py` / `tts_providers.py` / `stt.py` | 修改（v2.1）：命令 provider 接入、neutts 校验、edge 补丁、hf 镜像 |
| `tests/unit/test_voice_integration.py` | 新增：语音能力集成测试（20 用例） |
| `src/openkitsune/api/routes/chat.py` | 修改（v2.2）：回复完成前自动 TTS 合成并注入 `artifact_type="voice"` 事件（见第 8 节） |
| `data/voice_config.json` | 修改（v2.2）：新增 `tts.reply_voice`（对话语音回复开关） |
| `VOICE_INTEGRATION.md` | 新增：本说明文档 |

---

## 8. 对话语音回复（v2.2，Web 用户端自动发声）

Web 聊天（POST /api/chat SSE 流）在每轮回复完成后，若配置开启 `tts.reply_voice`，
后端自动把回复文本交给 openkitsune.voice 合成 mp3，并以 `artifact` 事件
（`artifact_type="voice"`）注入流尾（done 之前）。前端 `Artifacts.tsx` 对
`voice` 类型渲染 `<audio controls>` 播放器——**零前端改动**，每条 assistant
消息自动出现"语音回复 · 点击播放"音频条；会话持久化时随 artifacts 一起保存，
历史重放同样可见。

配置（`data/voice_config.json`）：

```json
{
  "tts": {
    "provider": "edge",
    "reply_voice": {
      "enabled": true,
      "max_chars": 500,
      "caption": "语音回复 · 点击播放"
    }
  }
}
```

- `enabled: false` 可关闭；`max_chars` 超长回复不自动合成（避免拖慢）；
  合成失败/超时（20s）静默跳过，绝不阻塞文本回复。
- 产出目录：会话工作区 `voice_replies/`（受 /api/files 作用域约束）。
- 实测（2026-10-22）：短对话 SSE 流自动出现 `artifact(voice)`，114KB mp3，
  `/api/files` 返回 200 audio/mpeg ✅。

### 可选升级（未做，需前端改动 + `npm run build:web`）
- 回复到达后**自动播放**（浏览器需一次用户交互授权，建议默认关、设置里开关）；
- 浏览器端 `speechSynthesis` 即时朗读（音色为系统语音，非神经语音）。

---

## 7. 使用示例

```python
from openkitsune.voice import synthesize_text, transcribe_audio

# TTS（默认 edge 免费引擎，自动语言适配）
result = synthesize_text("你好，这是语音合成。", provider="edge", format="mp3")
print(result["paths"])  # -> [输出 mp3 路径]

# STT（本地 faster-whisper 优先，失败回退在线）
text = transcribe_audio("recording.wav", language="zh")
print(text)

# VAD 录音（静音自动停止）
from openkitsune.voice import create_audio_recorder
recorder = create_audio_recorder()
recorder.start()
# ... 等待静音自动停止 ...
wav_path = recorder.stop()
```

```bash
# CLI 冒烟测试
pip install -e ".[voice]"
python -c "from openkitsune.voice import synthesize_text; r = synthesize_text('你好'); print(r['paths'])"
```
