"""Persistent settings for cloud knowledge connectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openkitsune.utils.atomic_io import atomic_json_write, read_json_safe

CONFIG_VERSION = 3


def default_ima_config() -> dict[str, Any]:
    return {
        "configured": None,
        "enabled": False,
        "auto_retrieve": True,
        "prefer_knowledge": False,
        "knowledge_bases": [],
        "top_k": 5,
    }


def default_bailian_config() -> dict[str, Any]:
    return {
        "configured": None,
        "enabled": False,
        "auto_retrieve": True,
        "prefer_knowledge": False,
        "workspace_id": "",
        "agent_id": "",
        "service_name": "百炼知识检索",
        "region": "cn-beijing",
        "top_k": 5,
    }


def knowledge_config_path(project_root: Path | None = None) -> Path:
    if project_root is None:
        from openkitsune.config import settings

        project_root = Path(settings.project_root)
    return Path(project_root) / "data" / "knowledge_connectors.json"


def load_ima_config(path: Path | None = None) -> dict[str, Any]:
    raw = read_json_safe(path or knowledge_config_path()) or {}
    connector = (raw.get("connectors") or {}).get("tencent-ima") or {}
    if not isinstance(connector, dict):
        connector = {}

    knowledge_bases: list[dict[str, str]] = []
    for item in connector.get("knowledge_bases") or []:
        if not isinstance(item, dict):
            continue
        knowledge_base_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if knowledge_base_id:
            knowledge_bases.append({"id": knowledge_base_id, "name": name or knowledge_base_id})

    try:
        top_k = max(1, min(int(connector.get("top_k") or 5), 10))
    except (TypeError, ValueError):
        top_k = 5

    return {
        "configured": (bool(connector["configured"]) if "configured" in connector else None),
        "enabled": bool(connector.get("enabled", False)),
        "auto_retrieve": bool(connector.get("auto_retrieve", True)),
        "prefer_knowledge": bool(connector.get("prefer_knowledge", False)),
        "knowledge_bases": knowledge_bases,
        "top_k": top_k,
    }


def save_ima_config(config: dict[str, Any], path: Path | None = None) -> None:
    target = path or knowledge_config_path()
    existing = read_json_safe(target) or {}
    connectors = existing.get("connectors")
    if not isinstance(connectors, dict):
        connectors = {}
    configured = config.get("configured")
    if configured is None:
        previous = connectors.get("tencent-ima")
        if isinstance(previous, dict) and "configured" in previous:
            configured = bool(previous["configured"])
        else:
            configured = bool(config.get("knowledge_bases"))
    connectors["tencent-ima"] = {
        "configured": bool(configured),
        "enabled": bool(config.get("enabled", False)),
        "auto_retrieve": bool(config.get("auto_retrieve", True)),
        "prefer_knowledge": bool(config.get("prefer_knowledge", False)),
        "knowledge_bases": list(config.get("knowledge_bases") or []),
        "top_k": max(1, min(int(config.get("top_k") or 5), 10)),
    }
    existing["version"] = CONFIG_VERSION
    existing["connectors"] = connectors
    atomic_json_write(target, existing)


def load_bailian_config(path: Path | None = None) -> dict[str, Any]:
    raw = read_json_safe(path or knowledge_config_path()) or {}
    connector = (raw.get("connectors") or {}).get("aliyun-bailian") or {}
    if not isinstance(connector, dict):
        connector = {}
    try:
        top_k = max(1, min(int(connector.get("top_k") or 5), 20))
    except (TypeError, ValueError):
        top_k = 5
    region = str(connector.get("region") or "cn-beijing").strip()
    if region not in {"cn-beijing", "ap-southeast-1"}:
        region = "cn-beijing"
    agent_id = str(connector.get("agent_id") or "").strip()
    service_name = str(connector.get("service_name") or "百炼知识检索").strip()
    return {
        "configured": (bool(connector["configured"]) if "configured" in connector else None),
        "enabled": bool(connector.get("enabled", False)),
        "auto_retrieve": bool(connector.get("auto_retrieve", True)),
        "prefer_knowledge": bool(connector.get("prefer_knowledge", False)),
        "workspace_id": str(connector.get("workspace_id") or "").strip(),
        "agent_id": agent_id,
        "service_name": service_name or "百炼知识检索",
        "region": region,
        "knowledge_bases": ([{"id": agent_id, "name": service_name}] if agent_id else []),
        "top_k": top_k,
    }


def save_bailian_config(config: dict[str, Any], path: Path | None = None) -> None:
    target = path or knowledge_config_path()
    existing = read_json_safe(target) or {}
    connectors = existing.get("connectors")
    if not isinstance(connectors, dict):
        connectors = {}
    region = str(config.get("region") or "cn-beijing").strip()
    if region not in {"cn-beijing", "ap-southeast-1"}:
        region = "cn-beijing"
    configured = config.get("configured")
    if configured is None:
        previous = connectors.get("aliyun-bailian")
        if isinstance(previous, dict) and "configured" in previous:
            configured = bool(previous["configured"])
        else:
            configured = bool(config.get("workspace_id") and config.get("agent_id"))
    connectors["aliyun-bailian"] = {
        "configured": bool(configured),
        "enabled": bool(config.get("enabled", False)),
        "auto_retrieve": bool(config.get("auto_retrieve", True)),
        "prefer_knowledge": bool(config.get("prefer_knowledge", False)),
        "workspace_id": str(config.get("workspace_id") or "").strip(),
        "agent_id": str(config.get("agent_id") or "").strip(),
        "service_name": str(config.get("service_name") or "百炼知识检索").strip(),
        "region": region,
        "top_k": max(1, min(int(config.get("top_k") or 5), 20)),
    }
    existing["version"] = CONFIG_VERSION
    existing["connectors"] = connectors
    atomic_json_write(target, existing)


def load_knowledge_configs(path: Path | None = None) -> list[dict[str, Any]]:
    ima = {"provider": "tencent-ima", **load_ima_config(path)}
    bailian = {"provider": "aliyun-bailian", **load_bailian_config(path)}
    return [ima, bailian]
