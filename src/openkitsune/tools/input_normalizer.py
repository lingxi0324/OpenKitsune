"""Schema-driven normalization for tool inputs."""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from .definitions import get_tool_input_schema

logger = logging.getLogger(__name__)


def normalize_tool_input(
    tool_name: str,
    params: Any,
    *,
    schema: dict | None = None,
) -> Any:
    """Normalize a tool input payload using its JSON schema."""
    tool_schema = schema if isinstance(schema, dict) else get_tool_input_schema(tool_name)
    if not tool_schema:
        return params
    # 非 dict 输入（位置参数 list / 字符串 JSON）→ 先按 schema 映射为 dict
    if not isinstance(params, dict):
        params = _map_positional_input(params, tool_schema, path=tool_name)
    # 文本解析器无法映射时留下的 raw_args → 兜底重解析（最后防线）
    if isinstance(params, dict) and isinstance(params.get("raw_args"), str):
        params = _resolve_raw_args(tool_name, params, tool_schema)
    if not isinstance(params, dict):
        return params
    normalized = _normalize_value(params, tool_schema, path=tool_name)
    normalized = _normalize_browser_tool_input(tool_name, normalized)
    normalized = _normalize_plan_tool_input(tool_name, normalized)
    return _normalize_shell_tool_input(tool_name, normalized)


def _positional_order(schema: dict) -> list[str]:
    """Declared positional order for a schema: ``required`` first, then the
    remaining ``properties`` keys in declaration order."""
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return []
    required = schema.get("required")
    if isinstance(required, list):
        order = [key for key in required if key in properties]
        order.extend(key for key in properties if key not in order)
        return order
    return list(properties.keys())


def _map_positional_input(value: Any, schema: dict, *, path: str) -> Any:
    """Map a non-dict tool input (positional list, or JSON string of a list)
    onto the schema's declared parameters. Returns a dict when mapping is
    possible; otherwise returns the original value so the handler layer can
    produce a guided error instead of raising AttributeError."""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return value
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return value
        value = parsed
    if not isinstance(value, list):
        return value

    order = _positional_order(schema)
    if not order or len(value) > len(order):
        return value

    mapped: dict[str, Any] = {}
    for index, item in enumerate(value):
        mapped[order[index]] = item
    logger.debug("[ToolInput] Mapped %d positional args for %s", len(mapped), path)
    return mapped


def _resolve_raw_args(tool_name: str, params: dict[str, Any], schema: dict) -> dict[str, Any]:
    """Re-parse a ``raw_args`` payload left behind by text parsers that could
    not map positional arguments (e.g. when no schema was known at parse time).

    Only rewrites ``params`` when the payload actually parses as a Python
    call and yields at least one schema-known key — otherwise keeps the
    original dict so the handler's guided error survives.
    """
    raw = str(params.get("raw_args") or "").strip()
    if not raw:
        return params
    try:
        import ast

        tree = ast.parse(f"_f({raw})", mode="eval")
        call_node = tree.body
        if not isinstance(call_node, ast.Call):
            return params
    except (SyntaxError, ValueError, TypeError):
        return params

    order = _positional_order(schema)
    result = dict(params)
    result.pop("raw_args", None)
    gained = 0
    for index, node in enumerate(call_node.args):
        if index >= len(order):
            break
        key = order[index]
        if key in result:
            continue
        try:
            result[key] = ast.literal_eval(node)
        except (ValueError, TypeError):
            result[key] = ast.unparse(node)
        gained += 1
    for kw in call_node.keywords:
        if kw.arg is None or kw.arg in result or kw.arg == "raw_args":
            continue
        try:
            result[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, TypeError):
            result[kw.arg] = ast.unparse(kw.value)
        gained += 1

    if gained == 0:
        return params
    logger.debug("[ToolInput] Recovered %d arg(s) from raw_args for %s", gained, tool_name)
    return result


