# OpenKitsune 记忆清理与 openakita-main 记忆迁徙融合方案

> 制定时间：2026-10-15
> 目标：清理 OpenKitsune 现有记忆；将 openakita-main 的记忆数据与记忆保存/检索逻辑**真正迁徙融合**（非引用）进当前记忆系统。

---

## 一、探查结论（已完成）

### 1.1 当前系统（OpenKitsune，`C:\Users\Administrator\.OpenKitsune\OpenKitsune`）
| 项目 | 现状 |
|---|---|
| 记忆逻辑 | `src/openkitsune/memory/`：基础版 29 个 py 文件（UnifiedStore / RetrievalEngine / LifecycleManager / MemoryExtractor / relational 图引擎），含 v4 owner 隔离改进（owner_migration.py、session_identity.py） |
| 记忆数据 | `data/memory/openkitsune.db`（schema v6，memories 仅 **232 条**，多为 10 月开发任务类记忆；conversation_turns 243、episodes 54、mdrm_nodes 8744） |
| 会话文件 | `data/memory/conversation_history/` 41 个测试会话 jsonl |
| 空壳库 | `data/memory/openakita.db`（4KB，几乎无数据） |

### 1.2 源项目（openakita-main，`I:\ai\openakita-main`）
| 项目 | 现状 |
|---|---|
| 记忆逻辑 A | `src/openakita/memory/`：与当前 openkitsune 同源（少量差异） |
| 记忆逻辑 B | `src/leiwa/memory/`：**高级完整版**，多 28 个独有文件（faiss_index 向量检索、fuzzy_search、orchestrator、scheduler、progressive、weekly_compressor、working_memory、time_index、heart_note、domain_tagger、sleep_manager、threat_patterns 等）+ 21 个共有文件的增强版（retention/types/retrieval/storage/search_backends 等大幅升级） |
| 记忆数据 | `data/memory/leiwa.db`（schema v6，memories **6535 条**真实记忆：session_extraction 3061、memory_nudge 2153、manual 569、retrospect 317、推演 39 等；conversation_turns 3486、episodes 1639、mdrm_nodes 14597、mdrm_edges 40464） |
| 原始对话 | `data/memory/conversations/` 605 个 jsonl（约 **1.1GB**，2026-05 ~ 07 真实对话） |
| 其他 | `conversation_history/` 84 文件、`daily_summaries/` 6 文件、`everlasting/beads_chain.json`、`memories.json` |

### 1.3 fusion-memory 服务（不属本次迁徙对象）
- 独立 Rust 服务（`E:\models\llama-cpp-server\bin\fusion-memory.exe`），运行于 127.0.0.1:4010
- 数据：`E:\models\llama-cpp-server\data\fusion-memory\`（玄医融合知识库 xuan-yi、memory、knowledge、profiles、qmd）
- 当前项目源码**无** fusion-memory/4010 引用 → 两者相互独立，本次不动它

### 1.4 版本关系
```
openakita-main/src/openakita/memory  （基础版）
   ├──演进→ 当前 openkitsune/memory   （基础版 + v4/v6 owner 隔离改进）
   └──演进→ leiwa/memory             （高级版：多 28 文件 + 21 文件增强）
