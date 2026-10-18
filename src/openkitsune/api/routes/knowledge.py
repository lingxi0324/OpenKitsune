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


# ---------------------------------------------------------------------------
# Local knowledge-base (lynzie document library + knowledge graph)
# Contract: temp/kb_integration_contract.md — frozen, do not rename fields.
# ---------------------------------------------------------------------------

from openkitsune.knowledge import local_kb  # noqa: E402


class LocalKBRootRequest(BaseModel):
    root: str = Field(min_length=1, max_length=1024)


class LocalKBScanRequest(BaseModel):
    refresh: bool = False


class LocalKBSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)
    include_body: bool = False


def _local_guard(exc: local_kb.LocalKBError) -> HTTPException:
    return HTTPException(status_code=400, detail=exc.message)


@router.get("/local/config")
async def get_local_kb_config() -> dict:
    return local_kb.config_status()


@router.put("/local/config")
async def put_local_kb_config(body: LocalKBRootRequest) -> dict:
    try:
        local_kb.persist_root(body.root)
    except local_kb.LocalKBError as exc:
        raise _local_guard(exc) from exc
    return local_kb.config_status()


@router.post("/local/scan")
async def scan_local_knowledge(body: LocalKBScanRequest) -> dict:
    started = time.perf_counter()
    if body.refresh or local_kb.load_cache() is None:
        result = local_kb.scan(local_kb.resolve_root())
        local_kb.save_cache(result)
        stats = result["stats"]
        duration_ms = stats["duration_ms"]
    else:
        cached = local_kb.load_cache() or {}
        stats = cached.get("stats") or {}
        duration_ms = round((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "message": "本地知识库扫描完成",
        "duration_ms": duration_ms,
        "stats": {
            "total_files": stats.get("total_files", 0),
            "indexed_files": stats.get("indexed_files", 0),
            "dirs": stats.get("dirs", 0),
            "meta_files": stats.get("meta_files", 0),
            "skipped": stats.get("skipped", 0),
            "failed": stats.get("failed", []),
        },
    }


@router.get("/local/browse")
async def browse_local_knowledge(
    path: str = "", limit: int = 200
) -> dict:
    try:
        return local_kb.browse(path or None, limit=limit)
    except local_kb.LocalKBError as exc:
        raise _local_guard(exc) from exc


@router.get("/local/doc")
async def read_local_knowledge_doc(path: str) -> dict:
    try:
        return local_kb.read_doc(path)
    except local_kb.LocalKBError as exc:
        raise _local_guard(exc) from exc


@router.post("/local/search")
async def search_local_knowledge(body: LocalKBSearchRequest) -> dict:
    return local_kb.search(
        body.query, limit=body.limit, include_body=body.include_body
    )


@router.get("/local/graph")
async def local_knowledge_graph(
    limit: int = 600, category: str = "all", q: str | None = None
) -> dict:
    return local_kb.graph(limit=limit, category=category, q=q)


# ---------------------------------------------------------------------------
# Document parsing & AI learning (port of CM-agentic documentParse +
# dynamic-graph learning engine)
# ---------------------------------------------------------------------------

from openkitsune.knowledge import learning  # noqa: E402
from openkitsune.knowledge.parsers import (  # noqa: E402
    FileTooLarge,
    MissingDependency,
    ParseError,
    UnsupportedFormat,
    parse_document,
)


class LocalParseRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    format: str = Field(default="text", pattern="^(text|json)$")
    max_chars: int = Field(default=8000, ge=100, le=50000)
    ocr_max_pages: int | None = Field(default=None, ge=1, le=200)


@router.post("/local/parse")
async def parse_local_document(body: LocalParseRequest) -> dict:
    """Parse a PDF / Word / Excel / CSV document inside the knowledge root.

    Scanned PDFs (no text layer) are OCR'd automatically; ``ocr_max_pages``
    caps how many pages are rendered for long scanned documents.
    """
    started = time.perf_counter()
    try:
        root = local_kb.resolve_root()
        target = local_kb.resolve_safe(root, body.path)
    except local_kb.LocalKBError as exc:
        raise _local_guard(exc) from exc
    try:
        parsed = parse_document(target, ocr_max_pages=body.ocr_max_pages)
    except FileTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UnsupportedFormat as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except MissingDependency as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = parsed.render_json() if body.format == "json" else parsed.render_text(body.max_chars)
    return {
        "ok": True,
        "path": body.path,
        "format": parsed.format,
        "metadata": parsed.metadata,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "content": payload,
    }


class LocalOCRRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    dpi: int = Field(default=150, ge=72, le=300)
    max_pages: int | None = Field(default=None, ge=1, le=200)


@router.post("/local/ocr")
async def ocr_local_document(body: LocalOCRRequest) -> dict:
    """Explicitly OCR a scanned PDF or image inside the knowledge root."""
    from openkitsune.knowledge import ocr

    try:
        root = local_kb.resolve_root()
        target = local_kb.resolve_safe(root, body.path)
    except local_kb.LocalKBError as exc:
        raise _local_guard(exc) from exc
    started = time.perf_counter()
    suffix = target.suffix.lower()
    if suffix == ".pdf":
        result = ocr.extract_pdf_text(target, dpi=body.dpi, max_pages=body.max_pages or ocr.MAX_PAGES)
    elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        result = ocr.extract_image_text(target)
    else:
        raise HTTPException(status_code=415, detail=f"OCR 仅支持 PDF / 图片，当前: {suffix}")
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error") or "OCR 失败")
    return {
        "ok": True,
        "path": body.path,
        "cached": result.get("cached", False),
        "pages": result.get("pages", 0),
        "recognized_pages": result.get("recognized_pages", 0),
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "text": result.get("text", ""),
    }


class LocalIngestRequest(BaseModel):
    path: str | None = Field(default=None, max_length=1024)
    title: str | None = Field(default=None, max_length=256)
    text: str | None = Field(default=None, max_length=200_000)
    category_hint: str | None = Field(default=None, max_length=32)


@router.post("/local/learn/ingest")
async def learn_ingest_document(body: LocalIngestRequest) -> dict:
    """AI learning: ingest a document into the dynamic knowledge graph."""
    source_path = None
    title = body.title
    text = body.text or ""
    if body.path:
        try:
            root = local_kb.resolve_root()
            target = local_kb.resolve_safe(root, body.path)
            source_path = body.path
            parsed = parse_document(target)
            if not text:
                text = parsed.render_text(max_chars=20_000)
            if not title:
                title = target.stem
        except local_kb.LocalKBError as exc:
            raise _local_guard(exc) from exc
        except (ParseError, FileTooLarge, UnsupportedFormat, MissingDependency) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not title:
        raise HTTPException(status_code=400, detail="缺少文档标题（title）")
    if not text.strip():
        raise HTTPException(status_code=400, detail="文档内容为空，无法学习")
    return learning.ingest_document(title, text, source_path, body.category_hint)


class LocalStrengthenRequest(BaseModel):
    node_ids: list[str] = Field(default_factory=list, max_length=100)
    co_occur: list[list[str]] = Field(default_factory=list, max_length=200)


@router.post("/local/learn/strengthen")
async def learn_strengthen(body: LocalStrengthenRequest) -> dict:
    """Hebbian-style reinforcement on the dynamic graph."""
    co_occur = [tuple(pair) for pair in body.co_occur if len(pair) == 2]
    return learning.strengthen(body.node_ids, co_occur)


@router.post("/local/learn/communities")
async def learn_communities(min_cluster: int = 3) -> dict:
    """Community detection over the dynamic graph (label propagation)."""
    return learning.community_detect(min_cluster=min_cluster)


@router.post("/local/search/hybrid")
async def hybrid_search_local(body: LocalKBSearchRequest) -> dict:
    """Keyword + graph-neighborhood hybrid retrieval."""
    return learning.hybrid_search(body.query, limit=body.limit)


class DynamicGraphRequest(BaseModel):
    operation: str = Field(
        pattern="^(addNode|updateNode|removeNode|getNode|listNodes|addRelation|"
        "removeRelation|getRelated|getStats|exportJson|clearAll)$"
    )
    label: str | None = Field(default=None, max_length=256)
    category: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, max_length=32)
    source_path: str | None = Field(default=None, max_length=1024)
    node_id: str | None = Field(default=None, max_length=256)
    source: str | None = Field(default=None, max_length=256)
    target: str | None = Field(default=None, max_length=256)
    relation: str | None = Field(default=None, max_length=64)
    weight: float | None = Field(default=None, ge=0.0, le=10.0)
    edge_id: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=100, ge=1, le=500)
    x: float | None = None
    y: float | None = None


