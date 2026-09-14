from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from time import monotonic

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    create_session_token,
    session_from_request,
    verify_password,
)
from app.core.config import get_settings


router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_ATTEMPT_LIMIT = 8
_failed_attempts: dict[str, deque[float]] = defaultdict(deque)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _prune_attempts(key: str) -> deque[float]:
    now = monotonic()
    attempts = _failed_attempts[key]
    while attempts and now - attempts[0] > _LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return attempts


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    settings = get_settings()
    key = _client_key(request)
    attempts = _prune_attempts(key)

    if len(attempts) >= _LOGIN_ATTEMPT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many failed login attempts; try again later",
        )

    username_ok = payload.username == settings.auth_username
    password_ok = verify_password(payload.password, settings.auth_password_hash)

    if not (username_ok and password_ok):
        attempts.append(monotonic())
        await asyncio.sleep(0.35)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )

    _failed_attempts.pop(key, None)
    token = create_session_token(settings.auth_username)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"authenticated": True, "username": settings.auth_username}


@router.get("/session")
def session(request: Request) -> dict:
    identity = session_from_request(request)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return {
        "authenticated": True,
        "username": identity.username,
        "expires_at": identity.expires_at,
    }


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}
