# 本地化配置统一约定（LOCALIZATION.md）

> 目的：把依赖外部云 API 的技能（视觉/OCR/PPT）全部改为**本地模型优先**，
> 云端仅作**显式 fallback**。所有环境变量统一约定，供各技能 SKILL.md 引用。

## 一、本地端点约定

| 环境变量 | 默认值 | 服务 | 说明 |
|---|---|---|---|
| `LOCAL_LLM_URL` | `http://127.0.0.1:8220/v1` | 文本 LLM（已在运行） | Qwen3.6-35B-A3B-APEX-MTP-I-Compact |
| `LOCAL_LLM_MODEL` | `qwen3.6-35b-a3b` | 文本 LLM | llama.cpp 不校验 model 名 |
| `LOCAL_VISION_URL` | `http://127.0.0.1:8221/v1` | 视觉 LLM（按需启动） | Qwen3.8-35B-A3B-IQ3_M + mmproj |
| `LOCAL_VISION_MODEL` | `qwen3.8-35b-a3b` | 视觉 LLM | 同上 |
| `LOCAL_LLM_TIMEOUT` | `300` | — | 本地 LLM 超时秒数 |

## 二、本地化技能与云端开关

| 技能 | 本地实现 | 云端 fallback 条件 |
|---|---|---|
| `image-understanding` | llama.cpp 视觉端点（OpenAI 兼容） | 本地不可达且设了 `DASHSCOPE_API_KEY`/`OPENAI_API_KEY` |
| `image-understander` | 同上（本地优先） | 本地不可达且设了 `OPENAI_API_KEY` + `OPENAI_VISION_URL` |
| `baidu-paddleocr-text` | `rapidocr_onnxruntime` 本地推理 | 本地失败且设了 `BAIDU_OCR_AK/SK`；或 `USE_CLOUD_OCR=1` 强制云端 |
| `baidu-paddleocr-doc` | 同上（文档识别=文字识别+排序） | 同上（云端支持表格/结构还原） |
| `baidu-ppt-gen` | 本地 LLM 生成结构化大纲 JSON | 无云端依赖（已完全本地化） |

## 三、云端 key（仅显式启用时生效）

```
BAIDU_OCR_AK / BAIDU_OCR_SK    # 百度 OCR 云端
DASHSCOPE_API_KEY              # 通义千问视觉云端
OPENAI_API_KEY                 # OpenAI 云端
OPENAI_VISION_URL              # OpenAI 兼容云端端点（自定义）
USE_CLOUD_OCR=1                # 强制 OCR 走云端
```

## 四、启动视觉服务（按需）

```powershell
powershell -File C:\Users\Administrator\.OpenKitsune\OpenKitsune\skills\_shared\start_vision_server.ps1 -Start
```

探测：不加参数运行同一脚本。

## 五、改造原则（对齐九尾狐「断尾再生」）

- **本地优先**：默认全部走本地模型，零外部依赖、零数据出域；
- **云端显式**：云端只在配置了 key 且本地不可达时兜底，绝不明着静默；
- **不破坏接口**：本地输出与云端**同构 JSON**（如 words_result），调用方无需感知切换；
- **标准库实现**：全部改用 urllib，消除 requests 等 venv 缺失依赖。
