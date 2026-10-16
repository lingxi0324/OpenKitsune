# 飞书 IM 通道 — 功能清单 / 逻辑约束 / 已知问题

> 本文档记录飞书适配器（`feishu.py`）及其与 gateway、session、prompt 等模块的交互逻辑。
> 目的：后续修改或修 bug 时不遗漏既有逻辑约束。

---

## 一、核心功能清单

### 1. 消息接收

| 功能 | 关键代码位置 | 说明 |
|------|------------|------|
| WebSocket 长连接 | `start_websocket()` | 推荐方式，SDK 内置重连 |
| Webhook 回调 | `handle_event()` | 需外部 HTTP 服务器 |
| 消息类型解析 | `_convert_message()` | 支持 text/image/file/audio/video/sticker/merge_forward |
| @mention 检测 | `_convert_message()` 内 `is_mentioned` | 遍历 mentions 匹配 `_bot_open_id` |
| @所有人 检测 | `_convert_message()` 内 `@_all` | 缓冲为事件，不影响 is_mentioned |
| 话题 ID 映射 | `thread_id = root_id` | 同时设置 `reply_to = root_id` |
| 用户名提取 | mentions 占位符替换 | `@_user_N` → 实际名称 |

### 2. 消息发送

| 功能 | 方法 | reply_to 支持 |
|------|------|:---:|
| 文本（纯文本/markdown/卡片） | `send_message()` | ✅ |
| 语音 | `send_voice()` | ✅ |
| 文件/视频 | `send_file()` | ✅ |
| 图片 | `send_photo()` | ✅ |
| 卡片 | `send_card()` | ✅ |
| 辅助文本 | `_send_text()` | ✅ |
| 图片+文本混合 | `send_message()` 图片分支 | ✅ 图片发送后追加文本 |
| 思考状态指示 | `send_typing()` → `_send_thinking_card()` | ✅ 作为用户消息的回复 |
| 占位卡片更新 | `_patch_card_content()` | — PATCH API 更新卡片内容 |
| 消息删除（降级） | `_delete_feishu_message()` | — PATCH 失败时清理占位卡片 |

**约束**：所有发送方法的 `reply_to` 参数用于话题内回复。当 `reply_to` 有值时，使用 `ReplyMessageRequest`；否则使用 `CreateMessageRequest`。新增发送方法必须遵循此模式。

### 3. 启动流程

| 步骤 | 说明 |
|------|------|
| 创建 lark Client | `app_id` + `app_secret` |
| 获取 `_bot_open_id` | 3 次重试，间隔 2 秒 |
| 权限探测 `_probe_capabilities()` | 用无效 ID 调 API 判断权限 |
| 注册事件处理器 | `_setup_event_dispatcher()` |
| 启动 WebSocket/Webhook | 开始接收消息 |

### 4. 事件感知（第三层）

| 事件 | SDK 注册方法 | 处理器 |
|------|------------|--------|
| 群信息更新 | `register_p2_im_chat_updated_v1` | `_on_chat_updated` |
| 机器人入群 | `register_p2_im_chat_member_bot_added_v1` | `_on_bot_chat_added` |
| 机器人被移出 | `register_p2_im_chat_member_bot_deleted_v1` | `_on_bot_chat_deleted` |
| @所有人 | `_convert_message()` 中检测 | 缓冲为 `at_all` 事件 |

事件缓冲在 `_important_events` dict 中，per-chat 上限 10 条，`get_pending_events()` 取出并清空。

### 5. IM 查询工具

| 工具名 | 适配器方法 | 说明 |
|--------|----------|------|
| `get_chat_info` | `get_chat_info()` | 群名/描述/群主/成员数 |
| `get_user_info` | `get_user_info()` | 姓名/邮箱/头像 |
| `get_chat_members` | `get_chat_members()` | 群成员列表 |
| `get_recent_messages` | `get_recent_messages()` | 最近 N 条消息 |

---

## 二、关键逻辑约束（修改时必须保持）

### 约束 1：群聊"偷听"防护（双重过滤）

群消息的过滤有**两道关卡**，缺一不可：

1. **入队前过滤**（`gateway._on_message` 中断路径）：
   当会话正在处理时，新消息进入中断逻辑。对 `mention_only` 模式的群消息，
   如果未 @机器人且不是 stop/skip 指令，**必须 return 丢弃**，不能 INSERT 注入。

