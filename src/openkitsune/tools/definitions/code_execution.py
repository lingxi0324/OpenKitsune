"""Execute Code 工具定义

持久会话内核执行 Python 代码（移植自 Hermes code_execution 工具集）：
- 一次起一个内核子进程，变量 / import 跨调用存活，reset=true 才重置
- 脚本内可编程式调用白名单内的宿主工具（kitsune_tools）
- 超时 / 中断自动杀内核，stdout 超出内联上限自动截断 + 全文落盘
"""

CODE_EXECUTION_TOOLS: list[dict] = [
    {
        "name": "execute_code",
        "category": "Development",
        "description": (
            "Execute Python code in a session-persistent kernel. One kernel per "
            "(session, interpreter, cwd, tool-set): variables and imports survive "
            "across calls until you pass reset=true.\n\n"
            "Inside the script you can programmatically call host tools that are "
            "on the sandbox allow-list (read-only tools by default) via the "
            "``kitsune_tools`` module:\n"
            "    from kitsune_tools import read_file, web_search\n"
            "    content = read_file(path=\"...\")[\"content\"]\n"
            "Helpers: ``from kitsune_tools import json_parse, shell_quote, retry``.\n\n"
            "Rules:\n"
            "- Use Python stdlib; third-party packages may be missing in the kernel.\n"
            "- A cell that times out or is interrupted kills the kernel and its state "
            "(next call starts fresh).\n"
            "- Output over the inline cap is truncated to head/tail and the FULL text "
            "is saved to disk (path reported) — page it with read_file instead of re-running.\n\n"
            "Prefer execute_code over run_shell/run_powershell for in-memory Python "
            "work: no temp files, no per-call process spawn, state persists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "The Python code to execute. Runs with exec() in the kernel's "
                        "persistent GLOBALS namespace; print() output is returned. "
                        "Use print() to surface results."
                    ),
                },
                "reset": {
                    "type": "boolean",
                    "description": (
                        "When true, discard the current kernel state (variables, imports) "
                        "and start a fresh kernel before running this cell. "
                        "Default: false."
                    ),
                    "default": False,
                },
            },
            "required": ["code"],
        },
        "detail": (
            "Execute Code（持久内核轻量执行通道）。\n\n"
            "使用场景：\n"
            "- 需要跨多次调用保留变量/import 状态的 Python 工作流\n"
            "- 数据清洗、格式转换、批量计算等纯 Python 任务（无临时文件、无子进程反复创建）\n"
            "- 脚本内需要编程式调用宿主工具（读取文件、搜索记忆等只读操作）\n\n"
            "限制：\n"
            "- 默认超时 300s（最大 900s），超时/中断会杀掉内核并丢失状态\n"
            "- 单次最多 50 次脚本内工具调用\n"
            "- 脚本内工具白名单默认仅只读安全工具（read_file/grep/web_search 等）\n"
            "- 内核使用 OpenKitsune 应用解释器（.venv），第三包依赖以该环境为准"
        ),
        "triggers": [
            "User asks to run Python code",
            "Need state to persist across multiple code runs",
            "Need to call host tools programmatically from a script",
            "Avoid temp files and repeated process spawns",
        ],
        "examples": [
            {
                "scenario": "Persistent variable across calls",
                "params": {"code": "counter = (counter + 1 if 'counter' in globals() else 1); print(counter)"},
                "expected": "1 on first call, 2 on second, ... (state persists)",
            },
            {
                "scenario": "Reset kernel state",
                "params": {"code": "print('fresh')", "reset": True},
                "expected": "Kernel state discarded and a fresh kernel runs the cell",
            },
            {
                "scenario": "Call a host tool from the script",
                "params": {"code": "from kitsune_tools import list_directory\nprint(list_directory(path='.'))"},
                "expected": "Directory listing returned via the host tool",
            },
        ],
        "related_tools": [
            {"name": "run_powershell", "relation": "heavier alternative (spawns a process per call)"},
            {"name": "read_file", "relation": "page spilled stdout with read_file"},
        ],
    },
]
