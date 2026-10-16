---
name: evidence-verify
description: 为 Agent 的关键结论、声称的操作结果、决策依据收集并验证证据链，确保“所见即所得”，防止幻觉和假成功。
---

# Evidence Verify - Agent 证据核验工具

**ID**: evidence_verify
**描述**: 为 Agent 的关键结论、声称的操作结果、决策依据收集并验证证据链，确保"所见即所得"，防止幻觉和假成功。
**类型**: 反思层工具

---

# Evidence Verify - Agent 证据核验工具

## 核心功能

Agent 在执行任务、得出结论时，可能产生**幻觉**（声称做了但没做）或**假成功**（表面成功但实际错误）。`evidence_verify` 通过收集可验证的证据链，确保每个关键结论都有真实依据。

## 使用场景

- **交付前验证** — 确认"已完成"的操作确实生效
- **决策依据** — 记录关键决策的证据链
- **失败分析** — 收集失败证据，为 root_cause 提供数据
- **审计追踪** — 为关键操作留存证据

## 证据类型

| 证据类型 | 来源 | 可信度 |
|---------|------|--------|
| **文件证据** | `read_file` + `grep` 返回的实际内容 | ★★★★★ |
| **执行证据** | `run_powershell`/`run_shell` 的 stdout/stderr/退出码 | ★★★★★ |
| **测试证据** | `test_run`/`read_lints` 的客观结果 | ★★★★☆ |
| **diff 证据** | `edit_file`/`write_file` 修改前后的对比 | ★★★★☆ |
| **状态证据** | `list_directory`/`list_plugins`/`get_skill_info` 的当前状态 | ★★★★☆ |
| **推理证据** | Agent 自身的逻辑推理 | ★★☆☆☆（需额外验证） |

## 核验流程

```
Agent 声称"已完成 X"
    ↓
evidence_verify(claim="已完成 X", required_evidence=["文件修改", "测试结果"])
    ↓
收集证据：
  - 读取修改后的文件内容
  - 检查执行结果
  - 验证测试通过
    ↓
证据评分：
  - 强证据（文件/执行）→ 可信
  - 中证据（测试/diff）→ 较可信
  - 弱证据（推理）→ 需额外验证
    ↓
返回结果：
  - verified（证据充分）
  - weak（证据不足，需补充）
  - unverified（无证据，不可信）
```

## 参数说明

- **claim**: Agent 声称的操作结果（如"文件已修改"、"服务已启动"、"测试通过"）
- **required_evidence**: 需要的证据类型列表
- **verification_points**: 具体的验证点（文件路径、命令、测试结果等）
- **min_strong_evidence**: 最低强证据数量（默认 1）

## 输出格式

```json
{
  "claim": "文件已修改",
  "verification_timestamp": "2024-01-01T00:00:00",
  "status": "verified|weak|unverified",
  "evidence_chain": [
    {
      "type": "file_content",
      "source": "read_file: path/to/file.py",
      "content_snippet": "关键行内容...",
      "confidence": 0.95,
      "strength": "strong"
    },
    {
      "type": "execution_result",
      "source": "run_powershell: test-command",
      "stdout": "Success",
      "exit_code": 0,
      "confidence": 0.98,
      "strength": "strong"
    }
  ],
  "missing_evidence": [
    {
      "type": "test_result",
      "recommendation": "建议运行测试验证"
    }
  ],
  "overall_confidence": 0.92,
  "recommendation": "交付|补充证据|终止"
}
```

## 与相关工具的关系

- **self_review** — self_review 调用 evidence_verify 为每个检查项收集证据
- **root_cause** — 失败时，evidence_verify 提供的证据链是根因分析的基础
- **audit_log** — 证据链记录到审计日志，供事后审查

## 使用示例

```python
# 示例 1：验证文件修改
evidence_verify(
    claim="config.yaml 已更新数据库连接",
    required_evidence=["file_content"],
    verification_points=["path/config.yaml"]
)
# 返回：verified，证据包含实际文件内容

# 示例 2：验证服务启动
evidence_verify(
    claim="数据库服务已启动",
    required_evidence=["execution_result", "file_content"],
    verification_points=["run_powershell: netstat -ano | findstr 3306"]
)
# 返回：weak，缺少文件证据，建议补充

# 示例 3：验证测试通过
evidence_verify(
    claim="单元测试全部通过",
    required_evidence=["execution_result"],
    verification_points=["run_powershell: pytest --tb=short"]
)
# 返回：verified，证据包含实际测试输出
```

## 注意事项

- 强证据优先（文件内容、执行输出）
- 弱证据（推理、推断）必须标注置信度
- 关键操作建议至少 2 个强证据
- 证据链应可追溯、可复现
- 不验证的证据不应作为交付依据