2. **出队后过滤**（`gateway._handle_message`）：
   消息从队列取出后，按 `GroupResponseMode` 判断是否处理。
   `mention_only` + `not is_mentioned` → return。

**根因说明**：历史上只有第 2 道关卡，导致用户 @bot 后 bot 处理期间，
同一用户在群里的非 @ 消息被 INSERT 注入上下文，表现为"偷听"。

### 约束 2：`is_mentioned` 的保守策略

- `_bot_open_id` 为 None → `is_mentioned = False`（不偷听，但群里无响应）
- `_bot_open_id` 有值但 mentions 中无匹配 → `is_mentioned = False`
- 绝不能在 `_bot_open_id` 为 None 时 fallback 到 `True` 或 `bool(mentions)`

### 约束 3：话题隔离对称性

- **接收端**：`thread_id = message["root_id"]`，`reply_to = message["root_id"]`
- **发送端**：`reply_target = message.reply_to or message.thread_id` → `ReplyMessageRequest`
- **session 层**：`session_key` 包含 `thread_id`（四段式 `channel:chat_id:user_id:thread_id`）
- **序列化**：`to_dict` / `from_dict` 都包含 `thread_id`

### 约束 4：记忆共享是设计意图

底层记忆（语义记忆、Scratchpad）是跨会话共享的。
"记忆串台"通过 **system prompt 注入 IM 环境信息** 解决，让 LLM 知道当前上下文：
- 平台名称、聊天类型、chat_id、thread_id
- 机器人身份（bot_id）
- 已确认可用能力列表
- 共享记忆警告（提醒 LLM 审慎引用来源不明的记忆）

### 约束 5：事件注入使用 system role

上下文边界标记和待处理事件注入到 session context 时，`role` 必须为 `"system"`。
不能用 `"user"`，否则 LLM 会将系统元数据误解为用户请求。

### 约束 6：IM 工具的平台兼容检查

`IMChannelHandler._handle_im_query_tool` 使用 `type(adapter).method is ChannelAdapter.method`
判断子类是否重写了方法。不能用 `getattr(adapter, method) is ChannelAdapter.method`
（bound method vs function 永远不相等）。

---

## 三、已修复的历史问题