```
- 两边 schema 均为 v6，表结构高度一致；源 memories 多 `category_path/schema_name/status` 3 列，episodes 列有差异（源含 scope 系列列，当前含 compaction 系列列）
- 源 FTS 为独立内容表（`memories_fts` 无 content=），当前为外部内容表 → **不能直接拷库文件，需行级迁徙 + 重建索引**

---

## 二、用户已确认的决策（interaction.ask 结果）

| 决策点 | 选择 |
|---|---|
| 清理范围 | **全部清空重建**：清空 memories 表、测试会话、快照文件等全部记忆痕迹，迁徙后从源库重建 |
| 数据迁徙范围 | **记忆库 + 原始对话**：leiwa.db 全部核心记忆表 + conversations 605 个原始对话 jsonl（1.1GB） |
| 逻辑融合范围 | **全部融合**：28 个独有逻辑文件全部融入当前 `src/openkitsune/memory` |
| 源库处置 | **保留原样**：openakita-main 原样保留作为历史备份，不依赖源路径 |

---

## 三、执行步骤

### 阶段 0：安全前置（必须）
1. **备份**当前 `data/memory/` 整个目录 → `data/memory_backup_pre_migration_<ts>/`（含 openkitsune.db、快照、conversation_history 等，保证可回滚）
2. 备份源库 `leiwa.db` → 生成只读副本 `leiwa_migration_source.db`（迁徙全程只读源，绝不修改）
3. **处理运行中的服务**：检测到两个 `openkitsune serve` 进程（PID 22340/25132）→ 需与用户确认停止，避免数据库被锁/写入冲突

### 阶段 1：清理 OpenKitsune 记忆
1. 清空 `openkitsune.db` 全部记忆业务表数据：`memories / conversation_turns / episodes / mdrm_nodes / mdrm_edges / mdrm_entity_index / mdrm_entity_aliases / mdrm_reachable / session_tenants / context_epochs / extraction_queue / attachments / scratchpad / tool_output_blobs / _memory_scope_audit`（保留 schema）
2. 重建 FTS 索引（memories_fts / mdrm_nodes_fts / attachments_fts）→ 清空后立即重建为空索引
3. 删除 `conversation_history/` 全部测试会话 jsonl
4. 归档/移除空壳 `openakita.db`

### 阶段 2：迁徙记忆数据（leiwa.db → openkitsune.db）
编写 `migrate_memory_data.py`，行级迁徙 + 列映射 + FTS 重建：
| 源表 | 目标表 | 处理 |
|---|---|---|
| memories（6535） | memories | 按列名映射；源 3 额外列（category_path/schema_name/status）在目标库 ALTER TABLE 补列后保留 |
| conversation_turns（3486） | conversation_turns | 列映射（含 metadata 差异） |
| episodes（1639） | episodes | 列映射：源 scope/scope_owner/user_id/workspace_id → 目标已有列；compaction 列留默认 |
| mdrm_nodes（14597） | mdrm_nodes | 直接映射（schema 一致） |
| mdrm_edges（40464） | mdrm_edges | 直接映射 |
| mdrm_entity_index（159） | mdrm_entity_index | 直接映射 |
| session_tenants | session_tenants | 从 conversation_turns 反推重建 |
| 附件/scratchpad 等 | 对应表 | 有则迁，无则略 |
- 迁徙后**重建全部 FTS 索引**（memories_fts、mdrm_nodes_fts、episodes_fts 等，按目标库 v6 外部内容表结构）
- 迁徙事务化：单连接 + 显式事务，失败整体回滚；逐表统计行数校验

### 阶段 3：迁徙原始对话文件
1. `conversations/` 605 个 jsonl（1.1GB）→ `data/memory/conversations/`
2. `conversation_history/` 84 个 jsonl → `data/memory/conversation_history/`
3. `daily_summaries/` 6 个 json → `data/memory/daily_summaries/`
4. `everlasting/beads_chain.json` → `data/memory/everlasting/`
5. `memories.json`（已由 v4 backfill 归档）→ 复制为参考存档

### 阶段 4：融合记忆保存/检索逻辑（leiwa/memory → openkitsune/memory）
1. **复制 28 个独有文件**到 `src/openkitsune/memory/`：
   builtin_provider / context_scrubber / daily_memory_exporter / domain_tagger / faiss_index / fuzzy_search / go_memory_bridge / heart_note / heart_note_ext / kw_index / memori_provider / memory_manager / memory_provider / memory_retrieval_config / metadata_cache / migrate_domain_tags / noise_filter / orchestrator / permission_filter / progressive / retention_cron / scheduler / sleep_manager / threat_patterns / time_index / vec_integration / weekly_compressor / working_memory
2. **import 适配**（是迁徙不是引用 → 全部改为本地相对导入）：
   - `from leiwa.config import settings` → `from openkitsune.config import settings`（或模块内解析）
   - `from leiwa.memory.X import Y` → `from .X import Y`
   - 检查 `heart_note.py` / `heart_note_ext.py` 对 leiwa.config.settings 的字段依赖，映射到 openkitsune.config 对应字段
3. **共有文件取增强版**（以 leiwa 版为基础，保留 openkitsune v4 独有方法/字段）：
   - 全覆盖：retention.py（1KB→16KB 策略引擎）、types.py（v3 渐进结构）、retrieval.py、search_backends.py、storage.py、unified_store.py、vector_store.py、manager.py、lifecycle.py、extractor.py、daily_consolidator.py 等 21 文件
   - 手工合并：manager.py 保留 openkitsune 独有方法（`_relational_pending_nodes`、`_merge_*`、`contribute_to_compaction` 等），融入 leiwa 独有方法（`_fts_match`、`_extract_sync_fallback`、`batch_save_memory`、`on_turn_complete`、`get_everlasting_status` 等）
   - 保留当前独有：`owner_migration.py`、`session_identity.py`、`exceptions.py`（相同文件直接保留）
4. **更新 `__init__.py`**：导出新增能力（ProgressiveEngine、WorkingMemoryLayer、FaissIndex、KeywordIndex、TimeIndex、VecIntegration、MemoryProvider 等），保持向后兼容
5. **依赖处理**：faiss/jieba/llama_cpp/memori 均为运行期 try/except 可选导入，缺失优雅降级；当前 venv 已有 numpy、pyyaml、pydantic。融合后运行 `python -c "import openkitsune.memory"` 验证导入零错误
6. **relational 子模块**：leiwa 与当前版本几乎一致（SAME），保留当前即可

### 阶段 5：验证（验证 ≠ 声称）
1. **导入验证**：当前 venv 下 `import openkitsune.memory` 成功，`from openkitsune.memory import MemoryManager, ProgressiveEngine, WorkingMemoryLayer` 成功
2. **数据验证**：
   - memories 6535 条（按 source 分布核对）；conversation_turns 3486；episodes 1639；mdrm_nodes 14597；mdrm_edges 40464
   - FTS 查询命中：`SELECT count(*) FROM memories_fts WHERE memories_fts MATCH '玄医'` 等
   - conversations 文件 605 个、大小核对（≈1.1GB）
3. **功能验证**：用 openkitsune 内存模块实例化 MemoryManager 指向新库 → `search_memories("丹道")` 返回结果、`get_stats()` 行数正确
4. **回滚预案**：如验证失败，`data/memory_backup_pre_migration_<ts>/` 原样恢复 + 源码 git 回退（如适用）

### 阶段 6：交付
- 输出迁徙融合报告：清理清单、迁徙行数统计、逻辑融合文件清单、验证结果、遗留缺口（如 faiss 未装时向量检索降级）
- 交付物：更新后的记忆库 + 融合后的 memory 模块 + 报告文档

---

## 四、风险与对策
| 风险 | 对策 |
|---|---|
| 运行中服务占用数据库 | 阶段 0 先确认停止 serve 进程再动库；停前告知用户 |
| 列映射遗漏导致数据丢失 | 逐表 PRAGMA 对比列名，映射脚本中不匹配列显式列出并人工确认 |
| FTS 结构差异（外部 vs 独立内容表） | 不走文件拷贝，全部行级 INSERT + 目标库重建 FTS |
| import 断裂（leiwa.config 等） | 融合后立即 `python -c import` 冒烟测试 |
| 迁徙中途失败 | 单事务 + 源只读副本 + 全量备份，可回滚 |

## 五、待用户确认的执行点
1. 是否同意**停止当前运行的 2 个 `openkitsune serve` 进程**（PID 22340 / 25132）以安全操作数据库？停止后由我重新启动或你手动启动。
2. 融合后的记忆库仍使用 `data/memory/openkitsune.db` 作为唯一库（清空重建），废弃 `openakita.db` —— 确认。
3. faiss / jieba 可选依赖：当前 venv 未装，融合逻辑后是否允许我 `pip install faiss-cpu jieba` 以启用完整向量检索与中文分词？（若不想装，代码将优雅降级为 FTS/关键词检索）

---

## 六、附加任务：丹道玄医录 01-个人理论 导入（已完成）

> 2026-10-15 执行。用户指令：`E:\study\丹道玄医录\01-个人理论` 全部文本导入 openkitsune.db（当前唯一记忆库），确保可检索、可加载读取，并要求**分段智能动态分页增量阅读处理**。

### 6.1 导入结果
| 项 | 值 |
|---|---|
| 扫描文本文件 | 1197 个（.md/.json/.txt/.yaml 等） |
| 写入记忆 | **3081 条**（智能分段后） |
| 记忆类型 | rule 2131 / preference 752 / experience 198 |
| priority | 全部 long_term |
| scope | 全部 user（与检索默认 scope 对齐） |
| 分页元数据 | 665 条多页章节（metadata.page_index/page_total），支持增量读取 |
| 跳过 | 1 个（空文件）；图片/脚本/缓存/pkl 等按约定跳过 |

顶层目录分布：04-融合 1424 / 06-灵汐档案 752 / 01-中医 651 / 05-设计 198 / 02-丹道 28 / 03-玄学 28。

### 6.2 实现的"分段智能动态分页增量阅读"（`src/openkitsune/memory/retrieval.py`，已备份原文件至 `data/memory_backup_pre_migration_20261015_233126/retrieval.py.bak`）
1. **注入层分段**（`_format_within_budget`）：单条记忆超预算时不再 break 导致注入为空，改为**智能截断注入前缀**（优先在段落/句末断点），并附记忆 ID 标记 `…⟦…按记忆 ID=xxx 增量读取⟧`，上层可按 ID 加载完整内容。
2. **短查询 CJK 放行**（`should_skip_retrieval`）：≥2 个连续汉字视为有效语义查询（"桂枝汤/丹道/六经"等 2-3 字中文不再被 too_short 误杀）。
3. **关键词排序增强**（`_rerank` + retrieve 接线）：把 decompose 出的查询关键词作为 focus 加分信号；长 CJK 关键词用 jieba 切子词参与匹配；完整短语命中额外 ×1.5，精确相关记忆优先注入。
4. **语义查询纯净化**：`_search_semantic` 与 `_search_recent` 改用"原始查询+关键词"（不再混入对话上下文，避免背景词稀释意图、桥接节点抢位）；recent 通道未命中查询词时 relevance 降为 0.05。
5. **数据层智能分段**（`temp/import_xuanyi_knowledge.py`）：`##` → `###` → 段落三级递归分段，目标块 ≤3000 字符（TARGET_CHUNK），段落聚合页 ≤2500 字符（PARA_CHUNK），metadata 记录 page_index/page_total。

