# 记忆系统 v4 升级与回滚指南

> 适用版本：v1.27.10 → v1.28（含 schema 升级）
>
> 影响面：所有桌面端、CLI、API、IM 用户。第一次启动会触发一次性 schema 迁移和 `memories.json` 归档。

---

## 1. 你为什么会看到这份文档

如果你从 v1.27 之前升级上来，可能遇到过以下三类问题之一：

1. **"Legacy / 旧版记忆"提示反复弹出**，即使你已经"导入"过一次；
2. **越聊越慢**：上下文一长，每轮响应明显比刚启动时拖；
3. **记忆数据在 `memories.json` 和 SQLite 之间打架**：你删过的条目又冒出来，或者你新加的没存住。

v4 这一轮升级把这三件事的根因一次性收拾掉了。

---

## 2. 这次升级做了什么（按用户角度）

### 2.1 banner 不再反复骚扰

| 旧行为 | 新行为 |
|---|---|
| 后台合成记忆会被错误塞回 `legacy_quarantine`，导致"待整理"计数永远清不空 | 后台合成产物落到独立的 `pending_consolidation` 桶，**用户不可见、不触发 banner** |
| 没有"不再提醒"选项，每次启动都要点掉 | UI 提供三个选项：**整理导入** / **稍后提醒**（本会话） / **不再提醒**（永久） |
| 导入成功后如果未来又出现新 legacy，banner 不再亮 | "永久不再提醒"会在你下次主动 claim-legacy 成功后被自动重置 |

后端 API 增加了 `show_banner`、`banner_dismissed`、`api_version` 字段。前端只信 `show_banner`，banner 决策完全收敛到后端。

### 2.2 旧 `memories.json` 自动归档

- v4 首次启动会做一次 backfill：把 `memories.json` 里的数据塞进 SQLite（含 `_LEGACY_JSON_BACKFILL_SENTINEL` 守卫，绝不重复执行）；
- backfill 完成后 `memories.json` 自动改名为 `memories.json.archived.<timestamp>`；
- 此后 `_save_memories()` 是 no-op，SQLite 成为唯一真相源；
- 如果你担心 backfill 出错，**归档文件原样保留**，可以手动改回 `memories.json` 触发回滚（见 §5）。

### 2.3 多用户 / 多 workspace 隔离闭环

- `_GlobalStoreSource` 严格按 `(user_id, workspace_id)` 过滤，禁止跨用户回流；
- placeholder 身份（`anonymous` / `legacy` / `system`）不能从 global store 取记忆；
- 新增 `session_tenants` 表，把 `session_id` 显式映射到 `(user_id, workspace_id)`；
- v3 → v4 升级时会扫描 `conversation_turns` 自动回填该表，老会话不丢归属；
- 新增 API：`POST /api/memories/migrate-workspace`，可以把当前用户在 workspace A 的记忆迁到 workspace B，事务保护 + 审计日志。

### 2.4 性能优化（Phase 5）

| 优化点 | 收益 |
|---|---|
| 默认使用 compact Memory Guide | 每轮 prompt 节省 ~600 token |
| 短 chitchat（"ok"/"嗯"/"继续"/≤4 字符）跳过 Layer 4 多路语义召回 | 短消息响应延迟显著下降；identity slot 不受影响 |
| MEMORY.md 进程级 mtime 缓存 | 同一文件不再每轮重读 + truncate；LLM prompt 缓存命中率更稳定 |

性能开关：

- `OPENKITSUNE_PROMPT_VERBOSE_MEMORY_GUIDE=1` —— 强制使用完整版 Memory Guide（旧行为，约 815 token）。一般只用于调试 / 评估。

---

## 3. Schema 变更清单（v3 → v4）

`MemoryStorage._SCHEMA_VERSION = 4`。升级时会按下表执行：

