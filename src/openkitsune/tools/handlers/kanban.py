"""
KanbanHandler 类 + create_kanban_handler 工厂函数

计划看板 Agent 工具执行层。对标 Hermes ``tools/kanban_tools.py`` 精简移植，
全部读写走 ``openkitsune.kanban.store`` 数据层（SQLite 单例），
与桌面面板 /api/kanban 共享同一份数据。

# ApprovalClass checklist（新增 / 修改工具时必读）
# 1. 在本文件 Handler 类的 TOOLS 列表加新工具名
# 2. 在同 Handler 类的 TOOL_CLASSES 字典加 ApprovalClass 显式声明
# 3. 行为依赖参数 → 在 policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
"""

import json
import logging
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass
from ...kanban.store import get_kanban_store

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)

__all__ = ["KanbanHandler", "create_handler", "create_kanban_handler"]


class KanbanHandler:
    """计划看板（Kanban）工具处理器"""

    TOOLS = [
        "kanban_create",
        "kanban_list",
        "kanban_get",
        "kanban_move",
        "kanban_update",
        "kanban_comment",
        "kanban_complete",
        "kanban_delete",
    ]

    # C7 explicit ApprovalClass — 看板读写对用户资产影响可控，全部走审计活动流
    TOOL_CLASSES = {
        "kanban_create": ApprovalClass.MUTATING_SCOPED,
        "kanban_list": ApprovalClass.READONLY_GLOBAL,
        "kanban_get": ApprovalClass.READONLY_GLOBAL,
        "kanban_move": ApprovalClass.MUTATING_SCOPED,
        "kanban_update": ApprovalClass.MUTATING_SCOPED,
        "kanban_comment": ApprovalClass.MUTATING_SCOPED,
        "kanban_complete": ApprovalClass.MUTATING_SCOPED,
        "kanban_delete": ApprovalClass.DESTRUCTIVE,
    }

    def __init__(self, agent: "Agent"):
        self.agent = agent
        self._store = get_kanban_store()

    def _author(self) -> str:
        """评论作者：优先当前 agent 身份，回退到 'agent'。"""
        profile_id = getattr(self.agent, "agent_profile_id", None) or getattr(
            self.agent, "profile_id", None
        )
        if profile_id:
            return str(profile_id)
        name = getattr(self.agent, "name", None)
        if name:
            return str(name)
        return "agent"

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        """工具分发入口（同步执行，返回 JSON 字符串）。"""
        try:
            method = getattr(self, f"_{tool_name}", None)
            if method is None:
                return json.dumps(
                    {"ok": False, "error": f"未知看板工具: {tool_name}"}, ensure_ascii=False
                )
            result = method(params or {})
            if result is None:
                return json.dumps({"ok": True}, ensure_ascii=False)
            if isinstance(result, str):
                return result
            return json.dumps({"ok": True, **result}, ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except KeyError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:  # 兜底：不让工具异常打断 agent 主循环
            logger.exception("kanban tool %s failed", tool_name)
            return json.dumps({"ok": False, "error": f"看板操作失败: {exc}"}, ensure_ascii=False)

    # ── 工具实现（同步，handler 层已由 registry 兼容同步/异步） ──────────

    def _kanban_create(self, params: dict) -> dict:
        title = str(params.get("title", "")).strip()
        if not title:
            raise ValueError("卡片标题不能为空")
        card = self._store.create_card(
            title=title,
            description=str(params.get("description", "") or ""),
            board_id=str(params.get("board_id", "default") or "default"),
            status=str(params.get("status", "todo") or "todo"),
            assignee=(str(params["assignee"]).strip() if params.get("assignee") else None),
            priority=int(params.get("priority", 0) or 0),
        )
        return {
            "card_id": card["id"],
            "title": card["title"],
            "status": card["status"],
            "board_id": card["board_id"],
            "card": card,
        }

    def _kanban_list(self, params: dict) -> dict:
        cards = self._store.list_cards(
            board_id=str(params.get("board_id", "default") or "default"),
            status=(str(params["status"]) if params.get("status") else None),
            assignee=(str(params["assignee"]) if params.get("assignee") else None),
            include_archived=bool(params.get("include_archived", False)),
            limit=int(params.get("limit", 50) or 50),
        )
        return {
            "count": len(cards),
            "cards": [
                {
                    "card_id": c["id"],
                    "title": c["title"],
                    "status": c["status"],
                    "assignee": c.get("assignee"),
                    "priority": c.get("priority", 0),
                    "comment_count": c.get("comment_count", 0),
                }
                for c in cards
            ],
        }

    def _kanban_get(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        if not card_id:
            raise ValueError("card_id 不能为空")
        card = self._store.get_card(card_id)
        if card is None:
            raise KeyError(f"卡片不存在: {card_id}")
        return {"card": card}

    def _kanban_move(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        status = str(params.get("status", "")).strip()
        if not card_id or not status:
            raise ValueError("card_id 与 status 均必填")
        card = self._store.move_card(
            card_id,
            status,
            note=(str(params["note"]).strip() if params.get("note") else None),
        )
        return {"card_id": card_id, "status": status, "card": card}

    def _kanban_update(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        if not card_id:
            raise ValueError("card_id 不能为空")
        fields: dict[str, Any] = {}
        if params.get("title") is not None:
            fields["title"] = params["title"]
        if params.get("description") is not None:
            fields["description"] = params["description"]
        if params.get("assignee") is not None:
            fields["assignee"] = params["assignee"]
        if params.get("priority") is not None:
            fields["priority"] = params["priority"]
        card = self._store.update_card(card_id, **fields)
        return {"card_id": card_id, "card": card}

    def _kanban_comment(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        body = str(params.get("body", "")).strip()
        if not card_id:
            raise ValueError("card_id 不能为空")
        if not body:
            raise ValueError("评论内容不能为空")
        comment = self._store.add_comment(card_id, body, author=self._author())
        return {"card_id": card_id, "comment": comment}

    def _kanban_complete(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        summary = str(params.get("summary", "")).strip()
        if not card_id:
            raise ValueError("card_id 不能为空")
        card = self._store.move_card(card_id, "done", note="kanban_complete")
        if summary:
            self._store.add_comment(
                card_id, f"✅ 完成总结：{summary}", author=self._author()
            )
        return {"card_id": card_id, "status": "done", "card": card}

    def _kanban_delete(self, params: dict) -> dict:
        card_id = str(params.get("card_id", "")).strip()
        if not card_id:
            raise ValueError("card_id 不能为空")
        ok = self._store.delete_card(card_id)
        if not ok:
            raise KeyError(f"卡片不存在: {card_id}")
        return {"card_id": card_id, "deleted": True}


def create_handler(agent: "Agent"):
    """创建 Kanban Handler 处理函数（与系统 handler 统一命名惯例）"""
    handler = KanbanHandler(agent)
    return handler.handle


# 兼容别名：与 todo_handler.create_todo_handler 命名风格保持一致
create_kanban_handler = create_handler