def _normalize_browser_tool_input(tool_name: str, params: Any) -> Any:
    if not isinstance(params, dict):
        return params
    if tool_name == "browser_type":
        return _normalize_browser_type_input(params)
    if tool_name == "browser_click":
        return _normalize_browser_click_input(params)
    return params


def _normalize_shell_tool_input(tool_name: str, params: Any) -> Any:
    if tool_name != "run_shell" or not isinstance(params, dict):
        return params
    if params.get("block_timeout_ms") is not None or params.get("timeout") is not None:
        return params

    normalized = dict(params)
    try:
        from ..config import settings

        normalized["block_timeout_ms"] = int(
            getattr(settings, "run_shell_default_block_timeout_ms", 30000) or 0
        )
    except Exception:
        normalized["block_timeout_ms"] = 30000
    return normalized


def _normalize_plan_tool_input(tool_name: str, params: Any) -> Any:
    if tool_name != "create_plan_file" or not isinstance(params, dict):
        return params
    normalized = dict(params)
    if not normalized.get("body"):
        body = _first_present(normalized, "content", "markdown", "plan_content")
        if body is not None:
            normalized["body"] = body
    if not normalized.get("name"):
        name = _first_present(normalized, "plan_name", "title", "plan_title")
        if name is not None:
            normalized["name"] = name
    if not normalized.get("todos"):
        steps = _first_present(normalized, "steps", "items")
        if steps is not None:
            normalized["todos"] = _normalize_plan_steps(steps)
    return normalized


def _normalize_plan_steps(steps: Any) -> Any:
    if isinstance(steps, str):
        try:
            parsed = json.loads(steps)
            steps = parsed
        except json.JSONDecodeError:
            return steps
    if not isinstance(steps, list):
        return steps
    normalized_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(steps, start=1):
        if isinstance(step, str):
            content = step.strip()
            if content:
                normalized_steps.append({"id": f"step_{idx}", "content": content})
            continue
        if not isinstance(step, dict):
            continue
        content = _first_present(step, "content", "description", "task", "title")
        if not content:
            continue
        normalized_steps.append(
            {
                "id": step.get("id") or f"step_{idx}",
                "content": str(content),
                "status": step.get("status", "pending"),
            }
        )
    return normalized_steps


def _normalize_browser_type_input(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)

    if not normalized.get("text"):
        text = _first_present(
            normalized,
            "value",
            "input",
            "content",
            "typed_text",
            "text_to_type",
        )
        if text is not None:
            normalized["text"] = text

    if not normalized.get("selector"):
        selector = _first_present(normalized, "locator", "css", "query", "target_selector")
        if selector is None:
            selector = _selector_for_field(
                _first_present(normalized, "field", "name", "target", "label")
            )
        if selector is not None:
            normalized["selector"] = selector

    if isinstance(normalized.get("clear"), str):
        normalized["clear"] = normalized["clear"].strip().lower() not in {"false", "0", "no"}

    return normalized


def _normalize_browser_click_input(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)

    if not normalized.get("selector"):
        selector = _first_present(normalized, "locator", "css", "query", "target_selector")
        if selector is not None:
            normalized["selector"] = selector

    if not normalized.get("selector") and not normalized.get("text"):
        target = _first_present(normalized, "target", "label", "name")
        if isinstance(target, str) and target.strip():
            normalized["text"] = target

    if not normalized.get("selector") and not normalized.get("text"):
        action = str(normalized.get("action") or "").strip().lower()
        if action in {"submit", "login", "sign_in", "signin"}:
            normalized["selector"] = (
                'button[type="submit"], input[type="submit"], '
                'button:has-text("登录"), button:has-text("Login")'
            )

    return normalized