### 6.3 验证结果（独立验证，非脚本自述）
- FTS：`MATCH '丹道'` 160 / `'河图'` 225 / `'桂枝汤'` 121 / `'六经'` 204 / `'灵汐'` 238 / `'奇门'` 30 条命中
- MemoryManager（fts5 后端）加载 3081 条全部成功，`get_stats` 正确
- 注入上下文（带对话上下文模拟）："丹道火候" 1745 字符、"桂枝汤" 1813、"灵汐修行" 1816、"中成药" 1825（均 ≈700 token 预算，首条为精确相关内容，尾附增量读取 ID）
- 增量读取：`search_memories('丹道火候')` 首条 content 2772 字符完整可加载（source=xuan-yi://01-个人理论/02-丹道/01-修炼次第/06-丹道体用临床转化.md）
- 依赖：已安装 jieba 0.42.1 + faiss-cpu 1.15.1（FTS5 中文分词生效）

### 6.4 遗留说明
- 迁移任务（阶段 2/4，openakita-main leiwa.db 行级迁移 + 28 独有逻辑文件融合）仍 pending，未受本任务影响。
- 重新导入可重跑 `temp/import_xuanyi_knowledge.py`（自动清旧批次 `xuan-yi://01-个人理论/` 再全量写入）。

---

