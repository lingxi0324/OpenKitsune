# OneBot IM 通道 — 功能清单 / 逻辑约束 / 已知问题

> 本文档记录 OneBot v11 适配器（`onebot.py`）及其与 gateway、session、prompt 等模块的交互逻辑。
> 目的：后续修改或修 bug 时不遗漏既有逻辑约束。

---

## 一、核心功能清单

### 1. 消息接收

| 功能 | 关键代码位置 | 说明 |
|------|------------|------|
| WebSocket 反向连接（推荐） | `_run_reverse_server()` | OpenKitsune 作为 WS 服务端，NapCat/Lagrange 作为客户端连入 |
| WebSocket 正向连接 | `_receive_loop_with_reconnect()` | OpenKitsune 主动连接 OneBot 实现的 WS 服务器 |
| 消息类型解析 | `_parse_message()` | 支持 text/image/record/video/file/at/face |
| CQ 码解析 | `_parse_cq_code()` | 兼容字符串格式消息，含实体解码 (`&#44;`, `&#91;`, `&#93;`, `&amp;`) |
| @机器人 检测 | `_handle_message_event()` 内 at 段检查 | 匹配 `self_id` 或 `all` |
| 消息去重 | `_seen_message_ids` (OrderedDict LRU) | 容量 500，防止重复推送 |

### 2. 消息发送

| 功能 | 方法 | 群聊/私聊判断 |
|------|------|:---:|
| 文本/图片/语音 | `send_message()` | `metadata.is_group` |
| 文件上传 | `send_file()` | `is_group` 参数或默认群 |
| 语音上传 | `send_voice()` | `is_group` 参数或默认群 |
| 便捷文本 | `send_text()` (基类) | `metadata` 透传 |
| 消息撤回 | `delete_message()` | — |

**约束**：`send_message()` 通过 `OutgoingMessage.metadata.get("is_group")` 判断群/私聊类型，调用 `send_group_msg` 或 `send_private_msg` API。所有经 gateway 发送的消息（包括反馈、错误、自检报告）都必须传递 `metadata` 中的 `is_group` 字段。

### 3. 两种连接模式对比

| 维度 | 反向 WebSocket (reverse) | 正向 WebSocket (forward) |
|------|--------------------------|--------------------------|
| 默认 | ✅ 默认模式 | — |
| OpenKitsune 角色 | WS 服务端 (`websockets.serve`) | WS 客户端 (`websockets.connect`) |
| NapCat 配置 | 配置 Websocket 客户端 → `ws://<host>:<port>` | 配置 Websocket 服务器端口 |
| 认证 | `Authorization: Bearer <token>` 或 `?access_token=<token>` | `Authorization: Bearer <token>` |
| 连接管理 | 单连接替换（新连接替旧连接） | 自动重连（指数退避 1s~60s） |
| 适用场景 | NapCat 和 OpenKitsune 同机 / 内网 | OpenKitsune 无法被 NapCat 访问时 |
| 连接超时 | N/A（被动等待） | `open_timeout=10` |

### NapCat 配置示例（反向模式）

在 NapCat 设置中：
- **网络配置** → 添加 **Websocket 客户端**
- URL: `ws://127.0.0.1:6700`（默认端口）
- Token: 与 `ONEBOT_ACCESS_TOKEN` 一致（可选）

### 4. API 调用机制

| 机制 | 说明 |
|------|------|
| echo 回调 | 每次 API 调用生成 UUID echo，通过 `_api_callbacks` 字典等待响应 |
| 超时 | 30 秒超时，自动清理 callback |
| 连接断开时 | `_reject_pending_callbacks()` 拒绝所有等待中的 Future |
| Future 保护 | `set_result/set_exception` 均用 `try/except InvalidStateError` 保护 |

### 5. 媒体处理

| 功能 | 说明 |
|------|------|
| 下载 | `download_media()` 使用 httpx，含 `raise_for_status()` |
| 上传 | `upload_media()` 返回本地路径引用 |
| 本地缓存 | `data/media/onebot/` |

---

## 二、配置项

