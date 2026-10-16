"""Local API for Marketplace deep-link installation."""

from __future__ import annotations

import os
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from openkitsune.account.desktop import require_marketplace_access, trusted_marketplace_origin
from openkitsune.account.oidc import AccountOIDCManager
from openkitsune.integrations.marketplace import MarketplaceInstallManager
from openkitsune.integrations.marketplace.installer import MarketplaceInstallError

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@router.get("/skills")
async def list_marketplace_skills(
    q: str = Query(default="", max_length=300),
    category: str = Query(default="", max_length=100),
    sort: Literal["popular", "new", "acquired"] = "popular",
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Read the public catalog without forwarding local credentials or granting acquisition."""
    origin = trusted_marketplace_origin(
        os.environ.get("OPENKITSUNE_MARKETPLACE_URL", "https://marketplace.openkitsune.cn")
    )
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(
                f"{origin}/api/v1/resources",
                params={
                    "type": "skill",
                    "q": q,
                    "category": category,
                    "sort": sort,
                    "limit": limit,
                    "offset": offset,
                },
            )
            response.raise_for_status()
            data = response.json()
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("items"), list)
            or not isinstance(data.get("total"), int)
            or data["total"] < 0
            or any(
                not isinstance(item, dict)
                or item.get("resource_type") != "skill"
                or not all(
                    isinstance(item.get(key), str) and item[key] for key in ("id", "slug", "name")
                )
                for item in data["items"]
            )
        ):
            raise ValueError("Invalid marketplace catalog")
        return {
            "items": data["items"],
            "total": data["total"],
            "limit": limit,
            "offset": offset,
            "facets": data.get("facets", {}),
            "origin": origin,
        }
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail={"code": "marketplace_catalog_unavailable"}
        ) from exc


class PrepareBody(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    endpoint: str = Field(min_length=1, max_length=500)


def _manager(request: Request) -> MarketplaceInstallManager:
    manager = getattr(request.app.state, "marketplace_install_manager", None)
    if manager is None:
        manager = MarketplaceInstallManager()
        request.app.state.marketplace_install_manager = manager
    return manager


def _error(exc: MarketplaceInstallError) -> HTTPException:
    status = (
        404
        if exc.code == "marketplace_install_not_found"
        else 409
        if exc.code == "marketplace_install_busy"
        else 400
    )
    return HTTPException(status_code=status, detail={"code": exc.code})


def _account(request: Request) -> AccountOIDCManager:
    require_marketplace_access(request)
    account = getattr(request.app.state, "account_oidc_manager", None)
    if account is None or request.app.state.account_capability.get("mode") != "openkitsune":
        raise MarketplaceInstallError("marketplace_account_required")
    return account


@router.post("/installs/prepare")
async def prepare_install(body: PrepareBody, request: Request):
    try:
        account = _account(request)
        endpoint = trusted_marketplace_origin(body.endpoint)
        return {"data": await _manager(request).prepare(body.token, endpoint, account=account)}
    except MarketplaceInstallError as exc:
        raise _error(exc) from exc


@router.get("/installs")
async def list_installs(request: Request):
    require_marketplace_access(request)
    return {"data": _manager(request).list_jobs()}


@router.get("/installs/{job_id}")
async def get_install(job_id: str, request: Request):
    require_marketplace_access(request)
    try:
        return {"data": await _manager(request).get(job_id)}
    except MarketplaceInstallError as exc:
        raise _error(exc) from exc


@router.post("/installs/{job_id}/confirm")
async def confirm_install(job_id: str, request: Request):
    try:
        return {"data": await _manager(request).confirm(job_id, request, account=_account(request))}
    except MarketplaceInstallError as exc:
        raise _error(exc) from exc


@router.post("/installs/{job_id}/cancel")
async def cancel_install(job_id: str, request: Request):
    require_marketplace_access(request)
    try:
        return {"data": await _manager(request).cancel(job_id)}
    except MarketplaceInstallError as exc:
        raise _error(exc) from exc
