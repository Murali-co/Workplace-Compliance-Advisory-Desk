"""Authenticate client identity instead of trusting X-Client-ID."""

import secrets

from app.core.config import settings
from fastapi import Header, HTTPException


def get_client_id(
    authorization: str = Header(default=""), x_client_id: str | None = Header(default=None)
) -> str:
    if not settings.AUTH_CLIENT_TOKENS:
        raise HTTPException(503, "Client authentication has not been configured.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            401, "A valid bearer token is required.", headers={"WWW-Authenticate": "Bearer"}
        )
    identity = None
    for client, secret in settings.AUTH_CLIENT_TOKENS.items():
        if secrets.compare_digest(token.encode("utf-8"), secret.get_secret_value().encode("utf-8")):
            identity = client
    if identity is None or (x_client_id is not None and x_client_id != identity):
        raise HTTPException(
            401, "Invalid client credentials.", headers={"WWW-Authenticate": "Bearer"}
        )
    return identity