| 动作 | 落点 |
|---|---|
| `legacy_quarantine` 中 `source IN ('daily_consolidation', 'experience_synthesis')` 的记忆 → 迁到 `pending_consolidation` | `memories` 表 |
| 真历史 v1/v2 旧数据继续留在 `legacy_quarantine` | `memories` 表 |
| 每条迁移产生一条 `pre_scope → new_scope` 记录 | 新表 `_memory_scope_audit` |
| 从 `conversation_turns` 反推 `session_id → (user_id, workspace_id)`，回填到 `session_tenants` | 新表 `session_tenants` |
| `legacy_json_backfill_done` sentinel | 沿用 `_schema_meta` |
| `legacy_banner_dismissed` sentinel | 沿用 `_schema_meta` |

### 自动备份

升级前会把 `openkitsune.db` 复制到 `openkitsune.db.bak.v3_to_v4.<timestamp>`（如果是从 v2 升上来则名字带 `v2_to_v4`）。SQLite 文件级别的回滚直接覆盖回来即可。

---

## 4. API 变更

### 4.1 GET `/api/memories/migration-status`

新增字段：

```json
{
  "api_version": "v4",
  "show_banner": true,
  "banner_dismissed": false,
  "pending_consolidation": 0,
  // ... 原有字段保持兼容
  "has_recoverable_legacy": true,
  "legacy_pending": 3,
  "legacy_reviewed": 0,
  "legacy_quarantine": 3,
  "current_visible": 12
}
```

老前端（不感知 `show_banner`）会自动回退到看 `has_recoverable_legacy`，行为与 v3 一致。

### 4.2 POST `/api/memories/legacy/dismiss`

新端点。把 `_schema_meta.legacy_banner_dismissed` 置为 `"1"`，幂等。下次 `migration-status` 会返回 `show_banner=false`，直到：

- 用户成功调用 `POST /api/memories/claim-legacy`（自动清除 sentinel），或
- 你手动把 `_schema_meta.legacy_banner_dismissed` 删掉。

### 4.3 POST `/api/memories/migrate-workspace`

请求体：

```json
{
  "from_workspace_id": "default",
  "to_workspace_id": "proj-7a1c98ab2e44",
  "scope": "user"
}
```

行为：

- 只动当前请求会话身份所属 `user_id` 的记忆，绝不跨用户搬运；
- 默认 `scope='user'`，不动 `legacy_quarantine` / `pending_consolidation` / `session` 桶；
- 事务保护，失败 ROLLBACK；
- 每条迁徙记录写入 `_memory_scope_audit` 表，可追溯。

---

## 5. 回滚预案

### 5.1 仅回滚 banner / 文案变化（最轻）

- 把 `apps/setup-center/dist-web` 替换为旧版打包；
- 后端兼容老前端，老前端只看 `has_recoverable_legacy`，行为与 v3 一致。

### 5.2 回滚 prompt 性能优化

- 设置环境变量 `OPENKITSUNE_PROMPT_VERBOSE_MEMORY_GUIDE=1`，恢复完整版 Memory Guide；
- 短消息跳过召回的逻辑没有 env 开关，**如果必须关掉**，请反向 cherry-pick `perf(prompt): Phase 5` 那个 commit。

### 5.3 回滚 schema（最重）

适用场景：怀疑 v4 迁移把数据搞坏。

```bash
# 1. 停掉所有 openkitsune 进程（后端 / 桌面 / IM）
# 2. 找到 v3 → v4 升级时自动备份的 db
ls ~/.openkitsune/openkitsune.db.bak.v3_to_v4.*

# 3. 把当前 db 重命名留底，备份覆盖回去
mv ~/.openkitsune/openkitsune.db ~/.openkitsune/openkitsune.db.v4-broken
cp ~/.openkitsune/openkitsune.db.bak.v3_to_v4.<timestamp> ~/.openkitsune/openkitsune.db

# 4. 启动旧版（v1.27.x）二进制 / wheel
```

注意：