### 环境变量（全局模式）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ONEBOT_ENABLED` | `false` | 是否启用 OneBot 通道 |
| `ONEBOT_MODE` | `reverse` | 连接模式: `reverse` / `forward` |
| `ONEBOT_REVERSE_HOST` | `0.0.0.0` | 反向模式监听地址 |
| `ONEBOT_REVERSE_PORT` | `6700` | 反向模式监听端口 |
| `ONEBOT_WS_URL` | `ws://127.0.0.1:8080` | 正向模式 WS 地址 |
| `ONEBOT_ACCESS_TOKEN` | (空) | 访问令牌（两种模式通用） |

### 多 Bot 模式（API/前端）

多 Bot 配置下，OneBot 有两个 bot type：
- `onebot` — 正向 WS 模式，credentials: `ws_url`, `access_token`
- `onebot_reverse` — 反向 WS 模式，credentials: `reverse_host`, `reverse_port`, `access_token`

---

## 三、关键逻辑约束

1. **反向模式单连接**：同时只维护一个活跃 WS 连接。新客户端连入时关闭旧连接（4000 "replaced"），并拒绝旧连接上的待处理 API 回调。

2. **`_ws` 生命周期**：断连后 `_ws` 必须置 `None`。正向模式在 `_receive_loop_with_reconnect` 退出迭代时置 `None`；反向模式在 `_reverse_ws_handler` 的 `finally` 中判断 `self._ws is ws` 后置 `None`。

3. **chat_id 类型**：OneBot API 需要 `int` 型 ID，`send_message()` 将 `message.chat_id` 转为 `int`，转换失败时抛出 `ValueError`。

4. **群/私聊判断**：统一通过 `metadata.is_group` 字段，不再使用 try-except 回退机制。

5. **消息去重**：基于 `message_id` 的 OrderedDict LRU（容量 500），防止 OneBot 实现重复推送同一消息。

6. **CQ 码实体解码**：`&#44;` → `,`, `&#91;` → `[`, `&#93;` → `]`, `&amp;` → `&`。

7. **启动条件**：`main.py` 中只检查 `onebot_enabled`，不再要求 `ws_url` 非空（反向模式不需要）。

---

## 四、数据流

```
NapCat / Lagrange
        │
    ┌───┴───┐
    │reverse│  (NapCat → OpenKitsune WS Server)
    │forward│  (OpenKitsune WS Client → NapCat)
    └───┬───┘
        │ OneBot v11 JSON events
        ▼
  OneBotAdapter._handle_event()
        │
        ├─ echo in data → API 回调响应 (_api_callbacks)
        ├─ message → _handle_message_event() → UnifiedMessage → gateway
        ├─ notice → _emit_event()
        └─ request → _emit_event()
```

---

## 五、已知限制

1. **仅支持 OneBot v11**：不支持 v12 协议（v12 在实践中几乎没有实现支持）。
2. **文件上传**：OneBot v11 的 `upload_group_file` / `upload_private_file` 并非所有实现都支持。
3. **反向模式端口冲突**：如果指定端口被占用，`websockets.serve` 会抛出异常，需检查日志。
4. **Access Token 传递**：反向模式下检查请求头 `Authorization: Bearer <token>` 和查询参数 `?access_token=<token>` 两种方式。
5. **图片/文件 URL**：部分 OneBot 实现返回的媒体 URL 可能是临时的（有效期短），下载失败时需重试。

---

## 六、修改检查清单

修改 OneBot 通道时，务必检查：

- [ ] `onebot.py` — 适配器核心逻辑
- [ ] `config.py` — 配置字段 (`onebot_mode`, `onebot_reverse_*`)
- [ ] `main.py` — 启动条件、`_create_bot_adapter()`、`_CHANNEL_DEPS`
- [ ] `gateway.py` — `send_text` 调用是否传递 `metadata`（含 `is_group`）
- [ ] `wizard.py` — CLI 向导 `_configure_onebot()`
- [ ] `bridge.py` — 前端桥接验证逻辑
- [ ] `agents.py` — `VALID_BOT_TYPES`
- [ ] `IMConfigView.tsx` — 环境配置 UI（模式切换）
- [ ] `IMView.tsx` — 多 Bot 配置 UI（`BOT_TYPES`, `CREDENTIAL_FIELDS`）
- [ ] `App.tsx` — env keys 列表、状态页、onboarding
- [ ] `zh.json` / `en.json` — 翻译
- [ ] `.env.example` / `deploy.sh` / `deploy.ps1` — 环境变量模板
- [ ] `test_im_adapters.py` — 适配器测试
