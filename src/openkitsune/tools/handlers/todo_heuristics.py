"""多步骤任务启发式检测"""

import re as _re

__all__ = ["should_require_todo"]


def should_require_todo(user_message: str) -> bool:
    """
    检测用户请求是否需要 Todo 模式（多步骤任务检测）

    触发条件：
    1. 包含 2+ 个动作词（普通动作词，放宽自 5+：多步任务无需 5 个动词才建计划）
    2. 包含探索/分析型动词（"看看/检查/验证/对比/排查"等）——这类任务表面是
       一句话，实际几乎都要多轮工具调用，是"想到哪做到哪、重复调用"的重灾区，
       必须一开始就建 todo 锚定步骤与进度
    3. 包含 3+ 个动作词 + 连接词（明确的多步骤）
    4. 包含 3+ 个动作词 + 逗号分隔（明确的多步骤）

    简单任务（无动作词、纯问答、单步查看）仍直接执行，不过度计划。
    """
    if not user_message:
        return False

    msg = user_message.lower()

    zh_action_words = [
        "打开",
        "搜索",
        "截图",
        "发给",
        "发送",
        "写",
        "创建",
        "执行",
        "运行",
        "读取",
        "查看",
        "保存",
        "下载",
        "上传",
        "复制",
        "粘贴",
        "删除",
        "编辑",
        "修改",
        "更新",
        "安装",
        "配置",
        "设置",
        "启动",
        "关闭",
    ]
    en_action_words = [
        "open",
        "search",
        "screenshot",
        "send",
        "write",
        "create",
        "execute",
        "run",
        "read",
        "view",
        "save",
        "download",
        "upload",
        "copy",
        "paste",
        "delete",
        "edit",
        "modify",
        "update",
        "install",
        "configure",
        "setup",
        "start",
        "stop",
        "close",
        "deploy",
        "build",
        "test",
        "refactor",
        "migrate",
        "fix",
        "implement",
        "add",
        "remove",
    ]

    zh_connectors = ["然后", "接着", "之后", "并且", "再", "最后"]
    en_connectors = ["then", "after that", "next", "finally", "and then", "followed by", "also"]

    # 探索/分析型动词：一句话请求但实际需要多轮工具调用的任务
    # （"看看记忆系统是否正常"、"对比两个方案"、"排查报错原因"等）。
    # 这类请求旧逻辑判定为"非多步"而不建 todo，导致 agent 无计划锚点、
    # 每轮失忆重做、同一查询反复执行——必须优先触发计划模式。
    zh_explore_words = [
        "看看",
        "检查",
        "验证",
        "确认",
        "对比",
        "比较",
        "分析",
        "排查",
        "审查",
        "定位",
        "找出",
        "查明",
        "调研",
        "诊断",
        "了解",
        "复盘",
    ]
    en_explore_words = [
        "check",
        "verify",
        "compare",
        "analyze",
        "diagnose",
        "inspect",
        "investigate",
        "review",
        "audit",
        "look into",
        "figure out",
        "find out",
        "debug",
    ]

    action_count = sum(1 for w in zh_action_words if w in msg)
    for w in en_action_words:
        if _re.search(r"\b" + _re.escape(w), msg):
            action_count += 1

    explore_count = sum(1 for w in zh_explore_words if w in msg)
    for w in en_explore_words:
        if _re.search(r"\b" + _re.escape(w) + r"\b", msg):
            explore_count += 1

    has_connector = any(w in msg for w in zh_connectors) or any(
        _re.search(r"\b" + _re.escape(w) + r"\b", msg) for w in en_connectors
    )

    comma_separated = "，" in msg or "," in msg

    # 探索/分析型任务：命中即需要计划锚点（消息足够长、不是单字问答时）
    if explore_count >= 1 and len(msg.strip()) >= 8:
        return True
    # 放宽：两个及以上动作词即视为多步任务
    if action_count >= 2:
        return True
    if action_count >= 3 and has_connector:
        return True
    return bool(action_count >= 3 and comma_separated)
