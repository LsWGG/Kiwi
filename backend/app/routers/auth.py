"""访问令牌登录：校验、下发 HttpOnly Cookie、登出。"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.security import is_authenticated

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = 30 * 24 * 60 * 60


class LoginIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)


def _enabled() -> bool:
    return bool(settings.access_token.strip())


@router.get("/status")
async def auth_status(request: Request):
    return {
        "enabled": _enabled(),
        "authenticated": is_authenticated(request.scope),
    }


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response):
    if not _enabled():
        return {"ok": True, "enabled": False}
    expected = settings.access_token.strip()
    if not secrets.compare_digest(data.token, expected):
        raise HTTPException(401, "访问令牌不正确")
    response.set_cookie(
        settings.access_cookie_name,
        expected,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return {"ok": True, "enabled": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(settings.access_cookie_name, path="/")
    return {"ok": True}
