"""Cloud knowledge-base connection routes."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openkitsune.integrations.knowledge import (
    BAILIAN_REGIONS,
    BailianAPIError,
    BailianClient,
    IMAAPIError,
    IMAClient,
    knowledge_config_path,
    load_bailian_config,
    load_ima_config,
    save_bailian_config,
    save_ima_config,
)
from openkitsune.utils.env_config import update_env_file

router = APIRouter(prefix="/api/knowledge")


class IMACredentialsRequest(BaseModel):
    client_id: str = Field(default="", max_length=512)
    api_key: str = Field(default="", max_length=2048)


class IMASearchRequest(IMACredentialsRequest):
    knowledge_base_id: str = Field(min_length=1, max_length=512)
    query: str = Field(min_length=1, max_length=500)


class KnowledgeBaseSelection(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    name: str = Field(min_length=1, max_length=512)


class IMAConfigRequest(IMACredentialsRequest):
    enabled: bool = True
    auto_retrieve: bool = True
    prefer_knowledge: bool = False
    knowledge_bases: list[KnowledgeBaseSelection] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=5, ge=1, le=10)


class BailianCredentialsRequest(BaseModel):
    api_key: str = Field(default="", max_length=2048)
    workspace_id: str = Field(default="", max_length=512)
    agent_id: str = Field(default="", max_length=512)
    region: str = Field(default="cn-beijing", max_length=64)
    service_name: str = Field(default="百炼知识检索", max_length=512)


class BailianConfigRequest(BailianCredentialsRequest):
    enabled: bool = True
    auto_retrieve: bool = True
    prefer_knowledge: bool = False
    top_k: int = Field(default=5, ge=1, le=20)


class BailianSearchRequest(BailianCredentialsRequest):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


def _project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root)
    except Exception:
        return Path.cwd()


def _ima_config_path() -> Path:
    return knowledge_config_path(_project_root())


def _resolve_ima_credentials(body: IMACredentialsRequest) -> tuple[str, str]:
    client_id = body.client_id.strip() or os.environ.get("IMA_OPENAPI_CLIENTID", "").strip()
    api_key = body.api_key.strip() or os.environ.get("IMA_OPENAPI_APIKEY", "").strip()
    return client_id, api_key


def _resolve_bailian_connection(
    body: BailianCredentialsRequest,
) -> tuple[str, str, str, str, str]:
    saved = load_bailian_config(_ima_config_path())
    api_key = (
        body.api_key.strip()
        or os.environ.get("BAILIAN_KNOWLEDGE_API_KEY", "").strip()
        or os.environ.get("DASHSCOPE_API_KEY", "").strip()
    )
    workspace_id = body.workspace_id.strip() or saved["workspace_id"]
    agent_id = body.agent_id.strip() or saved["agent_id"]
    region = body.region.strip() or saved["region"]
    service_name = body.service_name.strip() or saved["service_name"]
    if region not in BAILIAN_REGIONS:
        raise HTTPException(status_code=400, detail="不支持的百炼地域")
    return workspace_id, api_key, agent_id, region, service_name


@router.get("/connectors")
async def list_knowledge_connectors() -> dict:
    ima_credentials_available = bool(
        os.environ.get("IMA_OPENAPI_CLIENTID", "").strip()
        and os.environ.get("IMA_OPENAPI_APIKEY", "").strip()
    )
    connector_config = load_ima_config(_ima_config_path())
    ima_configured = ima_credentials_available and connector_config["configured"] is not False
    bailian_config = load_bailian_config(_ima_config_path())
    bailian_credentials_available = bool(
        (
            os.environ.get("BAILIAN_KNOWLEDGE_API_KEY", "").strip()
            or os.environ.get("DASHSCOPE_API_KEY", "").strip()
        )
        and bailian_config["workspace_id"]
        and bailian_config["agent_id"]
    )
    bailian_configured = bailian_credentials_available and bailian_config["configured"] is not False
    return {
        "connectors": [
            {
                "id": "tencent-ima",
                "name": "腾讯 ima",
                "status": "configured" if ima_configured else "available",
                "configured": ima_configured,
                "enabled": ima_configured and connector_config["enabled"],
                "auto_retrieve": connector_config["auto_retrieve"],
                "prefer_knowledge": connector_config["prefer_knowledge"],
                "knowledge_bases": connector_config["knowledge_bases"],
                "top_k": connector_config["top_k"],
                "capabilities": ["search", "browse", "read"],
            },
            {
                "id": "aliyun-bailian",
                "name": "阿里云百炼",
                "status": "configured" if bailian_configured else "available",
                "configured": bailian_configured,
                "enabled": bailian_configured and bailian_config["enabled"],
                "auto_retrieve": bailian_config["auto_retrieve"],
                "prefer_knowledge": bailian_config["prefer_knowledge"],
                "knowledge_bases": bailian_config["knowledge_bases"],
                "top_k": bailian_config["top_k"],
                "capabilities": ["semantic_search", "read_matched_content"],
                "workspace_id": bailian_config["workspace_id"],
                "agent_id": bailian_config["agent_id"],
                "service_name": bailian_config["service_name"],
                "region": bailian_config["region"],
            },
        ]
    }


@router.post("/ima/validate")
async def validate_ima_connection(body: IMACredentialsRequest) -> dict:
    """Validate credentials and return a small, non-sensitive knowledge-base list."""
    client_id, api_key = _resolve_ima_credentials(body)
    started = time.perf_counter()
    try:
        knowledge_bases = await IMAClient(client_id, api_key).list_addable_knowledge_bases()
    except IMAAPIError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "message": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "message": "ima 连接验证成功",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "knowledge_bases": knowledge_bases,
    }


@router.put("/ima/config")
async def configure_ima_connection(body: IMAConfigRequest) -> dict:
    """Validate and persist an ima connection and its retrieval scope."""
    if body.enabled and not body.knowledge_bases:
        raise HTTPException(status_code=400, detail="请至少选择一个知识库")

    current = load_ima_config(_ima_config_path())
    client_id, api_key = _resolve_ima_credentials(body)
    requested = [
        {"id": item.id.strip(), "name": item.name.strip()} for item in body.knowledge_bases
    ]
    if body.enabled:
        try:
            available = await IMAClient(client_id, api_key).list_addable_knowledge_bases()
        except IMAAPIError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": exc.code, "message": str(exc)},
            ) from exc

        available_by_id = {item["id"]: item for item in available}
        selected_ids = [item["id"] for item in requested]
        unknown_ids = [item for item in selected_ids if item not in available_by_id]
        if unknown_ids:
            raise HTTPException(status_code=400, detail="所选知识库已不可用，请刷新后重试")
        selected = [available_by_id[item] for item in selected_ids]
    else:
        # Disabling is local-only and must still work when the remote service
        # or saved credentials are temporarily unavailable.
        selected = requested or current["knowledge_bases"]
    entries = {}
    if body.client_id.strip():
        entries["IMA_OPENAPI_CLIENTID"] = body.client_id.strip()
    if body.api_key.strip():
        entries["IMA_OPENAPI_APIKEY"] = body.api_key.strip()
    if entries:
        update_env_file(_project_root() / ".env", entries=entries)
        os.environ.update(entries)

    config = {
        "configured": bool(client_id and api_key),
        "enabled": body.enabled,
        "auto_retrieve": body.auto_retrieve,
        "prefer_knowledge": body.prefer_knowledge,
        "knowledge_bases": selected,
        "top_k": body.top_k,
    }
    save_ima_config(config, _ima_config_path())
    return {
        "ok": True,
        "message": "腾讯 ima 知识库已保存",
        "enabled": body.enabled,
        "auto_retrieve": body.auto_retrieve,
        "prefer_knowledge": body.prefer_knowledge,
        "knowledge_bases": selected,
        "top_k": body.top_k,
    }


@router.delete("/ima/config")
async def disconnect_ima() -> dict:
    """Remove the saved ima connection."""
    save_ima_config(
        {
            "configured": False,
            "enabled": False,
            "auto_retrieve": True,
            "prefer_knowledge": False,
            "knowledge_bases": [],
            "top_k": 5,
        },
        _ima_config_path(),
    )
    credential_keys = {"IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY"}
    update_env_file(_project_root() / ".env", entries={}, delete_keys=credential_keys)
    for key in credential_keys:
        os.environ.pop(key, None)
    return {"ok": True, "message": "腾讯 ima 连接已移除"}


@router.post("/ima/search")
async def search_ima_knowledge(body: IMASearchRequest) -> dict:
    """Search one ima knowledge base."""
    client_id, api_key = _resolve_ima_credentials(body)
    started = time.perf_counter()
    try:
        results = await IMAClient(client_id, api_key).search_knowledge(
            knowledge_base_id=body.knowledge_base_id,
            query=body.query,
        )
    except IMAAPIError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "message": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "message": "搜索完成",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
    }


@router.post("/bailian/validate")
async def validate_bailian_connection(body: BailianCredentialsRequest) -> dict:
    """Validate a published Bailian retrieval service with a read-only query."""
    workspace_id, api_key, agent_id, region, service_name = _resolve_bailian_connection(body)
    started = time.perf_counter()
    try:
        await BailianClient(workspace_id, api_key, agent_id, region=region).search(
            "OpenKitsune 连接测试", limit=1
        )
    except BailianAPIError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "message": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "message": "阿里云百炼连接验证成功",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "knowledge_bases": [{"id": agent_id, "name": service_name}],
    }


@router.put("/bailian/config")
async def configure_bailian_connection(body: BailianConfigRequest) -> dict:
    """Validate and persist a Bailian retrieval service."""
    workspace_id, api_key, agent_id, region, service_name = _resolve_bailian_connection(body)
    if body.enabled and (not workspace_id or not agent_id or not api_key):
        raise HTTPException(status_code=400, detail="请填写业务空间、检索服务和 API Key")
    if body.enabled:
        try:
            await BailianClient(workspace_id, api_key, agent_id, region=region).search(
                "OpenKitsune 连接测试", limit=1
            )
        except BailianAPIError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": exc.code, "message": str(exc)},
            ) from exc

    if body.api_key.strip():
        entries = {"BAILIAN_KNOWLEDGE_API_KEY": body.api_key.strip()}
        update_env_file(_project_root() / ".env", entries=entries)
        os.environ.update(entries)
    config = {
        "configured": bool(workspace_id and agent_id and api_key),
        "enabled": body.enabled,
        "auto_retrieve": body.auto_retrieve,
        "prefer_knowledge": body.prefer_knowledge,
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "service_name": service_name,
        "region": region,
        "top_k": body.top_k,
    }
    save_bailian_config(config, _ima_config_path())
    return {
        "ok": True,
        "message": "阿里云百炼知识库已保存",
        **config,
        "knowledge_bases": [{"id": agent_id, "name": service_name}],
    }


@router.delete("/bailian/config")
async def disconnect_bailian() -> dict:
    """Remove the saved Bailian retrieval connection."""
    save_bailian_config(
        {
            "configured": False,
            "enabled": False,
            "auto_retrieve": True,
            "prefer_knowledge": False,
            "workspace_id": "",
            "agent_id": "",
            "service_name": "百炼知识检索",
            "region": "cn-beijing",
            "top_k": 5,
        },
        _ima_config_path(),
    )
    credential_keys = {"BAILIAN_KNOWLEDGE_API_KEY"}
    update_env_file(_project_root() / ".env", entries={}, delete_keys=credential_keys)
    for key in credential_keys:
        os.environ.pop(key, None)
    return {"ok": True, "message": "阿里云百炼连接已移除"}


@router.post("/bailian/search")
async def search_bailian_knowledge(body: BailianSearchRequest) -> dict:
    """Search a configured Bailian retrieval service."""
    workspace_id, api_key, agent_id, region, _ = _resolve_bailian_connection(body)
    started = time.perf_counter()
    try:
        results = await BailianClient(workspace_id, api_key, agent_id, region=region).search(
            body.query, limit=body.limit
        )
    except BailianAPIError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "message": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return {
        "ok": True,
        "message": "搜索完成",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
    }
