"""
计划看板（Kanban）Agent 工具定义

对标 Hermes ``tools/kanban_tools_schemas.py``，精简为核心看板操作：
- kanban_create: 创建卡片
- kanban_list: 列出卡片
- kanban_get: 查看卡片详情（含评论与活动流）
- kanban_move: 状态流转
- kanban_update: 更新字段
- kanban_comment: 追加评论
- kanban_complete: 标记完成（移动到 done + 总结）
- kanban_delete: 删除卡片
"""

__all__ = ["KANBAN_TOOLS"]

_STATUS_ENUM = ["todo", "in_progress", "blocked", "done"]

KANBAN_TOOLS = [
    {
        "name": "kanban_create",
        "category": "Kanban",
        "description": (
            "Create a new kanban card on the plan board. "
            "Use to register a task, plan item or follow-up the user asked to track, "
            "so it stays visible on the board and can be moved through todo/in_progress/blocked/done."
        ),
        "detail": """创建计划看板卡片。

**何时使用**：
- 用户要求“记到看板上”“列入计划”“跟踪这个任务”
- 将大任务拆解为可跟踪的卡片
- 需要跨会话保留的任务/计划

**参数**：
- `title`: 卡片标题（必填）
- `description`: 详细描述/验收标准
- `assignee`: 负责人（可选）
- `priority`: 优先级，数字越大越靠前（0/1/2/3）
- `status`: 初始列：todo/in_progress/blocked/done（默认 todo）
- `board_id`: 看板 ID（默认 default）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "卡片标题（必填）"},
                "description": {"type": "string", "description": "卡片描述 / 验收标准"},
                "assignee": {"type": "string", "description": "负责人（可选）"},
                "priority": {
                    "type": "integer",
                    "description": "优先级，数字越大越靠前（0/1/2/3）",
                },
                "status": {
                    "type": "string",
                    "enum": _STATUS_ENUM,
                    "description": "初始列，默认 todo",
                },
                "board_id": {"type": "string", "description": "看板 ID，默认 default"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "kanban_list",
        "category": "Kanban",
        "description": (
            "List kanban cards so an agent can discover tracked work. "
            "Supports filters by status column, assignee and archived state. "
            "Returns compact rows with id, title, status, assignee, priority and comment count."
        ),
        "detail": """列出计划看板卡片。

**过滤参数**：
- `status`: todo / in_progress / blocked / done（不传则返回全部非归档）
- `assignee`: 只看某负责人
- `include_archived`: 是否包含已归档卡片（默认 false）
- `limit`: 返回条数上限（默认 50，最大 200）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "board_id": {"type": "string", "description": "看板 ID，默认 default"},
                "status": {
                    "type": "string",
                    "enum": [*_STATUS_ENUM, "archived"],
                    "description": "状态列过滤",
                },
                "assignee": {"type": "string", "description": "负责人过滤"},
                "include_archived": {
                    "type": "boolean",
                    "description": "包含已归档（默认 false）",
                },
                "limit": {"type": "integer", "description": "返回条数上限（默认 50，最大 200）"},
            },
        },
    },
    {
        "name": "kanban_get",
        "category": "Kanban",
        "description": (
            "Read a single kanban card's full state: title, description, assignee, priority, "
            "status, comments and recent events. Use to orient before working on a tracked card."
        ),
        "detail": """查看卡片详情。

返回标题、描述、负责人、优先级、状态、评论列表与最近活动流。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
            },
            "required": ["card_id"],
        },
    },
    {
        "name": "kanban_move",
        "category": "Kanban",
        "description": (
            "Move a card to another status column on the board: "
            "todo → in_progress → blocked → done (and back). "
            "Call after you start / finish / hit a blocker on a tracked card so the board stays live."
        ),
        "detail": """流转卡片状态。

- 开始执行 → `in_progress`
- 遇到阻塞 → `blocked`（可附 note 说明原因）
- 完成 → `done`（更推荐 kanban_complete 记录总结）
- 回归 → `todo`""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
                "status": {
                    "type": "string",
                    "enum": [*_STATUS_ENUM, "archived"],
                    "description": "目标状态列",
                },
                "note": {"type": "string", "description": "流转说明（可选，记录到活动流）"},
            },
            "required": ["card_id", "status"],
        },
    },
    {
        "name": "kanban_update",
        "category": "Kanban",
        "description": (
            "Update a card's fields: title, description, assignee or priority. "
            "Use for corrections and refinements while a tracked card is in flight."
        ),
        "detail": """更新卡片字段（标题/描述/负责人/优先级），至少传一个字段。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
                "title": {"type": "string", "description": "新标题"},
                "description": {"type": "string", "description": "新描述"},
                "assignee": {"type": "string", "description": "新负责人（传空串清除）"},
                "priority": {"type": "integer", "description": "新优先级 0/1/2/3"},
            },
            "required": ["card_id"],
        },
    },
    {
        "name": "kanban_comment",
        "category": "Kanban",
        "description": (
            "Append a comment to a card's thread. "
            "Use for durable notes: progress updates, questions, findings, handoff notes."
        ),
        "detail": """给卡片追加评论。

用于留下持久记录：进度说明、疑问、结论、交接备注。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
                "body": {"type": "string", "description": "评论内容（必填）"},
            },
            "required": ["card_id", "body"],
        },
    },
    {
        "name": "kanban_complete",
        "category": "Kanban",
        "description": (
            "Mark a card done with a structured handoff. Moves the card to 'done' and "
            "appends a completion comment summarizing what was done. "
            "Prefer over kanban_move when finishing tracked work."
        ),
        "detail": """标记卡片完成。

- 将卡片移动到 `done` 列
- 追加一条完成评论（summary 内容）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
                "summary": {"type": "string", "description": "完成总结（1-3 句，必填）"},
            },
            "required": ["card_id", "summary"],
        },
    },
    {
        "name": "kanban_delete",
        "category": "Kanban",
        "description": (
            "Permanently delete a card (including its comments). "
            "Prefer archiving via kanban_move(card_id, 'archived') when you want to keep history."
        ),
        "detail": """永久删除卡片（含评论）。

如需保留记录，请改用 kanban_move 移动到 archived。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "string", "description": "卡片 ID（必填）"},
            },
            "required": ["card_id"],
        },
    },
]
