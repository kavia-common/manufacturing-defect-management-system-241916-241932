from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import Settings, load_settings

_settings: Optional[Settings] = None
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _init() -> None:
    global _settings, _engine, _SessionLocal
    if _engine is not None:
        return

    _settings = load_settings()
    _engine = create_engine(
        _settings.database_url,
        pool_pre_ping=True,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


# PUBLIC_INTERFACE
def get_engine() -> Engine:
    """Return the singleton SQLAlchemy Engine."""
    _init()
    assert _engine is not None
    return _engine


# PUBLIC_INTERFACE
def get_db_session() -> Iterator[Session]:
    """FastAPI dependency that yields a SQLAlchemy session (commit/rollback handled by route code)."""
    _init()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for internal use (not as a FastAPI dependency)."""
    _init()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class DbConflictError(Exception):
    """Raised when a uniqueness/constraint conflict occurs."""


def fetch_one(db: Session, sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    row = db.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def fetch_all(db: Session, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows = db.execute(text(sql), params or {}).mappings().all()
    return [dict(r) for r in rows]


def execute(db: Session, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    try:
        res = db.execute(text(sql), params or {})
        return res.rowcount or 0
    except IntegrityError as e:
        raise DbConflictError(str(e)) from e