| # | 问题 | 根因 | 修复方案 | 涉及文件 |
|---|------|------|---------|---------|
| 1 | 群聊"偷听" | (a) `_bot_open_id` 为 None 时 is_mentioned fallback 到 `bool(mentions)` (b) 中断路径无群聊过滤 | (a) fallback 改为 False + 重试获取 bot_open_id (b) 中断路径加群聊模式检查 | feishu.py, gateway.py |
| 2 | 记忆串台 | LLM 不知道当前环境 | system prompt 注入 IM 环境信息 + 共享记忆警告 | builder.py, gateway.py |
| 3 | 话题功能失效 | (a) 未传 thread_id (b) 发送用 CreateMessage 而非 ReplyMessage | (a) root_id→thread_id 映射 (b) 全部发送方法支持 reply_to | feishu.py, gateway.py, session.py, manager.py |
| 4 | 权限感知不准 | 无运行时权限检测 | _probe_capabilities 启动时探测 | feishu.py, builder.py |
| 5 | "单机AI"行为 | 无环境感知、无 IM 工具 | 环境信息注入 + 4 个 IM 查询工具 | feishu.py, builder.py, im_channel.py (定义+处理器), agent.py |
| 6 | session 序列化丢 thread_id | to_dict/from_dict 遗漏 | 补全序列化字段 | session.py |
| 7 | voice/file/photo/card 脱离话题 | 无 reply_to 参数 | 全部发送方法加 reply_to 分支 | feishu.py |
| 8 | 图片+文本丢文本 | 图片分支未发送伴随文本 | 发送图片后追加 _send_text | feishu.py |
| 9 | 事件注入 role=user | 误导 LLM | 改为 role=system | gateway.py |
| 10 | TOOLS 列表不全 | handler 白名单未更新 | 同步 8 个工具 | im_channel.py handler |
| 11 | 方法重写检测失败 | bound method is function 永远 False | 改用 type(adapter).method is base.method | im_channel.py handler |
| 12 | _resolve_task_session_id 跨话题误匹配 | 模糊匹配未考虑 thread_id | 加入 thread_id 过滤 | gateway.py |
| 13 | 多 Bot 只有一个能收消息 | `lark_oapi.ws.client` 模块级 `loop` 变量被多实例覆盖，运行时 `create_task` 投递到错误的事件循环 | 用 `importlib.util` 为每个 WS 线程创建独立模块副本，各实例 `loop` 完全隔离（移除旧的 `_ws_startup_lock` 方案） | feishu.py |
| 14 | `feishu_enabled` 与 `im_bots` 重复注册 | 同一 app_id 创建两个 adapter，WebSocket 连接互踢 | 启动时检查 im_bots 是否已有相同 app_id，重复则跳过 | main.py |
| 15 | 消息去重缺失 | WebSocket 重连可能重复投递消息 | `OrderedDict` LRU 去重，容量 500，WebSocket 和 Webhook 路径均覆盖 | feishu.py |
| 16 | 收到消息无已读回执 | 飞书不支持机器人标记已读 | `add_reaction` 添加 [了解] (emoji_type=Get) 表情回复作为回执替代 | feishu.py |
| 17 | `_parse_post_content` 解析失败 | 未处理 i18n 层级 (`post→zh_cn→content`)，缺少 img/media/emotion 标签 | 提取语言层 + 补充标签解析 | feishu.py |
| 18 | `@_user_N` 占位符泄露 | mentions 占位符未替换为实际名称 | `_convert_message` 中遍历 mentions 替换 | feishu.py |
| 19 | `asyncio.get_event_loop()` 弃用警告 | Python 3.12+ 弃用，async 上下文应用 `get_running_loop()` | 全部 12 处替换 | feishu.py |
| 20 | `send_message` 媒体 fallthrough | voices/files/videos 无委托逻辑，掉入空文本分支 | 入口处 early return 委托给 send_voice/send_file | feishu.py |
| 21 | INSERT 路径消息不入会话历史 | `_on_message` INSERT 分支只调用 `insert_user_message(text)` 注入 agent 上下文，从不调用 `session.add_message()`，导致桌面端 IM 界面看不到该消息 | INSERT 分支在调用 `insert_user_message` 前，先获取 session 并调用 `session.add_message()` + `_notify_im_event()` 写入历史 | gateway.py |
| 22 | 系统重启后消息被重复回复 | 飞书 WS 断连后重投递旧消息，`_seen_message_ids` 内存字典在重启时清空 | 增加 `create_time` 时间窗口防护：消息创建超过 120 秒的重投递直接丢弃（WebSocket 和 Webhook 路径均覆盖） | feishu.py |
| 23 | 飞书语音消息处理卡死 | 飞书语音为 Opus 格式（`.opus`），`ensure_whisper_compatible` 只处理 SILK，Opus 直传 Whisper 导致 ffmpeg 内部长时间无输出；Gateway 无超时保护 | (a) `ensure_whisper_compatible` 新增 `.opus/.ogg/.amr/.webm/.wma/.aac` → WAV 的 ffmpeg 转换（30s 超时）(b) Gateway `_process_voice` 增加 60s 下载超时 + 120s 转写超时 (c) `asyncio.gather` 改为 `return_exceptions=True` 避免单个失败拖垮全部 | audio_utils.py, gateway.py |
| 24 | 图片/表情包发送间歇性 `Access denied` | lark-oapi SDK 缓存 `tenant_access_token`（约 1h50min 有效），权限变更后旧 token 不含新 scope，且 SDK 无 401 自动重试机制 | (a) 新增 `_is_token_error` 统一权限错误检测（补充 "access denied"/"scope" 关键词） (b) `_invalidate_token_cache` 通过 `TokenManager.cache.set(key, "", 0)` 强制 token 过期 (c) `_upload_image`/`_upload_file` 首次权限失败后清缓存重试一次 (d) `_probe_capabilities` 启动时探测 `im:resource:upload` 权限并告警 | feishu.py |
| 25 | 飞书 post(富文本) 消息中图片丢失 MediaFile | `_parse_post_content` 将 `img` 标签转为文本占位符 `[图片:image_key]`，不创建 `MediaFile`，导致 `content.images` 为空 → 图片不下载 → LLM 无法看到图片 → 幻觉回复 | 新增 `_parse_post_content_with_media` 方法，遇到 `img`/`media` 标签时同时创建 `MediaFile` 写入 `content.images`/`content.videos`；重构原方法为 `_extract_post_body` + `_render_post_body` 共享逻辑 | feishu.py |
| 26 | 纯媒体消息日志缺少关键信息 | `_log_message` 在 `message.text` 为空时仅输出 `{channel}: received {type}`，缺少 `chat_id`、`channel_user_id` 等排查信息 | 统一日志格式，无论有无文本都输出 `channel_user_id` 和 `chat_id` | base.py |
| 27 | `FeishuQRModal` web 模式崩溃 | 直接 import `@tauri-apps/api/core` 的 `invoke`，web 模式下为 undefined | 改为 import platform 抽象层的 `invoke`；QR 按钮增加 `IS_TAURI` 守卫 | FeishuQRModal.tsx, IMConfigView.tsx |
| 28 | `send_message` 流式分支返回 `session_key` | `_streaming_finalized` 分支 pop `_thinking_cards` 后返回 `sk` 而非 `card_id` | 在 pop 前 `get(sk)` 保存 `card_id`，返回 `card_id or sk` | feishu.py |
| 29 | Webhook 路径缺 `_last_user_msg` | `_handle_message_event` 未记录 `msg_id`，导致 webhook 场景下流式卡片无法回复定位 | 补充 `_last_user_msg[sk] = msg_id` | feishu.py |
| 30 | `stream_token` 丢失早期 token | token 累积在 `card_id` 检查之后，thinking card 未创建时 token 被丢弃 | 将 buffer 累积移到 `card_id` 检查之前 | feishu.py |
| 31 | `_send_response` base_channel 提取错误 | `channel.split("_")[0]` 对 `feishu:bot-id` 格式无法匹配 `_CHANNEL_MAX_LENGTH` | 改为 `channel.split(":")[0].split("_")[0]` | gateway.py |
| 32 | Credential `bool("false") == True` | IMView 将 checkbox 存为字符串 `"true"`/`"false"`，`bool("false")` 恒为 True | 新增 `_cred_bool()` 辅助函数，安全转换字符串布尔值；修复 QQBot sandbox 和新增飞书字段 | main.py |
| 33 | 流式输出是死代码 | `stream_token()`/`finalize_stream()` 虽已实现，但 Gateway 从未调用 | Gateway 新增流式路径：`_call_agent_streaming` 消费 `agent_handler_stream`，pipe token 到 adapter | gateway.py, main.py |
| 34 | Per-Bot 配置不生效 | `_create_bot_adapter` 只传 `app_id`/`app_secret`，流式/群聊配置只读 env | `__init__` 新增 keyword 参数（优先用参数值，None fallback env）；`_create_bot_adapter` 提取 creds 传入 | feishu.py, main.py |
| 35 | Device Flow API 端点 404 | `feishu_onboard.py` base URL 为 `open.feishu.cn`，正确应为 `accounts.feishu.cn`；`init`/`begin` 参数和返回值映射错误 | 修正 base URL 为 `accounts.feishu.cn` / `accounts.larksuite.com`；`init` 仅握手不返回 device_code；`begin` 发送 archetype/auth_method/request_user_info 参数，返回 device_code + verification_uri；`poll` 映射 client_id→app_id | feishu_onboard.py, bridge.py, feishu_onboard route |
| 36 | FeishuQRModal spinner 过大 | `.spinner` CSS 无固定尺寸，填充整个容器 | 加 `width: 32px; height: 32px; margin: 0 auto` 内联样式 | FeishuQRModal.tsx |
| 37 | 添加 Bot 全页崩溃 | `BotConfigTab` 是独立函数组件，未接收 `venvDir`/`apiBaseUrl` props，但飞书 UI 代码引用了这两个变量 → `ReferenceError` | 给 `BotConfigTab` 新增 `venvDir?`/`apiBaseUrl?` props 并从 `IMView` 传入 | IMView.tsx |
| 38 | 流式输出后续消息复用旧卡片 | `finalize_stream` 成功后不清理 `_thinking_cards[sk]`（设计由 `send_message` 清理），但 `streamed_ok=True` 时 `send_message` 被跳过，导致下一轮 `send_typing` 跳过创卡、`stream_token` PATCH 旧卡 | `finalize_stream` 成功后 pop `_thinking_cards[sk]`；`send_typing` 入口清理残留 `_streaming_finalized` | feishu.py |
| 39 | 流式卡片不显示思考过程 | `_call_agent_streaming` 忽略 `thinking_delta`/`thinking_end` 事件，思维链只通过非流式 `progress_callback` 推送独立消息 | 新增 `stream_thinking()` 方法及 `_streaming_thinking` buffer；`_compose_thinking_display()` 组合思考 + 回复内容；Gateway 检查 `chain_push` 后 pipe thinking 事件到 adapter | feishu.py, gateway.py |
| 40 | 流式路径不推送 chain_text 进度到会话后台 | `_call_agent_streaming` 未处理 `chain_text` 事件（工具调用描述、结果摘要等），也未在 `thinking_end` 时调用 `emit_progress_event`，导致会话后台/IM 消息历史完全看不到思维过程 | 新增 `chain_text` 事件处理 → `emit_progress_event`；`thinking_end` 时发送 💭 思考预览进度；finalize 前调用 `flush_progress` 确保进度消息先于回答到达 | gateway.py |
| 41 | `run_skill_script` 找不到技能 | `run_script()` 用 `_loaded_skills.get(name)` 做严格 skill_id 匹配，Agent 传入的 `name` 字段（如 `openkitsune/skills@datetime-tool`）匹配失败 | 改用 `_resolve_skill(name)`，支持 skill_id 和 name 回退查找，与 `get_skill()` 一致 | loader.py |
| 42 | 流式中间进度消息过早消费 thinking card | `emit_progress_event` → `send_text` → `send_message` 无条件 pop `_thinking_cards[sk]`，导致 `finalize_stream` 找不到卡片、返回 False，"思考中..."卡片残留 | Gateway `_call_agent_streaming` 开头初始化 `_streaming_buffers[sk]`；`send_message` 检测 `sk in _streaming_buffers` 时跳过 thinking card 消费 | gateway.py, feishu.py |
| 43 | ForceToolCall 对 REPLY 意图冲突重试 | `[REPLY]` intent + tool_calls=0 仍保留 1 次重试，闲聊场景模型被强制再问"是否该调工具"，产生矛盾提示和额外 token 消耗 | `intent == "REPLY"` 时直接 `return clean_llm_response()`，不重试；`[ACTION]` 和无标记保留完整重试 | reasoning_engine.py |
| 44 | 群聊"智能判断"/"所有消息"模式无效果 | OpenKitsune `group_response_mode` 只控制 gateway 过滤，飞书平台默认只投递 @提及消息 | UI 选择非"仅@时回复"时显示提示："需在飞书后台开启「接收群聊中所有消息」"；适配器启动时输出提醒日志 | IMView.tsx, feishu.py, zh.json, en.json |
| 45 | `/feishu auth` 生成的 OAuth URL 报错 20029 | `get_auth_url()` 硬编码 `redirect_uri` 为占位值，未在飞书后台注册 | 默认不传 `redirect_uri`，让飞书平台自动使用已注册的回调地址 | feishu.py |
| 46 | 非流式模式"思考中..."卡片残留 + 回复显示异常 | 非流式路径中 `_flush`（progress 合并发送）通过 `send_message` 发送进度文本时无条件 pop `_thinking_cards[sk]`，导致：①"思考中..."卡片被 PATCH 为思维过程文本而非最终回复；②`_keep_typing` 重建新卡片后无人消费 → 残留；③最终回复沦为独立新消息而非 PATCH 到占位卡片；④`_send_response` 前未 `flush_progress` 导致进度/回复顺序不稳定。另外飞书 adapter 缺少 `clear_typing` 兜底清理 | ①`_call_agent` 非流式路径也初始化 `_streaming_buffers[sk]` 保护 thinking card，agent 处理完 pop；②`_send_response` 前先 `flush_progress`；③飞书 adapter 新增 `clear_typing` 删除残留卡片；④`clear_typing` 调用传入 `thread_id` 以正确匹配 `sk` | gateway.py, feishu.py |

