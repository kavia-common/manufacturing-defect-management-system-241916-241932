from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from src.core.config import load_settings
from src.core.db import fetch_all, fetch_one, get_db_session

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated user context derived from Supabase JWT + local RBAC tables."""

    supabase_uid: str
    email: Optional[str]
    db_user_id: Optional[str]
    roles: Set[str]
    raw_claims: Dict[str, Any]


class _JwksCache:
    def __init__(self) -> None:
        self._jwks_client: Optional[PyJWKClient] = None
        self._expires_at: float = 0.0
        self._jwks_url: Optional[str] = None

    def get_client(self, jwks_url: str) -> PyJWKClient:
        # refresh every 10 minutes
        now = time.time()
        if self._jwks_client is None or self._jwks_url != jwks_url or now >= self._expires_at:
            self._jwks_url = jwks_url
            self._jwks_client = PyJWKClient(jwks_url)
            self._expires_at = now + 600
        return self._jwks_client


_jwks_cache = _JwksCache()


def _get_jwks_url() -> str:
    settings = load_settings()
    # Supabase JWKS endpoint:
    # https://<project>.supabase.co/auth/v1/keys
    return settings.supabase_url.rstrip("/") + "/auth/v1/keys"


async def _verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Verify a Supabase-issued JWT using the project's JWKS.

    We validate signature + standard claims (exp, nbf when present). We also validate issuer.
    """
    settings = load_settings()
    jwks_url = _get_jwks_url()

    try:
        jwk_client = _jwks_cache.get_client(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=None,  # Supabase access tokens may not include aud reliably
            options={"verify_aud": False},
            issuer=settings.supabase_url.rstrip("/") + "/auth/v1",
        )
        return claims
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
        ) from e


def _get_roles_for_user(db, supabase_uid: str) -> tuple[Optional[str], Set[str], Optional[str]]:
    """
    Return (db_user_id, roles, email) by joining users->user_roles->roles.
    """
    user_row = fetch_one(
        db,
        """
        select id, email
        from users
        where supabase_uid = :supabase_uid and is_active = true
        """,
        {"supabase_uid": supabase_uid},
    )
    if not user_row:
        return None, set(), None

    roles_rows = fetch_all(
        db,
        """
        select r.name
        from user_roles ur
        join roles r on r.id = ur.role_id
        where ur.user_id = :user_id
        """,
        {"user_id": user_row["id"]},
    )
    roles = {r["name"] for r in roles_rows}
    return str(user_row["id"]), roles, user_row.get("email")


# PUBLIC_INTERFACE
async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db=Depends(get_db_session),
) -> AuthenticatedUser:
    """FastAPI dependency: validates Supabase JWT and loads RBAC roles from Postgres."""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization bearer token")

    claims = await _verify_supabase_jwt(creds.credentials)
    supabase_uid = claims.get("sub")
    if not supabase_uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing 'sub' claim")

    db_user_id, roles, email = _get_roles_for_user(db, supabase_uid=supabase_uid)
    # If user not provisioned in local DB, treat as authenticated but unprivileged.
    # Frontend can show "request access" flows.
    ip = request.client.host if request.client else None
    _ = ip  # reserved for future audit meta

    return AuthenticatedUser(
        supabase_uid=str(supabase_uid),
        email=email or claims.get("email"),
        db_user_id=db_user_id,
        roles=roles,
        raw_claims=claims,
    )


# PUBLIC_INTERFACE
def require_roles(required: Set[str]):
    """Dependency factory enforcing RBAC roles."""

    async def _dep(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.roles.intersection(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role. Required one of: {sorted(required)}",
            )
        return user

    return _dep


# PUBLIC_INTERFACE
def require_authenticated(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """Dependency enforcing authentication only (no RBAC role required)."""
    return user