- 如果你已经在 v4 下产生了新对话，**这些对话会丢失**（v3 不识别 v4 新增字段）。回滚前请先 `openkitsune memory export` 或手动复制 `memories.json.archived.*` 留底。
- v4 把 `memories.json` 改名了。回滚到 v3 前请把 `memories.json.archived.<timestamp>` 改回 `memories.json`，否则 v3 会以为是首次启动。

### 5.4 我只想恢复一次"导入旧记忆"的提示

```bash
# 在 OPENKITSUNE_DB（默认 ~/.openkitsune/openkitsune.db）执行：
sqlite3 ~/.openkitsune/openkitsune.db \
  "UPDATE _schema_meta SET value='0' WHERE key='legacy_banner_dismissed';"
```

下次 `migration-status` 会再次返回 `show_banner=true`（前提是确实还有 `legacy_pending > 0`）。

---

## 6. 升级前自查清单

- [ ] 备份 `~/.openkitsune/openkitsune.db`（最稳妥）；
- [ ] 留意启动日志里这两行：
  - `[MemoryStorage] v3→v4 split: moved %d rows ...`
  - `[MemoryStorage] v3→v4 backfill: registered %d session_tenants entries`
- [ ] 如果你跑过自定义脚本直接读 `memories.json`，请改成读 SQLite 或 API；
- [ ] 如果你的 IM 部署有多个 workspace 共用一个 db，启动后检查 `GET /api/memories/migration-status` 的 `semantic.by_owner` 字段，确认每个 user/workspace 行数正常；
- [ ] 大规模部署建议先在测试环境跑一遍，再灰度。

---

## 7. Phase 2b / 3 收尾（v1.28 范围内已完成）

下面这些项原本规划在"下一个 minor 推进"，最终在 v4 升级一并落地，因为它们触及的是多用户 IM 部署的真实数据隔离漏洞，没必要拖到下个版本。

### 7.1 episode / turn 工具搜索按 (user_id, workspace_id) 过滤（Phase 2b.5）

- `storage.search_episodes` 增加 `user_id` / `workspace_id` 参数，通过 INNER JOIN `session_tenants` 限定结果；
- `storage.search_turns` 同上；
- `tools/handlers/memory.py`：`list_recent_tasks` / `search_conversation_traces` 自动带上 `mm._current_owner()` 的 (user, workspace)；
- 修复点：多用户 IM 部署下，alice 的 `list_recent_tasks` 之前会看到 bob 的任务列表 —— 是真泄漏，已堵。

### 7.2 daily_consolidator dedup 按 tenant 分组（Phase 3）

- 同 query content 但属于不同 (user_id, workspace_id) 的记忆**不会**再被跨用户合并；
- 向量库回包后增加两道兜底：1) 隔离桶（`legacy_quarantine` / `pending_consolidation`）不参与；2) 跨 tenant 命中即便相似度高也跳过。

### 7.3 persona_trait 加载排除隔离桶（Phase 3）

- `agent._initialize_async` 加载 `persona_trait` 时换用 `iter_cached()`，自动排除隔离桶；
- 解决"用户没碰过的旧 persona trait 突然变成新 Agent 的人格特征"问题。

### 7.4 `memory_mode → memory_isolation` 后向兼容重命名（Phase 2b.2）

- `AgentProfile` 新增 `memory_isolation` 属性别名（推荐新代码使用），底层字段仍为 `memory_mode`，JSON 持久化格式不变；
- `to_dict` 双 key 输出，`from_dict` 双向接收（新名优先）；
- API `ProfileCreateRequest` / `ProfileUpdateRequest` 接受新名，`create` 路径优先用新名；
- `create_agent` 工具 schema 新增 `memory_isolation` 入参，旧 `memory_mode` 仍兼容（schema 中标注 deprecated）；
- v1.30 计划把 `memory_mode` 打 `@deprecated`，更晚版本下线。

### 7.5 isolated agent 首次启动 seed MEMORY.md（Phase 2b.3）