---

## 四、已知未修复问题（后续迭代处理）

| # | 严重度 | 问题 | 说明 |
|---|--------|------|------|
| 1 | 中 | smart 模式批量缓冲未接入 | `SmartModeThrottle.buffer_message/drain_buffer` 是死代码，smart 模式只有频率限制 |
| ~~2~~ | ~~中~~ | ~~Per-Bot 群响应模式未实现~~ | 已修复（#34）：`FeishuAdapter.__init__` 接受 `group_response_mode` 参数，`_create_bot_adapter` 从 creds 传入 |
| 3 | 中 | download_media 大文件 OOM | `response.file.read()` 整体读入内存 |
| 4 | 中 | 无 API 限流/429 退避 | 高频调用可能被飞书限流 |
| 5 | 低 | _important_events chat key 累积 | 不活跃群的 key 不会清理（每次消费会清空值但 key 不会从 dict 消失） |
| 6 | 低 | Webhook asyncio.create_task 无保护 | 非 async 上下文调用时可能 RuntimeError |
| 7 | 低 | download_media 未校验 response.file | success=True 但 file=None 的边缘情况 |
| 8 | 低 | `@_all` 检测兜底条件可能误报 | `(key and not open_id)` 对注销用户也匹配 |
| 9 | 低 | _PLATFORM_NAMES 缺少 qq 映射 | 不影响功能，显示原始名 |

