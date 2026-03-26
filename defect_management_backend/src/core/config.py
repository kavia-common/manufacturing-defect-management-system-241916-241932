from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _parse_db_connection_txt_value(raw: str) -> str:
    """
    Parse db_connection.txt content.

    The database container uses the format:
        "psql postgresql://user:pass@host:port/db"

    We accept either the above or a raw "postgresql://..." URI and return the URI.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty db_connection.txt content")

    if raw.startswith("psql "):
        return raw[len("psql ") :].strip()

    # If someone changed it to just a connection URI, accept it.
    return raw


def _find_db_connection_txt() -> Optional[Path]:
    """
    Locate `defect_management_database/db_connection.txt` by scanning sibling workspaces.

    The workspace naming has an auto-generated suffix, so we cannot rely on a fixed path.

    IMPORTANT: This repository is checked out under:
        /home/kavia/workspace/code-generation/<workspace-name>/defect_management_backend/...

    A previous implementation used an incorrect `parents[]` index, which caused us to scan
    `/home/kavia/workspace/*` instead of `/home/kavia/workspace/code-generation/*`, so
    `db_connection.txt` was never discovered.
    """
    # /.../<workspace-name>/defect_management_backend/src/core/config.py
    # parents[0]=core, [1]=src, [2]=defect_management_backend
    backend_dir = Path(__file__).resolve().parents[2]
    workspace_dir = backend_dir.parent  # .../<workspace-name>
    codegen_dir = workspace_dir.parent  # .../code-generation

    # Fast paths first (avoid globbing if possible)
    candidates = [
        # Typical sibling workspace layout:
        codegen_dir
        / "manufacturing-defect-management-system-241916-241930"
        / "defect_management_database"
        / "db_connection.txt",
        # Generic pattern inside the *same* workspace dir (if someone co-locates db container)
        workspace_dir / "defect_management_database" / "db_connection.txt",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Bounded scan under code-generation for any matching workspace.
    for p in codegen_dir.glob(
        "manufacturing-defect-management-system-*/defect_management_database/db_connection.txt"
    ):
        if p.exists():
            return p

    return None


def _default_db_url() -> Optional[str]:
    """
    Attempt to read the Postgres URL from the database container's db_connection.txt.

    Prefer DATABASE_URL env var in production; this is a dev-friendly convenience.
    """
    txt_path = _find_db_connection_txt()
    if txt_path and txt_path.exists():
        return _parse_db_connection_txt_value(txt_path.read_text(encoding="utf-8"))
    return None


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    # Database
    database_url: str

    # Supabase JWT verification
    # NOTE: For step 04.01 we allow placeholders so non-auth flows can run.
    # Auth-protected endpoints will still require real Supabase values to function.
    supabase_url: str
    supabase_anon_key: str

    # CORS
    allowed_origins: list[str]
    allowed_headers: list[str]
    allowed_methods: list[str]

    # App
    trust_proxy: bool = False
    environment: str = "development"
    auth_disabled: bool = False


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    """
    Load settings from environment variables.

    Required for DB connectivity:
    - DATABASE_URL (recommended), a SQLAlchemy-compatible URL like:
        postgresql+psycopg://user:pass@host:port/db
      If not provided, we try to infer from the database container db_connection.txt.

    Supabase:
    - SUPABASE_URL
    - SUPABASE_KEY

    For step 04.01 (placeholder integration) we do NOT hard-fail if Supabase vars
    are missing. Instead we populate safe placeholders and allow running endpoints
    that don't require authentication. Authenticated endpoints will fail until real
    Supabase values are provided OR AUTH_DISABLED=true is set for local/dev.

    CORS:
    - ALLOWED_ORIGINS (comma-separated), default "*"
    - ALLOWED_HEADERS (comma-separated), default "*"
    - ALLOWED_METHODS (comma-separated), default "*"

    Optional:
    - AUTH_DISABLED=true to bypass JWT verification/RBAC (DEV ONLY).
    - TRUST_PROXY=true if behind a reverse proxy.
    """
    allowed_origins = [
        o.strip()
        for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ]
    allowed_headers = [
        h.strip()
        for h in os.environ.get("ALLOWED_HEADERS", "*").split(",")
        if h.strip()
    ]
    allowed_methods = [
        m.strip()
        for m in os.environ.get("ALLOWED_METHODS", "*").split(",")
        if m.strip()
    ]

    db_url_env = os.environ.get("DATABASE_URL", "").strip()
    if db_url_env:
        database_url = db_url_env
    else:
        inferred = _default_db_url()
        if not inferred:
            raise RuntimeError(
                "DATABASE_URL is not set and db_connection.txt could not be found. "
                "Set DATABASE_URL to e.g. postgresql+psycopg://appuser:...@localhost:5000/myapp"
            )
        # Convert plain postgresql://... into SQLAlchemy psycopg URL.
        if inferred.startswith("postgresql+"):
            database_url = inferred
        elif inferred.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + inferred[len("postgresql://") :]
        else:
            database_url = inferred

    # Supabase placeholders (usable to boot the service / generate docs)
    supabase_url = (
        os.environ.get("SUPABASE_URL", "").strip() or "https://placeholder.supabase.co"
    )
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip() or "placeholder-anon-key"

    trust_proxy = _read_bool_env("TRUST_PROXY", default=False)
    environment = os.environ.get("NODE_ENV", "development").strip()
    auth_disabled = _read_bool_env("AUTH_DISABLED", default=False)

    return Settings(
        database_url=database_url,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_key,
        allowed_origins=allowed_origins,
        allowed_headers=allowed_headers,
        allowed_methods=allowed_methods,
        trust_proxy=trust_proxy,
        environment=environment,
        auth_disabled=auth_disabled,
    )