- 旧实现：找不到 profile 自己的 `MEMORY.md` 时回退到全局 `settings.memory_path`，会把 isolated agent 的数据**覆写**到全局，破坏隔离语义；
- 新实现：永远使用 `{profile_dir}/identity/MEMORY.md`，不存在时自动写入带注释头的空模板，保护用户数据（已有内容不会被 seed 覆盖）。

---

## 8. 已知边界 / 后续计划

- `multi_agent_enabled` 已经默认为 `True`，**没有**开关可以关掉（参考 `AGENTS.md`）；
- `memory_mode` 字段名会在 v1.30 标 deprecated，建议前端 / 第三方集成早点切到 `memory_isolation`；
- `daily_consolidator.refresh_memory_md` / `_promote_persona_memories` 仍然假设进程内只有"当前活跃 tenant"在写 MEMORY.md / persona —— 多用户 IM 部署如果需要每个 tenant 独立 MEMORY.md，要等 Agent Profile-per-IM-user 的更深层改造（不在 v4 范围内）。

### 8.1 仍未完全收敛的边界（已知 + 监控中）

| 项 | 影响面 | 当前缓解 | 下一步 |
|---|---|---|---|
| HTTP `GET /api/memories/{id}` / `PUT /api/memories/{id}` 不做 owner 校验 | 桌面 admin UI / 本地管理面板 | API 默认只 bind localhost，desktop 单用户场景无泄漏面；多用户后台部署应放在内网 + 反代鉴权后 | v1.29 在 HTTP 路由层加 owner check |
| 升级前已有的 episode 但其 `session_id` 在 `conversation_turns` 里没记录 | v3 → v4 升级且有过 turn 清理脚本的部署 | `session_tenants` 反推不到这些孤儿 episode，被 `search_episodes` JOIN 自然过滤；数据本身不丢，只是工具看不到 | 后续做 `claim-orphan-episodes` 工具补登记 |
| `AgentProfile(memory_isolation="isolated")` 直接 kwarg 构造抛 `TypeError` | 直接构造 dataclass 的第三方扩展代码 | `from_dict` / API / 工具入参均接受新名，**生产代码应该走这三条之一** | v1.30 把字段重命名 + 删 alias |
| 多用户 IM 共享 `data/react_traces/` 和 `data/memory/conversation_history/` 时，文件按 session_id 命名 | 多用户 IM 共享同一 OPENKITSUNE_DATA_DIR 部署 | Phase 2b.5 二次审计已加 `iter_owned_session_ids` allow-set 过滤，stem 不在 owner 已登记 session 列表内的文件直接跳过 | 已堵；后续做按 user_id 分目录归档作为深度防御 |

### 8.2 v4.1 缓存一致性重构（Path A，已落地）

**背景：** 用户报告"删除记忆失败"的 bug —— `MemoryManager.delete_memory(id)` 只在 `_memories` 缓存里命中时才走 DB 删除，
对于 lifecycle 后台合成、API POST 直写等"绕开 manager"的写入路径，缓存里没有这条记录 → 删除直接返回 `False`，
DB 里的行被静默漏删。深挖发现这不只是一个 bug，而是 v4 把 SQLite 当 source-of-truth 后，`_memories` 缓存的写入、读取、
失效路径仍然散落在 manager / lifecycle / API / 各种 review 流程里，**没有人是"唯一的 cache owner"**。

**修法（Path A）：** 在 `UnifiedStore` 上加一个 observer pattern：

```
UnifiedStore.save_semantic()    ─┐
UnifiedStore.update_semantic()  ─┼──→ self._fire(kind, payload)  ──→ MemoryManager._on_store_event()
UnifiedStore.delete_semantic()  ─┤                                          │
UnifiedStore.cleanup_expired()  ─┘                                          ▼
                                                            self._memories[id] = mem  / pop(id)
```

