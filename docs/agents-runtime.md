# Agents Runtime — E:\agents 三项目运行时映射

> 2026-10-22 建立。描述 **灵汐（OpenKitsune 主仓库，D:\ai\OpenKitsune-main）宿主
> 与 E:\agents 下三个 openkitsune 相关项目** 的调用路径、接口与调用工具，
> 作为端口/启动口径的单一参考（与各项目 config\ports.yaml 事实源一致）。

## 1. 三个项目一览

| 项目 | 路径 | 角色 | 二进制/解释器 | 本机启动入口 |
|---|---|---|---|---|
| openkitsune-heart | `E:\agents\openkitsune-heart` | 推理内核（心·九尾，model-manager 统一网关） | `target\release\model-manager.exe` | `openkitsune-heart-start.bat`（Agent Stack 主编排） |
| openkitsune-brain | `E:\agents\openkitsune-brain` | 记忆系统（fusion-memory + brain-bus） | `target\release\fusion-memory.exe`；Python `services\brain-bus\server.py` | `start-menu.bat` |
| openkitsune-hands | `E:\agents\openkitsune-hands` | 网络爪牙（九尾搜索/抓取，含本机 SearXNG） | `target\release\kitsune-hands.exe`（未构建时回退 `target\debug`） | `start-hands.bat`（新增） |

## 2. 端口与健康端点（本机部署口径）

| 服务 | 端口 | 健康端点 | 启动方 |
|---|---|---|---|
| heart · model-manager（心门网关） | 8240 | `GET /api/admin/health`（另有 `/health`） | heart 引擎（`scripts\start-heart.ps1`） |
| heart · mcp-gateway（-Aux） | 8360 | — | heart 引擎（`-Aux`） |
| heart · embedding 灵桥 | 8120 | — | model-manager 内化 |
| brain · fusion-memory | **4014**（避开上游 Kitsune 4010） | `GET /health` | brain 菜单 / okmem_stack |
| brain · brain-bus（神经中枢） | 8641 | `GET /api/memory/health`（真查 SQLite） | brain 菜单 / okmem_stack |
| hands · kitsune-hands | 8320 | `GET /health` | hands 引擎 / 宿主 hands_stack |
| hands · SearXNG | 55510 | `GET /healthz`（SearXNG 无 `/health`） | hands 引擎（venv，`searxng\settings.yml`） |

> 注意：fusion-memory 上游默认 4010；本机三处口径（brain `start-menu.ps1` 默认、
> `start-memory-stack.ps1`、宿主 `okmem_stack.py`）统一为 **4014**，`ports.yaml`
> 已同步。heart 侧的 8240 同时暴露 `/health` 与 `/api/admin/health`。

## 3. 调用工具与接口契约（宿主 → 各项目）

| 宿主调用方 | 调用对象 | 接口 | 载荷 |
|---|---|---|---|
| `src/openkitsune/tools/web_search/providers/hands.py` | hands | `POST {8320}/api/search/web` | camelCase：`{query, maxResults, safeSearch, language?}`，header `X-Project-ID` |
| `src/openkitsune/tools/web_search/providers/hands.py` | hands | `POST {8320}/api/search/fetch` | URL 抓取 |
| `src/openkitsune/tools/web_search/hands_stack.py` | hands | 启动子进程 | `NX_CONFIG=<home>\config.yaml`、`NX_BIND=127.0.0.1:8320`；binary release→debug；`GET /health` |
| `src/openkitsune/memory/okmem_stack.py` | brain | 启动子进程 | `fusion-memory --root <home> --port 4014 --data-dir data/fusion-memory serve --no-watch`；`brain-bus server.py` 环境变量 `NEURAL_BUS_PORT=8641` 等 |
| `src/openkitsune/memory/semantics.py` 等 | fusion | `4014 /memory/*` | 三速记忆语义方法族 |
| `data/llm_endpoints.json` | heart | `{8240}/v1`（OpenAI 兼容） | chat/embeddings 等 |
| heart `config.yaml` `neural_hub.url` | brain | `{8641}` | shadow 模式快脑判定 |

## 4. Agent Stack 主编排（新增）

- 入口：`E:\agents\openkitsune-heart\openkitsune-heart-start.bat`
- 引擎：`E:\agents\openkitsune-heart\scripts\start-agents.ps1`（只做编排，动作委派各项目引擎）
- 用法：`start` / `stop` / `status` / `restart` / `logs`；无参进交互菜单
- 启动顺序（依赖方向）：brain → heart(-Aux) → hands(+SearXNG)；停止反向
- 防误杀：8240 被其他实例占用只警告跳过（`-Force` 才接管）；停止按 PID 文件 + 命令行匹配项目根路径

## 5. 本次同步记录（2026-10-22）

检查结果与修正：

1. **调用路径/接口核对**：宿主 `hands_stack.py`、`hands.py`、`okmem_stack.py` 与三项目实现一致
   （payload camelCase、`/health`、`NX_CONFIG/NX_BIND`、binary 回退链、fusion 4014/brain-bus 8641）。
2. **修正过时端口口径**：
   - `E:\agents\openkitsune-heart\config\config.yaml` 注释 4010 → 4014
   - `E:\agents\openkitsune-heart\config\ports.yaml` 外部依赖注释 4010 → 4014
   - `E:\agents\openkitsune-brain\config\ports.yaml` `fusion-memory: 4010` → `4014`（单一事实源对齐）
3. **修正过时启动提示**：`start.ps1` 中 `E:\models\Kitsune\scripts\start_services.ps1` → 新主编排入口。
4. **新增 hands 本机启动器**：`E:\agents\openkitsune-hands\start-hands.bat` + `scripts\start-hands.ps1`
   （此前 hands 仅由宿主伴随启动，无独立生命周期脚本）。
5. **SearXNG 健康探针**：使用 `/healthz`（SearXNG 无 `/health` 路由）。

验证：master `start` 幂等跑通（brain/heart/hands 端口占用即复用，SearXNG 拉起后 `/healthz` 200），
全栈 8240/4014/8641/8320/55510 健康；两个 bat 薄壳与 ps1 引擎语法校验通过。
