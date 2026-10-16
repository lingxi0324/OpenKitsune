"""
计划看板（Kanban）HTTP API

对标 Hermes ``kanban.db`` 看板在桌面面板中的呈现，为 OpenKitsune 桌面
前端提供看板数据接口：

- ``GET /api/kanban/workflow``    列定义与移动矩阵（前端渲染列）
- ``GET /api/kanban/boards``      看板列表
- ``POST /api/kanban/boards``     创建看板
- ``GET /api/kanban/cards``       卡片列表（board/status/assignee/归档过滤）
- ``POST /api/kanban/cards``      创建卡片
- ``GET /api/kanban/cards/{id}``  卡片详情（含评论与活动流）
- ``PATCH /api/kanban/cards/{id}`` 更新标题/描述/负责人/优先级
- ``POST /api/kanban/cards/{id}/move`` 状态流转（拖拽/菜单移动）
- ``DELETE /api/kanban/cards/{id}`` 物理删除
- ``POST /api/kanban/cards/{id}/comments`` 添加评论
- ``GET /api/kanban/stats``       各列统计
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from openkitsune.kanban.store import get_kanban_store

logger = logging.getLogger(__name__)

router = APIRouter()


def _notify_kanban_change(action: str = "update") -> None:
    """Fire-and-forget WS 广播：前端订阅后即时刷新。"""
    try:
        from openkitsune.api.routes.websocket import broadcast_event

        asyncio.ensure_future(broadcast_event("kanban:change", {"action": action}))
    except Exception:
        pass


class BoardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class CardCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    board_id: str = "default"
    status: str = "todo"
    assignee: str | None = None
    priority: int = 0


class CardUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    assignee: str | None = None
    priority: int | None = None


class CardMoveRequest(BaseModel):
    status: str
    note: str | None = None


class CommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    author: str | None = None


def _err(message: str, code: int = 400) -> dict[str, Any]:
    return {"error": message}


@router.get("/api/kanban/workflow")
async def get_workflow():
    return get_kanban_store().workflow()


@router.get("/api/kanban/boards")
async def list_boards():
    try:
        return {"boards": get_kanban_store().list_boards()}
    except Exception as exc:
        logger.exception("kanban list_boards failed")
        return _err(str(exc))


@router.post("/api/kanban/boards")
async def create_board(body: BoardCreateRequest):
    try:
        return get_kanban_store().create_board(body.name)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban create_board failed")
        return _err(str(exc))


@router.get("/api/kanban/cards")
async def list_cards(
    board_id: str = "default",
    status: str | None = None,
    assignee: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
):
    try:
        cards = get_kanban_store().list_cards(
            board_id=board_id,
            status=status,
            assignee=assignee,
            include_archived=include_archived,
            limit=limit,
        )
        return {"cards": cards}
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban list_cards failed")
        return _err(str(exc))


@router.post("/api/kanban/cards")
async def create_card(body: CardCreateRequest):
    try:
        card = get_kanban_store().create_card(
            title=body.title,
            description=body.description,
            board_id=body.board_id,
            status=body.status,
            assignee=body.assignee,
            priority=body.priority,
        )
        _notify_kanban_change("create")
        return card
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban create_card failed")
        return _err(str(exc))


@router.get("/api/kanban/cards/{card_id}")
async def get_card(card_id: str):
    card = get_kanban_store().get_card(card_id)
    if card is None:
        return _err(f"卡片不存在: {card_id}", 404)
    return card


@router.patch("/api/kanban/cards/{card_id}")
async def update_card(card_id: str, body: CardUpdateRequest):
    try:
        fields = body.model_dump(exclude_none=True)
        card = get_kanban_store().update_card(card_id, **fields)
        _notify_kanban_change("update")
        return card
    except KeyError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban update_card failed")
        return _err(str(exc))


@router.post("/api/kanban/cards/{card_id}/move")
async def move_card(card_id: str, body: CardMoveRequest):
    try:
        card = get_kanban_store().move_card(card_id, body.status, note=body.note)
        _notify_kanban_change("move")
        return card
    except KeyError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban move_card failed")
        return _err(str(exc))


@router.delete("/api/kanban/cards/{card_id}")
async def delete_card(card_id: str):
    try:
        ok = get_kanban_store().delete_card(card_id)
        if not ok:
            return _err(f"卡片不存在: {card_id}", 404)
        _notify_kanban_change("delete")
        return {"ok": True}
    except Exception as exc:
        logger.exception("kanban delete_card failed")
        return _err(str(exc))


@router.post("/api/kanban/cards/{card_id}/comments")
async def add_comment(card_id: str, body: CommentCreateRequest):
    try:
        comment = get_kanban_store().add_comment(card_id, body.body, author=body.author or "user")
        _notify_kanban_change("comment")
        return comment
    except KeyError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:
        logger.exception("kanban add_comment failed")
        return _err(str(exc))


@router.get("/api/kanban/stats")
async def kanban_stats(board_id: str = "default"):
    try:
        return get_kanban_store().stats(board_id)
    except Exception as exc:
        logger.exception("kanban stats failed")
        return _err(str(exc))
