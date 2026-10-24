---
name: skill-manager
description: 技能全生命周期管理——创建、查看、编辑、删除、扫描技能；应用模板快速生成新技能。利用 tools/skill_manager.py 工具实现一次工具调用完成技能操作。
when_to_use: 需要创建新技能、查看已有技能、编辑或删除技能、扫描技能目录并更新索引时。典型场景：用户要求创建新技能 / agent 自动记录经验为技能 / 维护技能集合 / 用模板快速生成标准化技能。不要用于：直接编写 SKILL.md 内容（内容需 agent 自行推理生成后再调用工具写入）、已有明确路径的手动文件操作。
category: software-development
---

# Skill Manager — 技能全生命周期管理

## Overview

本技能提供标准化的技能管理流程，让 Agent 能通过一次工具调用完成技能的创建、查看、编辑、删除、扫描和模板化生成。核心逻辑在 `tools/skill_manager.py` 中实现，是一个纯 Python CLI 工具。

**核心价值：**
- **一次调用完成**：agent 只需 `python tools/skill_manager.py create <name> <content>` 即可创建技能
- **标准化注册**：自动扫描所有技能并生成 `skills_index.json` 注册表
- **模板化生成**：内置 5 套技能模板（minimal/persona/workflow/framework/reference），减少从零编写成本
- **原子写入**：避免文件写入中断导致损坏

## When to Use

- **创建技能**：用户要求「把这段经验保存为技能」「创建一个XX视角的技能」
- **查看技能**：需要检查技能内容、支持文件列表
- **编辑技能**：需要更新技能内容（find/replace 补丁或整篇重写）
- **删除技能**：确认某技能不再需要
- **扫描注册**：新增/删除技能后更新系统注册表
- **模板生成**：用已有模板快速创建标准化技能，减少重复编写

**不要用于：**
- 生成 SKILL.md **内容**本身（需 agent 自行推理编写）
- 已有精确路径的手动文件编辑
- 本技能只管理 `.astrcode/skills/` 下的技能，不管理系统内置技能

## Tool Reference: `tools/skill_manager.py`

```bash
python tools/skill_manager.py <command> [args...]
```

### 指令一览

| 指令 | 用途 | 示例 |
|------|------|------|
| `create` | 创建新技能 | `python tools/skill_manager.py create my-skill content.md --category workflow` |
| `write-file` | 写入支持文件 | `python tools/skill_manager.py write-file my-skill references/notes.md "内容"` |
| `list` | 列出所有技能 | `python tools/skill_manager.py list` |
| `list --category X` | 按分类筛选 | `python tools/skill_manager.py list --category reasoning` |
| `view` | 查看技能详情 | `python tools/skill_manager.py view my-skill` |
| `patch` | find/replace 编辑 | `python tools/skill_manager.py patch my-skill "旧文本" "新文本"` |
| `delete` | 删除技能 | `python tools/skill_manager.py delete my-skill --force` |
| `scan` | 扫描并显示 | `python tools/skill_manager.py scan` |
| `scan --update-registry` | 扫描并更新注册表 | `python tools/skill_manager.py scan --update-registry` |
| `template list` | 列出可用模板 | `python tools/skill_manager.py template list` |
| `template apply` | 用模板生成新技能 | `python tools/skill_manager.py template apply persona 黄帝 "DESCRIPTION=..."` |

## Workflow（核心工作流）

### 流程 A：创建新技能（最常用）

```
Step 1: agent 推理产出 SKILL.md 内容
Step 2: 将内容写入临时文件或直接传参
Step 3: 调用 python tools/skill_manager.py create <name> <content_file>
Step 4: 调用 python tools/skill_manager.py scan --update-registry 注册到系统
Step 5: 在回复中告知用户技能已创建及路径
```

**重要规则：**
- 内容必须包含完整的 YAML frontmatter（`---` 开头）
- frontmatter 必须有 `name` 和 `description` 字段
- 内容长度不超过 100,000 字符
- 建议使用 `--category` 指定分类，方便管理

### 流程 B：用模板快速创建

```
Step 1: python tools/skill_manager.py template list       # 查看可用模板
Step 2: python tools/skill_manager.py template apply <template> <新名称> key=val ... 
Step 3: python tools/skill_manager.py scan --update-registry  # 注册
Step 4: python tools/skill_manager.py view <新名称>        # 验证
```

### 流程 C：扫描并更新注册表（建议每次技能变更后执行）

```bash
python tools/skill_manager.py scan --update-registry
```

注册表文件位于 `.astrcode/skills/skills_index.json`，包含：
- 按分类组织的技能列表
- 每个技能的 name / slug / description / path
- 更新时间戳

## Template Reference（模板说明）

| 模板名称 | 类型 | 适用场景 | 关键变量 |
|---------|------|---------|---------|
| minimal | 最小化 | 简单工具/命令技能 | DESCRIPTION, WHEN_TO_USE |
| persona | 人物视角 | 角色扮演、思维模仿 | PERSONA_NAME, IDENTITY, QUOTE |
| workflow | 工作流 | 流程驱动型技能 | STEP_1_NAME~STEP_4_NAME |
| framework | 分析框架 | 结构化引擎 | COMPONENT_1~3, MODE_1/2 |
| reference | 知识参考 | 知识问答查阅 | TOPIC_1~3, REF_KEY/REF_VAL |

## Common Pitfalls

1. **创建后忘记扫描注册** — 每次 `create` 或 `delete` 后必须执行 `scan --update-registry`。建议将此作为 pipeline 的最后一步。
2. **内容不含完整 frontmatter** — 必须从 `---` 开始，包含 `name` + `description`。缺少会导致工具拒绝写入。
3. **用 skill-manager 来生成内容** — 本工具只负责文件操作，不负责推理。agent 必须先自己想好 SKILL.md 内容再用工具写入。
4. **模板变量遗漏** — 模板中的 `{{VARIABLE}}` 替换全部完成后才能写入。未替换的变量会保留为原文，需二次修补。
5. **技能名冲突** — `create` 前建议先用 `list` 检查是否已有同名技能。冲突时工具会报错。

## Verification Checklist

- [ ] `tools/skill_manager.py` 可执行：`python tools/skill_manager.py --help` 正常输出
- [ ] 新建技能后：`python tools/skill_manager.py view <name>` 可查看
- [ ] 注册表更新后：`cat .astrcode/skills/skills_index.json` 包含新技能
- [ ] 删除技能后：`python tools/skill_manager.py list` 不再显示
- [ ] 模板应用后：`python tools/skill_manager.py view <name>` 内容正确
- [ ] frontmatter 缺少字段时：工具应报错而非直接写入