---

## 五、数据流概览

### 消息接收流程

```
飞书 WebSocket 事件
  → _on_message_receive()          # SDK 事件回调（同步，在 SDK 线程）
    → _handle_message_async()      # run_coroutine_threadsafe 切到主 loop
      → 消息去重（OrderedDict LRU） # message_id 已见过则跳过
      → create_time 陈旧消息防护    # 超过 120s 的重投递丢弃
      → add_reaction(Get)          # fire-and-forget 已读回执（[了解] 表示正在处理）
      → 记录 _last_user_msg[chat_id] = msg_id  # 供 send_typing 回复定位
      → _convert_message()         # 提取消息内容、is_mentioned、thread_id
      → _emit_message()            # 触发 gateway 回调
        → gateway._on_message()    # 中断检查 + 群聊过滤（第 1 道）
          → _message_queue.put()   # 入队
            → _process_loop()
              → _handle_message()  # 系统命令检查 →
                → _send_typing()   # 调用 adapter.send_typing()
                  → 首次: _send_thinking_card() → "💭 思考中..." 卡片
                  → 后续: 已有卡片则跳过
                → _call_agent_with_typing()  # _keep_typing 每 4s 重调 send_typing
                → Agent 返回 → send_message() →
                  → pop _thinking_cards → PATCH 卡片为最终回复
                  → PATCH 失败 → 删除占位卡片 → 正常发送
```

