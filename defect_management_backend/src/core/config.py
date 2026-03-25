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


def _default_db_url() -> Optional[str]:
    """
    Attempt to read the Postgres URL from the sibling database container's db_connection.txt.
    """
    # Repo layout:
    # manufacturing-defect-management-system-*/defect_management_backend
    # manufacturing-defect-management-system-*/../manufacturing-defect-management-system-*/defect_management_database/db_connection.txt
    backend_dir = Path(__file__).resolve().parents[3]  # .../defect_management_backend
    workspace_dir = backend_dir.parent  # .../manufacturing-defect-management-system-241916-241932
    # database workspace is a sibling folder at /home/kavia/...-241930; we cannot safely compute it.
    # Therefore, use an env var first and only fallback to a conventional relative lookup if present.
    rel_guess = workspace_dir.parent / "manufacturing-defect-management-system-241916-241930" / "defect_management_database" / "db_connection.txt"
    if rel_guess.exists():
        return _parse_db_connection_txt_value(rel_guess.read_text(encoding="utf-8"))
    return None


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    # Database
    database_url: str

    # Supabase JWT verification
    supabase_url: str
    supabase_anon_key: str

    # CORS
    allowed_origins: list[str]
    allowed_headers: list[str]
    allowed_methods: list[str]

    # App
    trust_proxy: bool = False
    environment: str = "development"


def load_settings() -> Settings:
    """
    Load settings from environment variables.

    Environment variables expected (already present in this container's .env):
    - SUPABASE_URL
    - SUPABASE_KEY
    - ALLOWED_ORIGINS (comma-separated)
    - ALLOWED_HEADERS (comma-separated)
    - ALLOWED_METHODS (comma-separated)

    Additionally required for DB connectivity:
    - DATABASE_URL (recommended), a SQLAlchemy-compatible URL like:
        postgresql+psycopg://user:pass@host:port/db
      If not provided, we try to infer from the database container db_connection.txt.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

    allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
    allowed_headers = [h.strip() for h in os.environ.get("ALLOWED_HEADERS", "*").split(",") if h.strip()]
    allowed_methods = [m.strip() for m in os.environ.get("ALLOWED_METHODS", "*").split(",") if m.strip()]

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
        # Keep it simple: if already has +psycopg keep, else insert.
        if inferred.startswith("postgresql+"):
            database_url = inferred
        elif inferred.startswith("postgresql://"):
            database_url = "postgresql+psycopg://" + inferred[len("postgresql://") :]
        else:
            database_url = inferred

    trust_proxy = os.environ.get("TRUST_PROXY", "false").strip().lower() in {"1", "true", "yes", "on"}
    environment = os.environ.get("NODE_ENV", "development").strip()

    return Settings(
        database_url=database_url,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_key,
        allowed_origins=allowed_origins,
        allowed_headers=allowed_headers,
        allowed_methods=allowed_methods,
        trust_proxy=trust_proxy,
        environment=environment,
    )