def _first_present(params: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = params.get(key)
        if value is not None and value != "":
            return value
    return None


def _selector_for_field(field: Any) -> str | None:
    value = str(field or "").strip().lower()
    if not value:
        return None
    if value in {"username", "user", "account", "login", "用户名", "账号", "账户"}:
        return (
            'input[name="username"], input[name="luci_username"], '
            'input[name="user"], #username, #luci_username, input[type="text"]'
        )
    if value in {"password", "pass", "pwd", "密码"}:
        return (
            'input[type="password"], input[name="password"], '
            'input[name="luci_password"], #password, #luci_password'
        )
    return None


def _normalize_value(value: Any, schema: dict | None, *, path: str) -> Any:
    if not isinstance(schema, dict) or not schema:
        return value

    schema_type = _infer_schema_type(schema)
    if schema_type == "object":
        return _normalize_object(value, schema, path=path)
    if schema_type == "array":
        return _normalize_array(value, schema, path=path)
    return _normalize_scalar(value, schema_type, path=path)


def _normalize_object(value: Any, schema: dict, *, path: str) -> Any:
    value = _maybe_parse_structured_string(value, expected_type="object", path=path)
    if not isinstance(value, dict):
        return value

    properties = schema.get("properties")
    additional = schema.get("additionalProperties")
    if not isinstance(properties, dict) and not isinstance(additional, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        child_schema = properties.get(key) if isinstance(properties, dict) else None
        if child_schema is None and isinstance(additional, dict):
            child_schema = additional
        normalized[key] = _normalize_value(item, child_schema, path=f"{path}.{key}")
    return normalized


def _normalize_array(value: Any, schema: dict, *, path: str) -> Any:
    value = _maybe_parse_structured_string(value, expected_type="array", path=path)
    if not isinstance(value, list):
        return value

    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return value

    return [
        _normalize_value(item, item_schema, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    ]


def _maybe_parse_structured_string(value: Any, *, expected_type: str, path: str) -> Any:
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    if expected_type == "object" and not raw.startswith("{"):
        return value
    if expected_type == "array" and not raw.startswith("["):
        return value

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return value

    if expected_type == "object" and isinstance(parsed, dict):
        logger.debug("[ToolInput] Parsed stringified object at %s", path)
        return parsed
    if expected_type == "array" and isinstance(parsed, list):
        logger.debug("[ToolInput] Parsed stringified array at %s", path)
        return parsed
    return value


def _normalize_scalar(value: Any, schema_type: str | None, *, path: str) -> Any:
    if schema_type == "number":
        return _coerce_number(value, path=path)
    if schema_type == "integer":
        return _coerce_integer(value, path=path)
    if schema_type == "boolean":
        return _coerce_boolean(value, path=path)
    return value


def _coerce_number(value: Any, *, path: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value
    try:
        parsed = float(raw)
    except ValueError:
        return value
    if not math.isfinite(parsed):
        return value
    logger.debug("[ToolInput] Parsed stringified number at %s", path)
    return parsed


def _coerce_integer(value: Any, *, path: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value
    try:
        parsed = float(raw)
    except ValueError:
        return value
    if not math.isfinite(parsed) or not parsed.is_integer():
        return value
    logger.debug("[ToolInput] Parsed stringified integer at %s", path)
    return int(parsed)


def _coerce_boolean(value: Any, *, path: str) -> Any:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return value

    raw = value.strip().lower()
    if raw in {"true", "1", "yes", "y", "on"}:
        logger.debug("[ToolInput] Parsed stringified boolean at %s", path)
        return True
    if raw in {"false", "0", "no", "n", "off"}:
        logger.debug("[ToolInput] Parsed stringified boolean at %s", path)
        return False
    return value


def _infer_schema_type(schema: dict) -> str | None:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        if "object" in schema_type:
            return "object"
        if "array" in schema_type:
            return "array"
        for scalar_type in ("integer", "number", "boolean", "string"):
            if scalar_type in schema_type:
                return scalar_type
        return None
    if isinstance(schema_type, str):
        return schema_type
    if "properties" in schema or isinstance(schema.get("additionalProperties"), dict):
        return "object"
    if "items" in schema:
        return "array"
    return None