### 消息发送流程（非流式）

```
Agent 生成回复
  → gateway 构造 OutgoingMessage（附带 reply_to / thread_id）
    → adapter.send_message()
      → 检查 _thinking_cards[chat_id]
        → 有卡片: PATCH 更新为最终回复内容 → 成功则直接返回
        → PATCH 失败: 删除占位卡片 → 继续正常发送
      → reply_target = message.reply_to or message.thread_id
      → 媒体类型委托: send_voice/send_file (带 reply_to)
      → 文本/图片: ReplyMessageRequest (reply_target) 或 CreateMessageRequest
      → 图片上传 _upload_image: 含 token 过期自动重试（权限错误 → 清缓存 → 重试 1 次）
      → 图片+文本: 先发图片，后追加 _send_text
```

### 消息发送流程（流式卡片）

```
gateway._call_agent()
  → 条件检查: streaming_enabled + has handler_stream + 非多Agent
  → _call_agent_streaming()
    → agent_handler_stream(session, text)  # async generator
      → chat_with_session_stream() yield SSE events
    → for event in stream:
        text_delta → adapter.stream_token(chat_id, delta, thread_id, is_group)
                     → 累积到 _streaming_buffers
                     → 节流 PATCH 卡片（间隔 _streaming_throttle_ms）
        ask_user   → 作为 reply_text
        error      → 作为 fallback
        done       → break
    → reply_text 非空? → adapter.finalize_stream(chat_id, final_text, thread_id)
                           → 最终 PATCH + _streaming_finalized 标记
                           → return (text, True)
    → reply_text 空?   → return (text, False) → 走 _send_response 正常路径
  → _handle_message: streamed_ok=True 时跳过 _send_response
```

### session_key 格式

```
三段式（非话题）: {channel}:{chat_id}:{user_id}
四段式（话题内）: {channel}:{chat_id}:{user_id}:{thread_id}

示例:
  feishu:oc_abc123:ou_user1                     # 主聊天
  feishu:oc_abc123:ou_user1:om_root_msg_id      # 话题内
```

