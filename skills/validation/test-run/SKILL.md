---
name: test-run
description: 封装 pytest/unittest/nose 等 Python 测试框架，自动执行测试并生成结果报告。
---

# Test Run - Agent 测试执行工具

**ID**: test_run
**描述**: 封装 pytest/unittest/nose 等 Python 测试框架，自动执行测试并生成结果报告。
**类型**: 验证层工具

---

# Test Run - Agent 测试执行工具

## 核心功能

自动执行项目测试，统计通过率、失败率、覆盖率，为代码修改提供客观验证。支持 Python 主流测试框架（pytest、unittest、nose）。

## 支持框架

| 框架 | 检测方式 | 命令 |
|------|---------|------|
| **pytest** | 查找 `pytest.ini`/`pyproject.toml`/`setup.cfg` | `pytest [options]` |
| **unittest** | 查找 `test_*.py`/`*_test.py` | `python -m unittest discover` |
| **nose** | 查找 `nose.cfg` | `nosetests [options]` |

## 使用场景

- **代码修改后** — 验证修改未破坏现有功能
- **依赖更新后** — 验证依赖更新未引入问题
- **重构后** — 验证重构保持功能正确性
- **提交前** — 确保代码可提交
- **定期** — CI/CD 流水线中定期执行

## 测试执行流程

```
1. 检测测试框架
   - 查找 pytest/unittest/nose 配置
   - 确定测试命令

2. 执行测试
   - 运行测试命令
   - 捕获 stdout/stderr/退出码

3. 分析结果
   - 统计通过/失败/跳过数量
   - 提取失败详情
   - 计算覆盖率

4. 生成报告
   - 结果摘要
   - 失败测试列表
   - 覆盖率统计
```

## 参数说明

- **test_path**: 测试路径（可选，默认执行全部测试）
- **framework**: 测试框架（可选，自动检测）
- **test_filter**: 测试过滤器（如 `test_user.py`、`::test_login`）
- **coverage**: 是否生成覆盖率报告（默认 true）
- **max_failures**: 最大失败数（达到后停止，默认 10）
- **timeout**: 单个测试超时（秒，默认 30）
- **parallel**: 是否并行执行（默认 true）

## 输出格式

```json
{
  "test_run_id": "test_20240101_120000_001",
  "timestamp": "2024-01-01T12:00:00",
  "framework": "pytest",
  "test_path": "tests/",
  "command": "pytest tests/ -v --tb=short --cov=src --cov-report=term",
  "exit_code": 1,
  "summary": {
    "total": 50,
    "passed": 42,
    "failed": 6,
    "skipped": 2,
    "error": 0,
    "duration_seconds": 15.5
  },
  "failures": [
    {
      "test_name": "test_user_login_invalid",
      "file": "tests/test_user.py:15",
      "error_type": "AssertionError",
      "message": "Expected 401, got 200",
      "traceback": "..."
    }
  ],
  "coverage": {
    "overall": 78.5,
    "files": [
      {"file": "src/user.py", "coverage": 95.0, "missing_lines": [15, 30]},
      {"file": "src/auth.py", "coverage": 60.0, "missing_lines": [10, 20, 25]}
    ]
  },
  "recommendation": "fix_failures|proceed|retest"
}
```

## 与相关工具的关系

- **lint_check** — 测试前建议先 lint 检查
- **self_review** — 测试后自检确认修复
- **root_cause** — 失败时分析根因
- **coverage_check** — 详细覆盖率分析
- **test_run** — 多次测试执行

## 使用示例

```python
# 示例 1：执行全部测试
test_run()
# 执行 tests/ 目录下全部测试

# 示例 2：执行特定测试
test_run(
    test_path="tests/test_user.py",
    test_filter="test_login"
)
# 执行 test_user.py 中 test_login 相关测试

# 示例 3：限制失败数
test_run(
    max_failures=5,
    coverage=True
)
# 最多报告 5 个失败，生成覆盖率报告

# 示例 4：指定框架
test_run(
    framework="pytest",
    test_path="tests/unit/"
)
# 使用 pytest 执行 unit 测试
```

## 注意事项

- **测试依赖** — 确保测试框架已安装（pytest/unittest）
- **测试环境** — 测试应在隔离环境执行
- **超时设置** — 长时间测试设置合理超时
- **并行执行** — 并行测试注意资源竞争
- **失败处理** — 失败测试需要修复后重新测试
- **覆盖率** — 覆盖率低不代表代码质量好
- **CI/CD** — 建议集成到 CI/CD 流水线
- **测试数据** — 测试应使用模拟数据，不依赖真实数据