def _require(value, name: str) -> str:
    if not value:
        raise HTTPException(status_code=400, detail=f"缺少参数: {name}")
    return value


@router.post("/local/graph/dynamic")
async def dynamic_graph_op(body: DynamicGraphRequest) -> dict:
    """Dynamic knowledge-graph operations (addNode/addRelation/listNodes/...)."""
    op = body.operation
    try:
        if op in ("addNode", "updateNode"):
            return learning.add_node(
                _require(body.label, "label"),
                category=body.category,
                description=body.description or "",
                color=body.color,
                source_path=body.source_path,
                node_id=body.node_id,
                x=body.x,
                y=body.y,
            )
        if op == "removeNode":
            return learning.remove_node(_require(body.node_id, "node_id"))
        if op == "getNode":
            return learning.get_node(_require(body.node_id, "node_id"))
        if op == "listNodes":
            return learning.list_nodes(limit=body.limit, category=body.category)
        if op == "addRelation":
            return learning.add_relation(
                _require(body.source, "source"),
                _require(body.target, "target"),
                label=body.relation or "关联",
                weight=body.weight,
            )
        if op == "removeRelation":
            return learning.remove_relation(_require(body.edge_id, "edge_id"))
        if op == "getRelated":
            return learning.get_related(_require(body.node_id, "node_id"), limit=body.limit)
        if op == "getStats":
            return learning.get_stats()
        if op == "exportJson":
            return learning.export_json()
        if op == "clearAll":
            return learning.clear_all()
    except learning.LearningError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    raise HTTPException(status_code=400, detail=f"不支持的操作: {op}")
