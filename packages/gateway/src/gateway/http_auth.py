"""Fail-closed authentication for gateway HTTP control and inference endpoints."""

import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_gateway_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected = settings.gateway_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Gateway HTTP access is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid gateway credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
