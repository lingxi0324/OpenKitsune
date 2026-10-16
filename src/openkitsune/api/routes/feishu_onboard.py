"""Feishu Device Flow onboarding API — web mode support for QR code bot creation."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feishu/onboard", tags=["feishu-onboard"])


class StartRequest(BaseModel):
    domain: str = "feishu"


class PollRequest(BaseModel):
    domain: str = "feishu"
    device_code: str


@router.post("/start")
async def onboard_start(body: StartRequest):
    """Init handshake + begin Device Flow. Returns device_code and verification_uri."""
    try:
        from openkitsune.setup.feishu_onboard import FeishuOnboard

        ob = FeishuOnboard(domain=body.domain)
        await ob.init()
        begin_data = await ob.begin()
        result = {
            "device_code": begin_data.get("device_code", ""),
            "verification_uri": begin_data.get("verification_uri_complete", ""),
            "interval": begin_data.get("interval", 5),
            "expire_in": begin_data.get("expire_in", 600),
        }
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Feishu onboard start failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/poll")
async def onboard_poll(body: PollRequest):
    """Poll Device Flow authorization status once."""
    try:
        from openkitsune.setup.feishu_onboard import FeishuOnboard

        ob = FeishuOnboard(domain=body.domain)
        result = await ob.poll(body.device_code)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Feishu onboard poll failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})