---

## 六、修改检查清单

修改飞书 IM 通道相关代码时，请逐一确认：

- [ ] 新增的发送方法是否支持 `reply_to` 参数？
- [ ] `is_mentioned` 逻辑是否仍然在 `_bot_open_id=None` 时返回 False？
- [ ] `session_key` 是否在所有生成位置保持一致（session.py / manager.py / gateway.py）？
- [ ] 新增的系统消息注入是否使用 `role="system"`？
- [ ] gateway 的中断路径是否包含群聊过滤？
- [ ] IM 工具是否在 4 层（definitions / handler TOOLS / handler route / agent register）同步？
- [ ] 方法重写检测是否使用 `type(adapter).method is Base.method` 而非 `getattr`？
- [ ] thread_id 是否在序列化/反序列化中包含？
- [ ] 多 Bot 场景：`_run_ws_in_thread` 是否为每个线程创建独立模块副本（不共享 `lark_oapi.ws.client.loop`）？
- [ ] 消息去重后是否有 `create_time` 陈旧消息防护（防止重启后重复处理）？

---

## 七、多 Bot 飞书平台侧检查清单

如果代码正确但某个 Bot 仍无法收到消息，请检查飞书开发者后台：

- [ ] 该应用是否启用了「机器人」能力
- [ ] 是否订阅了 `im.message.receive_v1` 事件
- [ ] 是否发布了最新版本（草稿状态的应用不推送事件）
- [ ] 事件订阅方式是否为「长连接」模式（而非 Webhook）
- [ ] 应用可见范围是否包含目标用户/群聊

---

## 八、v1.25 新增功能（飞书 IM 增强）

### 1. QR 扫码创建机器人（Device Flow）

| 模块 | 说明 |
|------|------|
| `setup/feishu_onboard.py` | FeishuOnboard 类：init → begin → poll 三步流程 |
| `setup_center/bridge.py` | 新增子命令：`feishu-onboard-start` / `feishu-onboard-poll` / `feishu-validate` |
| `setup/wizard.py` | `_configure_feishu()` 改为三选一菜单（扫码/手动/现有） |
| `main.rs` | Tauri invoke 注册：`openkitsune_feishu_onboard_start` / `poll` / `validate` |
| `FeishuQRModal.tsx` | 前端 QR 弹窗组件 + 轮询状态机 |
| `IMConfigView.tsx` | 飞书配置区新增扫码按钮 |

**约束**：
- Device Flow API 端点为 `/oauth/v1/app/registration`，Content-Type 为 `application/x-www-form-urlencoded`
- 飞书使用 `open.feishu.cn`，Lark 使用 `open.larksuite.com`
- bridge.py 是无状态的，`device_code` 由前端在 init→poll 之间传递

### 2. 流式卡片输出

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `FEISHU_STREAMING_ENABLED` | `false` | 启用流式输出 |
| `FEISHU_GROUP_STREAMING` | `false` | 群聊中也启用流式 |
| `FEISHU_STREAMING_THROTTLE_MS` | `800` | 流式 PATCH 节流间隔(ms) |

**实现细节**：
- `stream_token(chat_id, token)` 累积 token 到缓冲区，按节流间隔 PATCH 更新卡片
- `finalize_stream(chat_id, final_text)` 最终 PATCH，成功后设置 `_streaming_finalized` 标记
- `send_message()` 检测到 `_streaming_finalized` 时跳过重复发送
- PATCH 失败回退：删除占位卡片 → 走正常 `send_message` 路径
- 流式显示时卡片内容追加 ` ▍` 光标指示符

**约束**：
- `_thinking_cards` / `_last_user_msg` / `_streaming_buffers` 的 key 均使用 `session_key`（`chat_id:thread_id`），不再使用纯 `chat_id`
- 同一 session 不能同时有流式和非流式输出

### 3. 群聊回复模式 Per-Bot 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `FEISHU_GROUP_RESPONSE_MODE` | 未设置（使用全局） | `mention_only` / `smart` / `always` |

**实现**：
- `FeishuAdapter.__init__` 读取环境变量存入 `_group_response_mode`
- `gateway._get_group_response_mode()` 优先取 adapter 的 per-bot 配置，再 fallback 全局

