"""Install optional feature resources after direct user confirmation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...optional_features import (
    get_install_request,
    install_browser_automation,
    update_install_request,
)

router = APIRouter(prefix="/api/optional-features")


@router.get("/{request_id}")
async def optional_feature_status(request_id: str):
    request = get_install_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="optional feature request not found")
    return request


@router.post("/{request_id}/install")
async def install_optional_feature(request: Request, request_id: str):
    install_request = get_install_request(request_id)
    if not install_request:
        raise HTTPException(status_code=404, detail="optional feature request not found")
    if install_request.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="optional feature request was cancelled")
    try:
        result = await install_browser_automation(request_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    agent = getattr(request.app.state, "agent", None)
    manager = getattr(agent, "browser_manager", None)
    if manager is not None:
        try:
            await manager.start(
                visible=bool(install_request.get("visible", True)),
                install_chromium=False,
            )
        except Exception:
            pass
    return result


@router.post("/{request_id}/cancel")
async def cancel_optional_feature(request_id: str):
    request = get_install_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="optional feature request not found")
    if request.get("status") == "installing":
        raise HTTPException(status_code=409, detail="installation is already running")
    if request.get("status") == "installed":
        return request
    return update_install_request(
        request_id,
        status="cancelled",
        message="用户已取消安装",
        progress=0,
    )
