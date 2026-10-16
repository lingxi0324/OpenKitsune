# 启动顺序与聊天就绪

桌面启动以聊天可用为完成条件。IM 连接、MCP 自动连接和可选能力预热继续在后台执行，不再延迟聊天就绪。

## 启动路径

1. 导入轻量 CLI 入口，启动 HTTP API。
2. 构造并初始化 Agent：身份、技能元数据、MCP 配置目录、插件注册与安全策略、提示词等。
3. 初始化会话管理、Agent Pool 和 Orchestrator，发布聊天就绪状态。
4. 后台启动 IM、MCP 自动连接、向量库与表情包预热；运行环境版本报告也在后台线程执行。

插件工具注册和安全策略仍在聊天就绪之前完成，避免首条消息拿到不完整的工具目录或安全分类。
`Agent.initialize(defer_optional=True)` 允许宿主在核心服务绑定后调用 `start_background_services()`；普通调用会自动安排后台预热。轻量子 Agent 不重复启动这些任务。

## 状态契约

`GET /api/health` 返回 HTTP 200 仅表示 API 可访问。

| 字段 | 含义 |
| --- | --- |
| `readiness.http_ready` | HTTP 已监听 |
| `readiness.agent_ready` | Agent 必需初始化已完成 |
| `readiness.core_ready` | 会话与核心服务已绑定 |
| `readiness.chat_ready` | 桌面聊天可用 |
| `readiness.ready` | 与 `chat_ready` 相同，供旧客户端使用 |
| `readiness.im_ready` | IM 启动结束且未报告适配器启动失败 |
| `readiness.im_status` | IM 启动阶段：`starting`、`ready`、`degraded` 或 `error` |

聊天就绪时 `phase` 变为 `running`，心跳的 `ready` 同步设为 true。前端优先使用 `chat_ready`，连接旧后端时回退到 `ready`。没有配置 IM 时，空网关正常启动也视为 IM 启动完成。

IM 状态是启动结果快照；后续各通道的在线状态以通道接口与事件为准。运维使用的 `/api/readyz` 保留原有子系统探针语义。

普通启动仅检查 IM SDK 能否定位，不运行 pip，也不通过完整导入来检查大型 SDK。缺少依赖时，用户通过设置中的通道启用或修复流程安装。飞书 SDK 的实际导入移到线程中执行。

退出时先取消并回收后台启动协程，再关闭网关和 Agent；已取消的启动任务不会发布就绪状态。MCP 连接和表情包初始化分别加锁，避免预热与首次请求重复初始化。线程内已经开始的 SDK 导入无法由 asyncio 强制终止。

## 技能索引缓存

每次 `SkillLoader.load_all(base_path)` 读取一次 `base_path/data/cache/skill-metadata.json`，只保存版本化的元数据，正文仍按需读取。

缓存键包括源文件的绝对路径、纳秒级 mtime/ctime 与文件大小。文件签名变化、技能安装/卸载或显式热重载会使缓存失效；分类、启用列表和工具安全策略仍走原有流程。缓存损坏、不可写或版本不匹配时回退到源文件解析。目录仍会扫描，因此新增或删除技能不会被旧索引隐藏。

CLI Anything 技能发现先按安装目录名筛选，再读取匹配包的元数据，避免遍历所有已安装包的 METADATA。

## 验证与测量

相关回归测试包括 `tests/unit/test_background_startup.py`、`tests/unit/test_skill_metadata_disk_cache.py` 和前端的 `backendReadiness.test.ts`，覆盖 IM 尚未完成/失败时聊天仍可用、启动中退出、连接并发、跨进程缓存和旧后端兼容。

2026-09-14 在本机 Python 3.12 环境中，以修改前 HEAD 与修改后代码分别运行独立子进程：

| 隔离测量 | 修改前 | 修改后 |
| --- | --- | --- |
| CLI 入口导入，三次中位数 | 1.883 秒 | 0.406 秒 |
| 扫描相同 154 个项目技能，第二/三次均值 | 0.341 秒 | 0.216 秒 |

技能扫描使用同一目录、隔离工作区，并跳过运行时注册记录写入；修改后第二次开始命中磁盘缓存。入口导入已禁用日志配置；这些数据不包括完整服务启动、IM 登录、模型调用，也不是操作系统冷缓存测量。

真实启动日志分别输出 `Desktop chat ready in ...` 与 `IM startup finished in ...`，两个耗时均从进入 serve 协程开始计时，可用于后续验证实际配置下的收益。