- `UnifiedStore` 是 DB-mutation 的唯一事件源；每个成功提交后同步触发 observer；
- `MemoryManager` 在 `__init__` 里 `self.store.register_observer(self._on_store_event)`，
  observer 内部独立加锁，幂等，异常被吞掉不影响写入；
- `MemoryManager.delete_memory` 重写成 thin wrapper：直接 `store.delete_semantic`，observer 自动清缓存；
  保留了对 cache-only 残影的 self-heal 兜底；
- HTTP `DELETE /api/memories/{id}` 改为优先走 `MemoryManager.delete_memory`，保证 vector store / 插件 backend 一并触达；
- 单条 create / update / delete 的 `_sync_json(request)` 全部下线（observer 已经做了增量同步，O(N) full reload 是浪费）；
- 仅保留 `claim-legacy` 和 LLM review 完成后的 `_sync_json` 作为**多步骤批量写**后的防御性兜底。

**保留的已知 debt（不在 Path A 范围内）：**

- `MemoryManager.add_memory` v1 兼容路径在 `_memories_lock` 内做 in-flight 去重检查，
  会在 `store.save_semantic` 调用**前**先写一遍 `_memories[id] = memory`（pre-commit），
  observer 之后再 idempotent 覆盖一次。
  代价是如果 DB 写失败，缓存里会有一条短暂的 ghost（下次 `_reload_from_sqlite` 修复）。
  保留是因为去掉它会让两个并发 `add_memory(near-duplicate)` 走到去重门外，需要更大重写。
- `vector_store.add_memory` 在 `add_memory` 中是直调，不经 `UnifiedStore`。
  这块仍是 manager 自己负责的副效应，没有纳入 observer。
- `_memories` 仍是"全量 cache"语义：进程启动时 `_load_from_sqlite()` 一次性灌满。
  对于超大库（>百万记忆）这是内存问题，但 v4 范围内的优化（lazy/LRU 化缓存）属于 v1.29 议程。
- `UnifiedStore.bump_access` 和 `get_semantic` 内部用 `self.db.update_memory(...)` 给
  `access_count` / `last_accessed_at` 做计数自增，**不触发 observer**：这是热路径，每次检索都跑，
  缓存里的 access_count 因此会和 DB 略有偏差。但所有依赖 access_count 做评分的代码都走
  `store.search_semantic` 直读 DB，不读 cache.access_count，所以这点偏差不影响功能。
- **`MemoryStorage.get_memory` 没有持 `_lock`**（pre-existing bug，不是 Path A 引入）：
  和 `save_memory` / `update_memory` 并发会偶发 SQLite "bad parameter or other API misuse"。
  实际链路里 manager 的写操作经 `_memories_lock` 串行化、`UnifiedStore` 的 dedup 检查也基本单线程，
  桌面 / 单进程场景命中概率极低；多线程高并发写入（比如未来的 IM 群批量入库）会暴露这点。
  v1.29 应该在 `MemoryStorage.get_memory` / `get_*` 上加读锁或换 connection pool。

**v1.29 候选 — Path B（消除缓存）：** 让 `_memories` 退化成 LRU 或者直接干掉，所有读取都走 SQLite + FTS5/向量索引。
这条路一致性最干净（无 cache 就无 desync），代价是改动面更大（`iter_cached` / persona 加载 / dedup 检查全要重新写），
需要先评估 SQLite 直查的 P99 延迟是否能撑住默认 retrieval 路径。Path A 已经把"class of cache-desync bugs"按掉，
Path B 是优化项，不是修 bug。

**回归覆盖：** `tests/unit/test_memory_v4_migration_and_isolation.py` 末尾新增 7 个 observer / cache-coherence 测例，
包括 observer 异常隔离、dedup 短路不重复触发、外部直写自动入缓存、外部直删自动出缓存、用户报告的 ghost-row 删除等场景。

如果你在升级过程中遇到异常，请走 `openkitsune bugreport` 收集崩溃信息后提交 issue。
