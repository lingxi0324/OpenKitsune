# OpenKitsune 补全工具集 - 技能索引

## 新增技能清单

### 一、反思层（4 个技能）

| 技能 ID | 技能名称 | 描述 | 优先级 |
|---------|---------|------|--------|
| `self_review` | Agent 自检工具 | 任务交付前 7 步自检，防止幻觉和假成功 | ⭐⭐⭐⭐⭐ |
| `evidence_verify` | 证据核验工具 | 为关键结论收集可验证证据链 | ⭐⭐⭐⭐⭐ |
| `root_cause` | 根因分析工具 | 5Why/鱼骨图定位失败根本原因 | ⭐⭐⭐⭐ |
| `postmortem` | 事后复盘工具 | 失败/回滚事件复盘，更新记忆系统 | ⭐⭐⭐⭐ |
| `risk_assess` | 风险评估工具 | 变更前评估影响面、回滚难度、安全风险 | ⭐⭐⭐⭐ |

### 二、恢复层（2 个技能）

| 技能 ID | 技能名称 | 描述 | 优先级 |
|---------|---------|------|--------|
| `checkpoint_create` | 检查点创建工具 | 高风险操作前创建文件/配置/Git 快照 | ⭐⭐⭐⭐⭐ |
| `rollback_apply` | 回滚应用工具 | 根据检查点恢复文件/配置/Git 状态 | ⭐⭐⭐⭐⭐ |

### 三、验证层（2 个技能）

| 技能 ID | 技能名称 | 描述 | 优先级 |
|---------|---------|------|--------|
| `test_run` | 测试执行工具 | 封装 pytest/unittest，执行测试生成报告 | ⭐⭐⭐⭐ |
| `health_check` | 服务健康检测 | HTTP/TCP/进程探测，验证服务存活 | ⭐⭐⭐⭐ |

### 四、治理层（3 个技能）

| 技能 ID | 技能名称 | 描述 | 优先级 |
|---------|---------|------|--------|
| `audit_log` | 审计日志工具 | 不可关闭的操作审计，支持查询统计 | ⭐⭐⭐⭐⭐ |
| `dry_run_guard` | 变更预览保护 | 写操作前强制预览 diff，未确认不写入 | ⭐⭐⭐⭐⭐ |

---

## 闭环工作流（新增 + 已有）

```
1. 任务接收与规划
   plan_create → task_track → mem_recall

2. 风险评估
   risk_assess → permission_gate → dry_run_guard

3. 检查点创建
   checkpoint_create

4. 只读感知
   file_scan → grep_search → file_read

5. 编辑变更
   file_patch / yaml_edit / file_operate

6. 变更核验
   diff_check → lint_check → type_check
   test_run → coverage_check

7. 执行与测试
   exec_python / exec_shell / exec_sql
   health_check → log_inspect

8. 核实反思
   evidence_verify → self_review → root_cause
   risk_assess → postmortem

9. 失败处理
   失败 → root_cause → 重新编辑
   严重失败 → rollback_apply → checkpoint 恢复

10. 复盘与记忆
    postmortem → mem_store → audit_log
```

---

## 快速使用指南

### 场景 1：代码修改前
```
1. risk_assess(操作类型=代码修改) → 评估风险
2. checkpoint_create(描述=修改前备份) → 创建检查点
3. dry_run_guard(操作=文件修改) → 预览 diff
4. edit_file(修改代码) → 执行修改
5. test_run() → 运行测试
6. self_review() → 自检通过
```

### 场景 2：服务配置变更
```
1. risk_assess(操作类型=配置变更) → 评估风险
2. checkpoint_create(描述=配置备份) → 创建检查点
3. dry_run_guard(操作=配置变更) → 预览 diff
4. 修改配置 → 执行变更
5. health_check(服务名=api-server) → 检测服务状态
6. self_review() → 自检通过
```

### 场景 3：依赖更新
```
1. risk_assess(操作类型=依赖更新) → 评估风险
2. checkpoint_create(描述=依赖备份) → 创建检查点
3. 更新依赖 → 执行变更
4. test_run() → 运行测试
5. 如果失败 → rollback_apply(检查点=依赖备份)
6. postmortem(事件=依赖更新失败) → 复盘
```

### 场景 4：任务失败后
```
1. root_cause(问题=测试失败) → 根因分析
2. 根据分析修复
3. test_run() → 重新测试
4. self_review() → 自检通过
5. postmortem(事件=测试失败) → 复盘更新记忆
```

---

## 技能依赖关系

```
self_review
├── evidence_verify（证据核验）
├── root_cause（根因分析）
└── audit_log（审计日志）

rollback_apply
└── checkpoint_create（检查点创建）

test_run
├── lint_check（静态检查）
└── self_review（自检）

health_check
├── service_ctl（服务控制）
└── log_inspect（日志探查）

postmortem
├── root_cause（根因分析）
├── evidence_verify（证据核验）
└── add_memory（记忆更新）

audit_log
└── secret_redact（密钥脱敏）

dry_run_guard
├── edit_file（文件修改）
└── permission_gate（权限门禁）

risk_assess
├── checkpoint_create（检查点创建）
├── dry_run_guard（变更预览）
└── decision_log（决策记录）
```

---

## 文件路径

所有技能文件位于：
```
C:\Users\Administrator\.OpenKitsune\OpenKitsune\skills\
├── reflection/
│   ├── self_review/
│   ├── evidence_verify/
│   ├── root_cause/
│   ├── postmortem/
│   └── risk_assess/
├── recovery/
│   ├── checkpoint_create/
│   └── rollback_apply/
├── validation/
│   ├── test_run/
│   └── health_check/
└── governance/
    ├── audit_log/
    └── dry_run_guard/
```

---

## 实现状态

| 技能 | 状态 | 文件路径 |
|------|------|---------|
| self_review | ✅ 已创建 | skills/reflection/self_review/SKILL.md |
| evidence_verify | ✅ 已创建 | skills/reflection/evidence_verify/SKILL.md |
| root_cause | ✅ 已创建 | skills/reflection/root_cause/SKILL.md |
| postmortem | ✅ 已创建 | skills/reflection/postmortem/SKILL.md |
| risk_assess | ✅ 已创建 | skills/reflection/risk_assess/SKILL.md |
| checkpoint_create | ✅ 已创建 | skills/recovery/checkpoint_create/SKILL.md |
| rollback_apply | ✅ 已创建 | skills/recovery/rollback_apply/SKILL.md |
| test_run | ✅ 已创建 | skills/validation/test_run/SKILL.md |
| health_check | ✅ 已创建 | skills/validation/health_check/SKILL.md |
| audit_log | ✅ 已创建 | skills/governance/audit_log/SKILL.md |
| dry_run_guard | ✅ 已创建 | skills/governance/dry_run_guard/SKILL.md |

---

## 下一步

### 已完成
- ✅ 11 个技能文档已创建
- ✅ 覆盖反思层、恢复层、验证层、治理层

### 待完善
- [ ] 技能实际执行逻辑（当前为 SKILL.md 文档，需封装为可执行脚本）
- [ ] 权限门禁（permission_gate）实现
- [ ] 工作流引擎（workflow_run）实现
- [ ] SQL 执行工具（exec_sql）实现
- [ ] 命令白名单（command_whitelist）实现
- [ ] 密钥脱敏（secret_redact）实现
- [ ] 记忆写入（mem_store）封装
- [ ] 决策记录（decision_log）封装

### 建议优先级
1. 封装可执行脚本（SKILL.md → 实际工具）
2. 实现权限门禁
3. 实现工作流引擎
4. 补充剩余治理层工具