## 七、检索测试与优化（已完成）

> 2026-10-16 执行。用户指令：测试关键词、时间范围、自然语言等几种方法的检索，并优化完善。

### 7.1 检索方法测试结果（temp/test_retrieval_methods.py）
| 方法 | 入口 | 结果 |
|---|---|---|
| 关键词 | `MemoryStorage.search_fts`（FTS5 BM25 + jieba 分词 + LIKE 兜底） | "桂枝汤" 3 条 / "丹道 火候" 3 条 / "河图" 3 条 / "中成药" 3 条 |
| 时间范围 | `storage.query(created_after/…)`、`search_fts(…, created_after)`、`engine.retrieve_by_time`（新增） | 最近 1 天=3081 条全量、2026-10-01 前=0、FTS+时间组合、时间通道均正常 |
| 自然语言 | `RetrievalEngine.retrieve` / `get_injection_context` | 桂枝汤→"桂枝汤·六对药对多角度深度解"、中成药→"中成药用药整合方案"、灵汐→修行日记，均精确命中 |

### 7.2 优化项（本轮新增/修复，均已在 e2e 回归验证）
1. **时间范围过滤支持（三层贯通）**：
   - `MemoryStorage.query` / `search_fts` 新增 `created_after/created_before/updated_after/updated_before/accessed_after` 参数（ISO 字符串，自动归一化 `' '`→`'T'`）
   - `FTS5Backend.search`、`UnifiedStore.search_semantic(_scored)` 透传时间参数
   - `RetrievalEngine.retrieve_by_time` 新增方法（时间+关键词/类型组合检索，支持 `recent_days` 快捷参数）
   - `MemoryManager.search_memories` 新增时间范围过滤（内存级 datetime 解析比较）
2. **修复 FTS5 分数反转 bug**（search_backends.py）：`bm25()` 返回负值（越负越相关），原 `1/(1+abs(rank))` 让更相关的分数反而更低，导致语义通道排序错乱；改为单调递增 `abs(rank)/(1+abs(rank))`。
3. **自然语言拆词去噪**（retrieval.py `_decompose_with_rules`）：≥4 字 CJK token 用 jieba 拆出核心词（"帮我看看桂枝汤的组成和主治"→ `桂枝/桂枝汤/组成/主治`），避免整句稀释 BM25 权重；`retrieve`/`retrieve_candidates` 的 semantic_query 统一改为关键词拼接。
4. **标题区命中加权**（`_rerank`）：内容前 120 字符命中核心词 → 记忆本身即主题，加权更强（×1.18 起步），使"桂枝汤·六对药对"等标题直接命中的记忆升至首位。

### 7.3 验证
- `verify_e2e_v7.py` 五组注入全通过：丹道火候与河图数理→"三十六宫位与体用进阶"、桂枝汤→"桂枝汤·六对药对"、灵汐修行→"灵汐修行日记"、中成药→"中成药数据库"、丹道火候→"丹道体用临床转化"，首条均为精确相关内容，尾附增量读取 ID。
- `import openkitsune.memory` 冒烟通过（MemoryManager/RetrievalEngine/UnifiedStore 可导入）。


