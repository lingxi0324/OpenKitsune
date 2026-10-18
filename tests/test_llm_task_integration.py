"""LLM 任务测试与推理测试（整改后真实推理引擎）。

目标：验证整改后的流程/推理逻辑在**真实 ReasoningEngine 推理循环**下
任务成功、推理正常无误：

- T1 纯文本任务：单轮 ``FINAL_ANSWER`` 决策，验证 reason→verify→finalize
  主路径收敛，任务完成（done 事件、exit_reason=normal、无 error）；
- T2 工具任务：两轮 ``TOOL_CALLS → FINAL_ANSWER``，验证
  reason→act→observe→reason→verify→finalize 全链路，工具真实执行、
  观察结果回传后再收敛；
- 推理路由：``route_decision`` 对全决策词汇映射正确（act/verify/finalize/reason）。

LLM 驱动方式：注入 ``_reason_stream_iter``（async generator 产出 Decision
事件）——与 ``tests/unit/test_model_transcript.py`` 同范式，保留引擎完整
循环（checkpoint/rollback/观察回环），仅替换 LLM 协议层。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from openkitsune.agent.reasoning import build_reasoning_graph
from openkitsune.core._reasoning_runtime import Decision, DecisionType, ReasoningEngine
from openkitsune.core.agent_state import AgentState

SYSTEM = "你是任务执行助手，用中文回复。"


def _make_context() -> Mock:
    context = Mock()
    context.estimate_messages_tokens.return_value = 0
    context.estimate_tools_tokens.return_value = 0
    context.get_max_context_tokens.return_value = 0
    context.compress_if_needed = AsyncMock(side_effect=lambda messages, **_: messages)
    context.calculate_context_pressure.return_value = SimpleNamespace(
        messages_tokens=0,
        system_tokens=0,
        tools_tokens=0,
        trigger_tokens=0,
        soft_limit=10000,
        hard_limit=12000,
        max_tokens=16000,
    )
    context.context_preparation_pending = False
    context.normalize_turn_roles = lambda messages, **_: messages
    context.drain_gap_kv_evict = AsyncMock()
    return context


def _make_tool_executor() -> SimpleNamespace:
    te = SimpleNamespace()
    te._current_mode = None
    te._agent_ref = None
    te.executed: list[tuple] = []

    def canonicalize_tool_name(name: str) -> str:
        return name

    async def execute_tool_with_policy(**kwargs: object) -> tuple[str, None]:
        te.executed.append((kwargs.get("tool_name"), kwargs.get("tool_input")))
        return ("工具执行结果：文件内容 ABC", None)

    te.canonicalize_tool_name = canonicalize_tool_name
    te.execute_tool_with_policy = execute_tool_with_policy
    return te


def _make_engine(respond, tool_executor: SimpleNamespace | None = None) -> ReasoningEngine:
    instance = ReasoningEngine(
        brain=SimpleNamespace(
            model="mock-model", max_tokens=4096, get_current_endpoint_info=lambda: {}
        ),
        tool_executor=tool_executor or _make_tool_executor(),
        context_manager=_make_context(),
        response_handler=Mock(),
        agent_state=AgentState(),
    )
    instance._save_react_trace = Mock()  # 轻量 trace 沉淀钩子
    instance._handle_final_answer = AsyncMock(return_value="可见的最终答复")
    instance._reason_stream_iter = respond
    return instance


async def _run_turn(engine: ReasoningEngine) -> list[dict]:
    # 每次运行使用唯一会话/轮次 ID：模型转写（model transcript）会持久化
    # 已完成 turn，固定 ID 会让第二次运行直接回放而非重跑推理循环。
    conv_id = f"llm-task-{uuid.uuid4().hex[:12]}"
    engine._state.begin_task(session_id=conv_id, conversation_id=conv_id)
    return [
        event
        async for event in engine.reason_stream(
            [{"role": "user", "content": "请读取 a.txt 并总结"}],
            tools=[],
            conversation_id=conv_id,
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            system_prompt=SYSTEM,
            base_system_prompt=SYSTEM,
            mode="agent",
            force_tool_retries=0,
        )
    ]


# ═══════════════════════════════════════════════════════════════
# T1 纯文本任务：单轮 FINAL_ANSWER，任务成功收敛
# ═══════════════════════════════════════════════════════════════


async def _respond_final_answer(messages: list[dict], **kwargs: object):
    yield {
        "type": "decision",
        "decision": Decision(
            type=DecisionType.FINAL_ANSWER,
            text_content="任务完成：a.txt 内容已总结。",
            assistant_content=[{"type": "text", "text": "任务完成：a.txt 内容已总结。"}],
            thinking_content="已完成推理，直接给出结论",
        ),
    }


@pytest.mark.asyncio
async def test_llm_text_task_completes_successfully() -> None:
    """LLM 任务测试：单轮最终答复，任务成功、推理正常收敛。"""
    engine = _make_engine(_respond_final_answer)
    events = await _run_turn(engine)

    # 任务成功：done 事件存在、无 error
    assert any(e["type"] == "done" for e in events), events
    assert not any(e["type"] == "error" for e in events), events

    # 推理正常：正常退出、产物已沉淀
    assert engine._last_exit_reason == "normal"
    assert engine._handle_final_answer.called  # finalize 阶段执行

    # 最终答复可见（_handle_final_answer 产物流化输出）
    assert any(
        e.get("type") == "text_delta" and "可见的最终答复" in e.get("content", "")
        for e in events
    )


# ═══════════════════════════════════════════════════════════════
# T2 工具任务：TOOL_CALLS → FINAL_ANSWER，全链路推理
# ═══════════════════════════════════════════════════════════════


def _tool_decision() -> Decision:
    return Decision(
        type=DecisionType.TOOL_CALLS,
        text_content="",
        tool_calls=[
            {"id": "call_1", "name": "read_file", "input": {"path": "a.txt"}}
        ],
        assistant_content=[{"type": "text", "text": "先读取文件"}],
        thinking_content="需要先读取文件再总结",
    )


def _final_decision() -> Decision:
    return Decision(
        type=DecisionType.FINAL_ANSWER,
        text_content="任务完成：a.txt 内容为 ABC。",
        assistant_content=[{"type": "text", "text": "任务完成：a.txt 内容为 ABC。"}],
        thinking_content="基于工具结果总结完成",
    )


def _has_tool_result(messages: list[dict]) -> bool:
    """工具结果以 content 列表中的 tool_result block（含 tool_use_id）回传。"""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            if any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in content
            ):
                return True
        elif isinstance(content, str) and "tool_result" in content:
            return True
    return False


def _make_tool_respond():
    """第一轮给工具决策，工具结果回传后的后续轮给最终答复。"""
    calls = {"n": 0}

    async def respond(messages: list[dict], **kwargs: object):
        calls["n"] += 1
        # 防御：异常路径不得死循环（正常最多两轮）
        if calls["n"] > 4:
            yield {"type": "decision", "decision": _final_decision()}
            return
        if _has_tool_result(messages):
            yield {"type": "decision", "decision": _final_decision()}
        else:
            yield {"type": "decision", "decision": _tool_decision()}

    return respond


@pytest.mark.asyncio
async def test_llm_tool_task_full_cycle() -> None:
    """推理测试：工具路径全链路（reason→act→observe→reason→verify→finalize）。"""
    tool_executor = _make_tool_executor()
    engine = _make_engine(_make_tool_respond(), tool_executor=tool_executor)
    events = await _run_turn(engine)

    # 任务成功
    assert any(e["type"] == "done" for e in events), events
    assert not any(e["type"] == "error" for e in events), events
    assert engine._last_exit_reason == "normal"

    # 工具真实执行一次，参数正确
    assert tool_executor.executed == [("read_file", {"path": "a.txt"})]

    # 工具调用过程可见（chain_text / tool_call_start）
    assert any(
        e.get("type") in ("chain_text", "tool_call_start") for e in events
    ), events

    # 两轮 LLM 决策都被消费（工具轮 + 最终轮）
    assert engine._handle_final_answer.called


# ═══════════════════════════════════════════════════════════════
# 推理路由：决策词汇 → 推理图节点
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reasoning_route_all_decisions() -> None:
    """推理路由：全决策词汇映射到正确节点（闭环/完备的运行时侧验证）。"""
    graph = build_reasoning_graph()

    async def route(kind: str) -> str | None:
        return await graph.route(
            "reason", SimpleNamespace(type=SimpleNamespace(value=kind))
        )

    # TOOL_CALLS → act；FINAL_ANSWER → verify；扩展退出码归位
    assert await route("tool_calls") == "act"
    assert await route("final_answer") == "verify"
    assert await route("tool_use") == "act"
    assert await route("ask_user") == "finalize"
    assert await route("continue") == "reason"
    assert await route("error") == "finalize"
    assert await route("max_iterations") == "finalize"
    assert await route("verify_incomplete") == "reason"


@pytest.mark.asyncio
async def test_verify_incomplete_loops_back_to_reason() -> None:
    """推理循环：验证未完成回环 reason（唯一回退路径）。"""
    graph = build_reasoning_graph()
    nxt = await graph.route(
        "verify",
        SimpleNamespace(type=SimpleNamespace(value="verify_incomplete")),
    )
    assert nxt == "reason"


# ═══════════════════════════════════════════════════════════════
# T3 制衡守卫·no_self_verify 运行时拦截
# 产出声明与验证声明同现（自证嫌疑）⇒ 不得直接终态，回推理重新决策
# ═══════════════════════════════════════════════════════════════


def _make_self_verify_respond():
    """第一轮给自证嫌疑的最终答复（产出+验证同现），被拦截后给正常答复。"""
    calls = {"n": 0}

    async def respond(messages: list[dict], **kwargs: object):
        calls["n"] += 1
        if calls["n"] > 4:
            yield {"type": "decision", "decision": _final_decision()}
            return
        # 第二轮起：消息里应已注入“自证嫌疑”回退提示
        joined = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                joined += " ".join(
                    str(b.get("text", "")) for b in c if isinstance(b, dict)
                )
            elif isinstance(c, str):
                joined += c
        if "自证嫌疑" in joined or calls["n"] > 1:
            yield {"type": "decision", "decision": _final_decision()}
            return
        yield {
            "type": "decision",
            "decision": Decision(
                type=DecisionType.FINAL_ANSWER,
                text_content="已实现功能并验证通过",
                assistant_content=[{"type": "text", "text": "已实现功能并验证通过"}],
                thinking_content="自证式答复",
            ),
        }

    return respond


@pytest.mark.asyncio
async def test_no_self_verify_intercepted_at_runtime() -> None:
    """制衡·运行时：自证嫌疑的最终答复被拦截回推理，重新决策后收敛。"""
    engine = _make_engine(_make_self_verify_respond())
    events = await _run_turn(engine)

    # 任务成功收敛（第二次决策为正常答复）
    assert any(e["type"] == "done" for e in events), events
    assert not any(e["type"] == "error" for e in events), events
    assert engine._last_exit_reason == "normal"

    # 自证拦截已生效：事件流出现回退提示，且 LLM 被要求重新决策（≥2 轮）
    assert any(
        e.get("type") == "chain_text" and "自证" in e.get("content", "")
        for e in events
    ), events
    assert engine._handle_final_answer.called


# ═══════════════════════════════════════════════════════════════
# T4 递生守卫·feedforward_complete 运行时拦截
# 空工具产物不可消费（失败结果放行）⇒ 转错误提示后让 LLM 重新决策
# ═══════════════════════════════════════════════════════════════


def _make_empty_result_executor() -> SimpleNamespace:
    """工具执行返回空产物（非失败）——递生约束应将其拦截。"""
    te = SimpleNamespace()
    te._current_mode = None
    te._agent_ref = None
    te.executed: list[tuple] = []

    def canonicalize_tool_name(name: str) -> str:
        return name

    async def execute_tool_with_policy(**kwargs: object) -> tuple[str, None]:
        te.executed.append((kwargs.get("tool_name"), kwargs.get("tool_input")))
        return ("", None)  # 空产物

    te.canonicalize_tool_name = canonicalize_tool_name
    te.execute_tool_with_policy = execute_tool_with_policy
    return te


def _make_empty_product_respond():
    """第一轮工具决策；看到空产物拦截提示后给正常答复。"""
    calls = {"n": 0}

    def _joined(messages: list[dict]) -> str:
        joined = ""
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                joined += " ".join(
                    str(b.get("content", "") or b.get("text", ""))
                    for b in c
                    if isinstance(b, dict)
                )
            elif isinstance(c, str):
                joined += c
        return joined

    async def respond(messages: list[dict], **kwargs: object):
        calls["n"] += 1
        if calls["n"] > 6:
            yield {"type": "decision", "decision": _final_decision()}
            return
        if _has_tool_result(messages) and "空产物" in _joined(messages):
            # 递生守卫生效：空产物已转错误提示，正常收尾
            yield {"type": "decision", "decision": _final_decision()}
            return
        # 未检测到拦截提示（守卫未生效）→ 继续工具决策
        yield {"type": "decision", "decision": _tool_decision()}

    return respond


@pytest.mark.asyncio
async def test_feedforward_empty_product_intercepted_at_runtime() -> None:
    """递生·运行时：空工具产物被拦截（转错误提示），LLM 重新决策后收敛。"""
    executor = _make_empty_result_executor()
    engine = _make_engine(_make_empty_product_respond(), tool_executor=executor)
    events = await _run_turn(engine)

    # 任务成功收敛
    assert any(e["type"] == "done" for e in events), events
    assert not any(e["type"] == "error" for e in events), events
    assert engine._last_exit_reason == "normal"

    # 工具真实执行一次；空产物被拦截为错误提示（LLM 看到了“空产物”说明）
    assert executor.executed == [("read_file", {"path": "a.txt"})]
    assert engine._handle_final_answer.called
