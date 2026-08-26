from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

basic = HTTPBasic(auto_error=False)


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic),
) -> None:
    if not settings.auth.enabled:
        return
    if request.url.path in {"/health", "/api/health"}:
        return
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(credentials.username, settings.auth.username)
    pass_ok = secrets.compare_digest(credentials.password, settings.auth.password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 정보가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
