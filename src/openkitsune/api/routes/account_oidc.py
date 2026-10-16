"""Protected control endpoints for OpenKitsune Account login."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from openkitsune.account.desktop import require_desktop_account, trusted_marketplace_origin
from openkitsune.account.oidc import AccountOIDCError, AccountOIDCManager

capability_router = APIRouter(prefix="/api/account", tags=["account"])
router = APIRouter(prefix="/api/account", tags=["account"])


@capability_router.get("/capability")
async def account_capability(request: Request) -> dict:
    """Expose the distribution policy without activating the account provider."""

    return request.app.state.account_capability


def _manager(request: Request) -> AccountOIDCManager:
    return request.app.state.account_oidc_manager


class LoginStartRequest(BaseModel):
    flow: Literal["loopback", "device", "native"] = "loopback"
    redirect_uri: str | None = Field(default=None, max_length=512)


@router.post("/login/start")
async def start_login(
    request: Request, response: Response, body: LoginStartRequest | None = None
) -> dict:
    try:
        kwargs = {"flow": body.flow if body else "loopback"}
        if body and body.flow == "native":
            kwargs["redirect_uri"] = body.redirect_uri
        attempt = await _manager(request).start(**kwargs)
    except (OSError, AccountOIDCError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return {
        "attempt_id": attempt.attempt_id,
        "authorization_url": attempt.authorization_url,
        "expires_in": attempt.expires_in,
        "flow": attempt.flow,
        "user_code": attempt.user_code,
        "verification_uri": attempt.verification_uri,
    }


class NativeCallbackRequest(BaseModel):
    state: str = Field(min_length=1, max_length=256)
    code: str = Field(default="", max_length=4096)
    error: str = Field(default="", max_length=256)


@router.post("/login/native/callback/{attempt_id}")
async def native_callback(
    request: Request, response: Response, attempt_id: str, body: NativeCallbackRequest
) -> dict:
    """Authenticated App-to-instance delivery; this is not a public redirect endpoint."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _manager(request).complete_native_callback(
            attempt_id, state=body.state, code=body.code, error=body.error
        )
    except AccountOIDCError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login/cancel/{attempt_id}")
async def cancel_login(request: Request, attempt_id: str) -> dict:
    try:
        await _manager(request).cancel(attempt_id)
        return await _manager(request).attempt_status(attempt_id)
    except AccountOIDCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/login/status/{attempt_id}")
async def login_status(request: Request, response: Response, attempt_id: str) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await _manager(request).attempt_status(attempt_id)
    except AccountOIDCError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/status")
async def account_status(request: Request, refresh: bool = False) -> dict:
    if refresh:
        return await _manager(request).snapshot(force=True)
    return await _manager(request).snapshot()


@router.post("/entitlements/refresh")
async def refresh_entitlements(request: Request) -> dict:
    try:
        return await _manager(request).refresh_entitlements()
    except AccountOIDCError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/logout")
async def logout(request: Request) -> dict:
    try:
        return {"end_session_url": await _manager(request).logout()}
    except AccountOIDCError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class MarketplaceOpenBody(BaseModel):
    origin: str = Field(max_length=500)


@router.post("/marketplace/handoff")
async def marketplace_handoff(body: MarketplaceOpenBody, request: Request) -> dict:
    require_desktop_account(request)
    origin = trusted_marketplace_origin(body.origin)
    if request.app.state.account_capability.get("mode") != "openkitsune":
        return {"ticket": None}
    try:
        ticket = await _manager(request).marketplace_handoff(origin)
        return {"ticket": ticket, "account": await _manager(request).snapshot()}
    except AccountOIDCError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