### 4. 话题级并行处理

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `MAX_CONCURRENT_SESSIONS` | `5` | 最大并发处理会话数（全局） |

**实现**：
- `_process_loop` 改为并发调度：每条消息 `asyncio.create_task(_session_dispatch)`
- `_session_dispatch` 使用 `_concurrency_sem` 信号量控制并发上限
- 同一 session_key 内的消息仍由中断机制保证顺序

**约束**：
- `_processing_sessions` 必须在 `_interrupt_lock` 下修改
- `_session_tasks` 用于跟踪活跃的 session task（abort 快路径需要取消）

### 5. 中断快路径

**实现**：
- `_on_message` 在获取 `_interrupt_lock` 之前做低成本文本检测
- `_is_abort_text()` 剥离 @提及后检查多语言停止词集合
- 命中时 `_cancel_session()` 直接取消 agent 任务 + asyncio Task
- 多语言停止词：中文（停止/取消/算了/不用了...）、英文（stop/halt/abort/cancel）、日语、韩语

### 6. 端到端流式输出管道

**之前**：`stream_token()` / `finalize_stream()` 已在 adapter 实现但未被 Gateway 调用（死代码）。

**现在**：
- `main.py` 新增 `agent_handler_stream` 异步生成器，包装 `agent.chat_with_session_stream`
- `gateway._call_agent()` 返回值改为 `tuple[str, bool]`（`response_text, streamed_ok`）
- 条件满足时自动走 `_call_agent_streaming`：消费 SSE events → `adapter.stream_token()` → `adapter.finalize_stream()`
- `_handle_message` 检查 `streamed_ok`，为 True 时跳过 `_send_response`，避免重复发送

**流式条件**（全部满足才启用）：
1. `allow_streaming=True`（中断路径强制 False）
2. adapter 有 `is_streaming_enabled` 且返回 True
3. `agent_handler_stream` 已设置
4. 非多 Agent 模式

**边界处理**：
- 空回复：不调 `finalize_stream`，返回 `(text, False)` 走正常发送
- 流式异常：catch 后返回错误文本 + `False`
- `_call_agent_with_typing` 签名同步更新为返回 tuple

### 7. `/feishu` 对话命令

| 命令 | 功能 | 实现位置 |
|------|------|---------|
| `/feishu start` | 返回 adapter 版本、App ID、连接状态、流式/群聊配置 | `gateway._handle_feishu_command` → `adapter.get_status_info()` |
| `/feishu auth` | 返回飞书 OAuth2 用户授权 URL | `gateway._handle_feishu_command` → `adapter.get_auth_url()` |
| `/feishu help` | 显示命令帮助 | `gateway._handle_feishu_command` |

**约束**：仅 `message.channel.split(":")[0] == "feishu"` 时生效，其他渠道跳过。

### 8. IM Bot 管理界面集成

**之前**：飞书特有配置（QR 扫码、流式开关、群聊模式）只在 `IMConfigView`（全局环境变量配置页），Bot 管理界面无法 per-bot 配置。

**现在**：`IMView.tsx` 编辑面板新增：
- QR 扫码创建机器人按钮（需 `IS_TAURI && venvDir`）
- 流式卡片输出开关（`credentials.streaming_enabled`）
- 群聊流式开关（条件可见，`credentials.group_streaming`）
- 群聊回复模式三选一（`mention_only` / `smart` / `always`）

`App.tsx` 传递 `venvDir` prop 给 `IMView`。

---

## 九、新增环境变量汇总

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `FEISHU_STREAMING_ENABLED` | bool | `false` | 飞书流式卡片输出 |
| `FEISHU_GROUP_STREAMING` | bool | `false` | 飞书群聊流式输出 |
| `FEISHU_STREAMING_THROTTLE_MS` | int | `800` | 流式 PATCH 节流间隔 |
| `FEISHU_GROUP_RESPONSE_MODE` | enum | — | Per-Bot 群聊回复模式 |
| `MAX_CONCURRENT_SESSIONS` | int | `5` | 全局最大并发会话数 |

---

## 十、新增文件清单

| 文件 | 说明 |
|------|------|
| `src/openkitsune/setup/feishu_onboard.py` | Device Flow 扫码建应用 + 凭证校验 |
| `apps/setup-center/src/components/FeishuQRModal.tsx` | 飞书 QR 扫码弹窗组件 |
