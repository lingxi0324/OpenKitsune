---
name: root-cause
description: 对任务失败、错误、异常进行结构化根因分析，使用 5Why、鱼骨图、因果链等方法定位根本原因，为修复提供方向。
---

# Root Cause - Agent 根因分析工具

**ID**: root_cause
**描述**: 对任务失败、错误、异常进行结构化根因分析，使用 5Why、鱼骨图、因果链等方法定位根本原因，为修复提供方向。
**类型**: 反思层工具

---

# Root Cause Analysis - Agent 根因分析工具

## 核心功能

当任务失败、测试不通过、服务异常时，`root_cause` 提供结构化的根因分析方法论，避免"表面修复"导致问题反复出现。

## 分析方法

### 1. 5Why 分析法
连续追问 5 层"为什么"，定位根本原因：

```
问题：服务启动失败
├─ Why 1: 端口被占用
│  └─ Why 2: 旧进程未正常退出
│     └─ Why 3: 信号处理函数缺失
│        └─ Why 4: 代码重构时遗漏
│           └─ Root Cause: 重构流程无完整性检查
```

### 2. 鱼骨图分析法
从人、机、料、法、环 5 个维度分析：

```
                    服务启动失败
                   /   |   \
              代码   配置   环境
             /       |       \
        信号处理   端口配置   依赖缺失
        缺失      冲突      版本不匹配
```

### 3. 因果链分析
构建完整的因果关系图：

```
Root Cause → Intermediate Cause → Symptom
(重构遗漏) → (信号处理缺失) → (旧进程残留) → (端口占用) → (启动失败)
```

## 使用场景

- **任务失败后** — 分析失败原因，指导修复
- **测试不通过** — 定位测试失败的根因
- **服务异常** — 诊断服务问题的根本原因
- **重复问题** — 找出导致反复出现问题的系统性原因

## 分析流程

```
1. 问题收集
   - 错误信息
   - 日志输出
   - 测试失败详情
   - 变更历史

2. 证据收集
   - evidence_verify 验证失败证据
   - grep/read_file 定位问题代码
   - log_inspect 分析日志

3. 因果链构建
   - 从症状倒推原因
   - 使用 5Why 深入分析
   - 绘制鱼骨图分类

4. 根因确认
   - 验证根因是否合理
   - 排除其他可能性
   - 确认根因可修复

5. 修复建议
   - 短期修复方案
   - 长期预防方案
   - 风险评估
```

## 输出格式

```json
{
  "problem_id": "analysis_001",
  "symptom": "服务启动失败，端口 8080 被占用",
  "timestamp": "2024-01-01T00:00:00",
  "evidence": [
    {
      "type": "error_log",
      "content": "Address already in use",
      "source": "log_inspect: server.log"
    }
  ],
  "analysis": {
    "method": "5why",
    "chain": [
      {"level": 1, "question": "为什么端口被占用？", "answer": "旧进程未退出"},
      {"level": 2, "question": "为什么旧进程未退出？", "answer": "信号处理函数缺失"},
      {"level": 3, "question": "为什么信号处理函数缺失？", "answer": "代码重构时遗漏"},
      {"level": 4, "question": "为什么重构会遗漏？", "answer": "重构流程无完整性检查"},
      {"level": 5, "question": "为什么无完整性检查？", "answer": "团队缺乏重构检查清单"}
    ],
    "root_cause": "重构流程缺乏完整性检查机制",
    "confidence": 0.85
  },
  "fishbone": {
    "category": "方法",
    "factors": {
      "代码": "信号处理函数缺失",
      "流程": "重构无检查清单",
      "工具": "无自动检测旧进程工具",
      "文档": "重构指南未更新"
    }
  },
  "recommendations": {
    "short_term": "添加信号处理函数，修改 server.py",
    "long_term": "建立重构检查清单，自动检测旧进程",
    "prevention": "代码审查加入信号处理检查项"
  },
  "related_skills": ["postmortem", "self_review", "audit_log"]
}
```

## 与相关工具的关系

- **evidence_verify** — 收集失败证据，确保分析基于事实
- **self_review** — 修复后自检，确认根因已解决
- **postmortem** — 复盘分析结果，更新记忆
- **decision_log** — 记录决策依据

## 使用示例

```python
# 任务失败后调用
root_cause(
    problem_id="service_startup_fail_001",
    symptom="服务启动失败，端口 8080 被占用",
    evidence_sources=["server.log", "error_output", "git_diff"]
)

# 返回分析报告
# 根据建议修复
# 修复后 self_review 验证
```

## 注意事项

- 根因分析基于证据，不主观臆断
- 5Why 不要超过 7 层，避免过度分析
- 鱼骨图应覆盖所有可能维度
- 修复建议应区分短期和长期
- 分析结果应记录到审计日志
- 重复出现的根因应更新知识库
