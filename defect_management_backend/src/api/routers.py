from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from src.api.schemas import (
    ActionCreate,
    ActionOut,
    ActionUpdate,
    AttachmentCreate,
    AttachmentOut,
    DashboardParetoItem,
    DashboardTrendItem,
    DefectCreate,
    DefectOut,
    DefectUpdate,
    DueActionItem,
    PagedResponse,
    PageMeta,
    RcaOut,
    RcaUpsert,
    UserListItem,
    UserMeOut,
)
from src.core.auth import AuthenticatedUser, require_authenticated, require_roles
from src.core.db import DbConflictError, fetch_all, fetch_one, get_db_session

router = APIRouter()


def _paged(
    meta_total: int, limit: int, offset: int, items: List[Dict[str, Any]]
) -> PagedResponse:
    return PagedResponse(
        meta=PageMeta(limit=limit, offset=offset, total=meta_total), items=items
    )


@router.get(
    "/auth/me",
    response_model=UserMeOut,
    tags=["health"],
    summary="Get current authenticated user profile",
    description=(
        "Returns the authenticated user's Supabase UID, email, internal DB user id (if mapped), "
        "and resolved RBAC roles. Frontend uses this to drive navigation and permissions."
    ),
)
def auth_me(user: AuthenticatedUser = Depends(require_authenticated)) -> UserMeOut:
    # PUBLIC_INTERFACE
    """Return the current authenticated user context (for frontend session bootstrap)."""
    return UserMeOut(
        supabase_uid=user.supabase_uid,
        email=user.email,
        db_user_id=UUID(user.db_user_id) if user.db_user_id else None,
        roles=sorted(user.roles),
    )


@router.get(
    "/users",
    response_model=List[UserListItem],
    tags=["configs"],
    summary="List active users (for pickers)",
    description=(
        "Lists active users from the RBAC tables. Typically used for selecting an action owner. "
        "Requires supervisor or quality role."
    ),
)
def list_users(
    is_active: Optional[bool] = Query(
        True, description="If true, returns only active users"
    ),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(
        require_roles({"production_supervisor", "quality_engineer"})
    ),
) -> List[Dict[str, Any]]:
    # PUBLIC_INTERFACE
    """List users for assignment/pickers (minimal fields)."""
    where_sql = ""
    params: Dict[str, Any] = {"limit": limit}
    if is_active is not None:
        where_sql = " where is_active = :is_active"
        params["is_active"] = is_active
    return fetch_all(
        db,
        f"""
        select id, email, display_name, is_active
        from users
        {where_sql}
        order by coalesce(display_name, email) asc nulls last
        limit :limit
        """,
        params,
    )


@router.get("/configs/defect-types", tags=["configs"])
def list_defect_types(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List defect types."""
    return fetch_all(db, "select * from config_defect_types order by name asc")


@router.get("/configs/lines", tags=["configs"])
def list_lines(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List production lines."""
    return fetch_all(db, "select * from config_lines order by name asc")


@router.get("/configs/shifts", tags=["configs"])
def list_shifts(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List shifts."""
    return fetch_all(db, "select * from config_shifts order by name asc")


@router.get("/configs/parts", tags=["configs"])
def list_parts(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List parts."""
    return fetch_all(db, "select * from config_parts order by name asc")


@router.get("/configs/severity-rules", tags=["configs"])
def list_severity_rules(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_roles({"quality_engineer"})),
):
    """List severity rules (admin/quality only)."""
    return fetch_all(db, "select * from config_severity_rules order by created_at desc")


@router.post("/defects", response_model=DefectOut, tags=["defects"])
def create_defect(
    payload: DefectCreate,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(
        require_roles({"operator", "production_supervisor", "quality_engineer"})
    ),
):
    """Create a defect record."""
    try:
        row = fetch_one(
            db,
            """
            insert into defects (occurred_at, line_id, shift_id, part_id, defect_type_id, quantity, description, station, plant, created_by, updated_by)
            values (:occurred_at, :line_id, :shift_id, :part_id, :defect_type_id, :quantity, :description, :station, :plant, :actor, :actor)
            returning *
            """,
            {
                "occurred_at": payload.occurred_at,
                "line_id": str(payload.line_id),
                "shift_id": str(payload.shift_id),
                "part_id": str(payload.part_id) if payload.part_id else None,
                "defect_type_id": str(payload.defect_type_id),
                "quantity": payload.quantity,
                "description": payload.description,
                "station": payload.station,
                "plant": payload.plant,
                "actor": user.db_user_id,
            },
        )
        if not row:
            raise HTTPException(status_code=500, detail="Failed to create defect")
        db.commit()
        return row  # type: ignore[return-value]
    except DbConflictError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/defects", response_model=PagedResponse, tags=["defects"])
def list_defects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    line_id: Optional[UUID] = None,
    defect_type_id: Optional[UUID] = None,
    from_date: Optional[date] = Query(
        None, description="Filter occurred_at >= from_date"
    ),
    to_date: Optional[date] = Query(None, description="Filter occurred_at <= to_date"),
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List defects with basic filters."""
    where = []
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status_filter:
        where.append("d.status = :status")
        params["status"] = status_filter
    if line_id:
        where.append("d.line_id = :line_id")
        params["line_id"] = str(line_id)
    if defect_type_id:
        where.append("d.defect_type_id = :defect_type_id")
        params["defect_type_id"] = str(defect_type_id)
    if from_date:
        where.append("d.occurred_at >= :from_dt")
        params["from_dt"] = datetime.combine(
            from_date, datetime.min.time()
        ).astimezone()
    if to_date:
        where.append("d.occurred_at <= :to_dt")
        params["to_dt"] = datetime.combine(to_date, datetime.max.time()).astimezone()

    where_sql = (" where " + " and ".join(where)) if where else ""

    total_row = fetch_one(
        db, f"select count(*)::int as c from defects d{where_sql}", params
    )
    total = int(total_row["c"]) if total_row else 0

    items = fetch_all(
        db,
        f"""
        select d.*
        from defects d
        {where_sql}
        order by d.occurred_at desc
        limit :limit offset :offset
        """,
        params,
    )
    return _paged(total, limit, offset, items)


@router.get("/defects/{defect_id}", response_model=DefectOut, tags=["defects"])
def get_defect(
    defect_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Get a single defect by id."""
    row = fetch_one(db, "select * from defects where id = :id", {"id": str(defect_id)})
    if not row:
        raise HTTPException(status_code=404, detail="Defect not found")
    return row  # type: ignore[return-value]


@router.patch("/defects/{defect_id}", response_model=DefectOut, tags=["defects"])
def update_defect(
    defect_id: UUID,
    payload: DefectUpdate,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(
        require_roles({"production_supervisor", "quality_engineer"})
    ),
):
    """Update defect fields and optionally status."""
    current = fetch_one(
        db, "select * from defects where id = :id", {"id": str(defect_id)}
    )
    if not current:
        raise HTTPException(status_code=404, detail="Defect not found")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return current  # type: ignore[return-value]

    set_parts = []
    params: Dict[str, Any] = {"id": str(defect_id), "updated_by": user.db_user_id}
    for k, v in fields.items():
        set_parts.append(f"{k} = :{k}")
        params[k] = str(v) if isinstance(v, UUID) else v

    set_parts.append("updated_by = :updated_by")
    row = fetch_one(
        db,
        f"update defects set {', '.join(set_parts)} where id = :id returning *",
        params,
    )
    db.commit()
    assert row is not None
    return row  # type: ignore[return-value]


@router.get("/defects/{defect_id}/status-history", tags=["defects"])
def defect_status_history(
    defect_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Get defect status history (audit-ready)."""
    return fetch_all(
        db,
        """
        select *
        from defect_status_history
        where defect_id = :id
        order by changed_at asc
        """,
        {"id": str(defect_id)},
    )


@router.get("/defects/{defect_id}/rca", response_model=RcaOut, tags=["rca"])
def get_rca(
    defect_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Fetch RCA record for a defect (if present)."""
    row = fetch_one(
        db, "select * from defect_rca where defect_id = :id", {"id": str(defect_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="RCA not found")
    return row  # type: ignore[return-value]


@router.put("/defects/{defect_id}/rca", response_model=RcaOut, tags=["rca"])
def upsert_rca(
    defect_id: UUID,
    payload: RcaUpsert,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_roles({"quality_engineer"})),
):
    """Create or update RCA for a defect."""
    # Ensure defect exists
    d = fetch_one(db, "select id from defects where id = :id", {"id": str(defect_id)})
    if not d:
        raise HTTPException(status_code=404, detail="Defect not found")

    completed_by = user.db_user_id if payload.completed else None
    completed_at = datetime.utcnow() if payload.completed else None

    row = fetch_one(
        db,
        """
        insert into defect_rca (defect_id, problem_statement, root_cause, containment_action, why_analysis, contributing_factors, completed_by, completed_at)
        values (:defect_id, :problem_statement, :root_cause, :containment_action, :why_analysis::jsonb, :contributing_factors, :completed_by, :completed_at)
        on conflict (defect_id) do update
        set
          problem_statement = excluded.problem_statement,
          root_cause = excluded.root_cause,
          containment_action = excluded.containment_action,
          why_analysis = excluded.why_analysis,
          contributing_factors = excluded.contributing_factors,
          completed_by = excluded.completed_by,
          completed_at = excluded.completed_at
        returning *
        """,
        {
            "defect_id": str(defect_id),
            "problem_statement": payload.problem_statement,
            "root_cause": payload.root_cause,
            "containment_action": payload.containment_action,
            "why_analysis": payload.why_analysis,
            "contributing_factors": payload.contributing_factors,
            "completed_by": completed_by,
            "completed_at": completed_at,
        },
    )
    db.commit()
    assert row is not None
    return row  # type: ignore[return-value]


@router.post("/actions", response_model=ActionOut, tags=["actions"])
def create_action(
    payload: ActionCreate,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(
        require_roles({"production_supervisor", "quality_engineer"})
    ),
):
    """Create a corrective action for a defect."""
    defect = fetch_one(
        db, "select id from defects where id = :id", {"id": str(payload.defect_id)}
    )
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")

    rca = fetch_one(
        db,
        "select id from defect_rca where defect_id = :id",
        {"id": str(payload.defect_id)},
    )
    row = fetch_one(
        db,
        """
        insert into corrective_actions (defect_id, rca_id, title, description, owner_user_id, due_date, created_by, updated_by)
        values (:defect_id, :rca_id, :title, :description, :owner_user_id, :due_date, :actor, :actor)
        returning *
        """,
        {
            "defect_id": str(payload.defect_id),
            "rca_id": str(rca["id"]) if rca else None,
            "title": payload.title,
            "description": payload.description,
            "owner_user_id": (
                str(payload.owner_user_id) if payload.owner_user_id else None
            ),
            "due_date": payload.due_date,
            "actor": user.db_user_id,
        },
    )
    db.commit()
    assert row is not None
    return row  # type: ignore[return-value]


@router.get("/actions", response_model=PagedResponse, tags=["actions"])
def list_actions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    due_before: Optional[date] = None,
    defect_id: Optional[UUID] = Query(
        None, description="Optional filter: only actions for this defect"
    ),
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List corrective actions."""
    where = []
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status_filter:
        where.append("a.status = :status")
        params["status"] = status_filter
    if due_before:
        where.append("a.due_date <= :due_before")
        params["due_before"] = due_before
    if defect_id:
        where.append("a.defect_id = :defect_id")
        params["defect_id"] = str(defect_id)

    where_sql = (" where " + " and ".join(where)) if where else ""

    total_row = fetch_one(
        db, f"select count(*)::int as c from corrective_actions a{where_sql}", params
    )
    total = int(total_row["c"]) if total_row else 0

    items = fetch_all(
        db,
        f"""
        select a.*
        from corrective_actions a
        {where_sql}
        order by a.created_at desc
        limit :limit offset :offset
        """,
        params,
    )
    return _paged(total, limit, offset, items)


@router.get("/actions/{action_id}", response_model=ActionOut, tags=["actions"])
def get_action(
    action_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    # PUBLIC_INTERFACE
    """Get a single corrective action by id."""
    row = fetch_one(
        db, "select * from corrective_actions where id = :id", {"id": str(action_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Action not found")
    return row  # type: ignore[return-value]


@router.get(
    "/defects/{defect_id}/actions",
    response_model=List[ActionOut],
    tags=["actions"],
)
def list_actions_for_defect(
    defect_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    # PUBLIC_INTERFACE
    """List all corrective actions for a defect (non-paginated convenience endpoint)."""
    defect = fetch_one(db, "select id from defects where id = :id", {"id": str(defect_id)})
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")
    return fetch_all(
        db,
        "select * from corrective_actions where defect_id = :id order by created_at asc",
        {"id": str(defect_id)},
    )


@router.patch("/actions/{action_id}", response_model=ActionOut, tags=["actions"])
def update_action(
    action_id: UUID,
    payload: ActionUpdate,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(
        require_roles({"production_supervisor", "quality_engineer"})
    ),
):
    """Update corrective action fields, including status and verification."""
    current = fetch_one(
        db, "select * from corrective_actions where id = :id", {"id": str(action_id)}
    )
    if not current:
        raise HTTPException(status_code=404, detail="Action not found")

    fields = payload.model_dump(exclude_unset=True)
    set_parts = []
    params: Dict[str, Any] = {"id": str(action_id), "updated_by": user.db_user_id}

    verified_value = fields.pop("verified", None) if "verified" in fields else None
    if verified_value is not None:
        if verified_value is True:
            set_parts.append("verified_by = :verified_by")
            set_parts.append("verified_at = :verified_at")
            params["verified_by"] = user.db_user_id
            params["verified_at"] = datetime.utcnow()
        else:
            set_parts.append("verified_by = null")
            set_parts.append("verified_at = null")

    for k, v in fields.items():
        set_parts.append(f"{k} = :{k}")
        params[k] = str(v) if isinstance(v, UUID) else v

    set_parts.append("updated_by = :updated_by")

    row = fetch_one(
        db,
        f"update corrective_actions set {', '.join(set_parts)} where id = :id returning *",
        params,
    )
    db.commit()
    assert row is not None
    return row  # type: ignore[return-value]


@router.get("/actions/{action_id}/status-history", tags=["actions"])
def action_status_history(
    action_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Get corrective action status history."""
    return fetch_all(
        db,
        """
        select *
        from corrective_action_status_history
        where corrective_action_id = :id
        order by changed_at asc
        """,
        {"id": str(action_id)},
    )


@router.post("/attachments", response_model=AttachmentOut, tags=["uploads"])
def create_attachment_metadata(
    payload: AttachmentCreate,
    db: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(
        require_roles({"operator", "production_supervisor", "quality_engineer"})
    ),
):
    """
    Create attachment metadata record.

    Actual file upload should be done client-side using Supabase Storage; the backend only stores metadata.
    """
    defect = fetch_one(
        db, "select id from defects where id = :id", {"id": str(payload.defect_id)}
    )
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")

    row = fetch_one(
        db,
        """
        insert into defect_attachments (defect_id, bucket, object_key, url, content_type, bytes, uploaded_by)
        values (:defect_id, :bucket, :object_key, :url, :content_type, :bytes, :uploaded_by)
        returning *
        """,
        {
            "defect_id": str(payload.defect_id),
            "bucket": payload.bucket,
            "object_key": payload.object_key,
            "url": payload.url,
            "content_type": payload.content_type,
            "bytes": payload.bytes,
            "uploaded_by": user.db_user_id,
        },
    )
    db.commit()
    assert row is not None
    return row  # type: ignore[return-value]


@router.get(
    "/defects/{defect_id}/attachments",
    response_model=List[AttachmentOut],
    tags=["uploads"],
)
def list_attachments(
    defect_id: UUID,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """List attachments for a defect."""
    return fetch_all(
        db,
        "select * from defect_attachments where defect_id = :id order by uploaded_at desc",
        {"id": str(defect_id)},
    )


@router.get(
    "/dashboard/summary",
    tags=["dashboards"],
    summary="Dashboard KPI summary",
    description="Single-call summary KPIs (counts by workflow/action status) for quick dashboard bootstrap.",
)
def dashboard_summary(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
) -> Dict[str, Any]:
    # PUBLIC_INTERFACE
    """Return basic KPI counts used by the dashboard landing page."""
    defects_by_status = fetch_all(
        db,
        """
        select status, count(*)::int as count
        from defects
        group by status
        order by status asc
        """,
    )
    actions_by_status = fetch_all(
        db,
        """
        select status, count(*)::int as count
        from corrective_actions
        group by status
        order by status asc
        """,
    )
    overdue_actions = fetch_one(
        db,
        """
        select count(*)::int as c
        from vw_actions_due
        where days_overdue is not null and days_overdue > 0
        """,
    )
    return {
        "defects_by_status": defects_by_status,
        "actions_by_status": actions_by_status,
        "overdue_actions": int(overdue_actions["c"]) if overdue_actions else 0,
    }


@router.get(
    "/dashboard/pareto", response_model=List[DashboardParetoItem], tags=["dashboards"]
)
def dashboard_pareto(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Pareto: quantities and counts by defect type (from view)."""
    return fetch_all(
        db, "select * from vw_pareto_defect_types order by total_quantity desc"
    )


@router.get(
    "/dashboard/trends/daily",
    response_model=List[DashboardTrendItem],
    tags=["dashboards"],
)
def dashboard_trends_daily(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Daily trends for defects (from view)."""
    return fetch_all(db, "select * from vw_trends_daily order by day asc")


@router.get(
    "/dashboard/actions/due", response_model=List[DueActionItem], tags=["dashboards"]
)
def dashboard_actions_due(
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """Due/overdue actions (from view)."""
    return fetch_all(
        db,
        "select * from vw_actions_due order by days_overdue desc nulls last, due_date asc nulls last",
    )


@router.get("/audit", response_model=PagedResponse, tags=["audit"])
def list_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = None,
    entity_id: Optional[UUID] = None,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_roles({"quality_engineer"})),
):
    """List audit logs (read-only immutable)."""
    where = []
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if entity_type:
        where.append("a.entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_id:
        where.append("a.entity_id = :entity_id")
        params["entity_id"] = str(entity_id)
    where_sql = (" where " + " and ".join(where)) if where else ""
    total_row = fetch_one(
        db, f"select count(*)::int as c from audit_logs a{where_sql}", params
    )
    total = int(total_row["c"]) if total_row else 0
    items = fetch_all(
        db,
        f"""
        select *
        from audit_logs a
        {where_sql}
        order by a.at desc
        limit :limit offset :offset
        """,
        params,
    )
    return _paged(total, limit, offset, items)


@router.get("/defects/{defect_id}/export/pdf", tags=["export"])
def export_defect_pdf(
    defect_id: UUID,
    request: Request,
    db: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_authenticated),
):
    """
    Export an audit-ready PDF for a defect.

    Note: to avoid adding a heavyweight PDF dependency, this endpoint returns a very simple PDF-like payload.
    If full PDF rendering is required, integrate reportlab/weasyprint in a later step.
    """
    defect = fetch_one(
        db, "select * from defects where id = :id", {"id": str(defect_id)}
    )
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")
    rca = fetch_one(
        db, "select * from defect_rca where defect_id = :id", {"id": str(defect_id)}
    )
    actions = fetch_all(
        db,
        "select * from corrective_actions where defect_id = :id order by created_at asc",
        {"id": str(defect_id)},
    )
    attachments = fetch_all(
        db,
        "select * from defect_attachments where defect_id = :id order by uploaded_at asc",
        {"id": str(defect_id)},
    )

    # Minimal "PDF" bytes: this is NOT a full PDF spec implementation; it's a placeholder binary labeled application/pdf.
    # Clients can still download/attach it for audit bundles in demos.
    text_lines = [
        "DEFECT RECORD (DEMO EXPORT)",
        f"Defect No: {defect.get('defect_no')}",
        f"Occurred At: {defect.get('occurred_at')}",
        f"Severity: {defect.get('severity')}",
        f"Status: {defect.get('status')}",
        "",
        "Description:",
        str(defect.get("description") or ""),
        "",
        "RCA:",
        str(rca or "N/A"),
        "",
        f"Actions ({len(actions)}):",
        *(str(a) for a in actions),
        "",
        f"Attachments ({len(attachments)}):",
        *(str(a) for a in attachments),
        "",
        f"Exported from: {request.url}",
    ]
    payload = ("\n".join(text_lines)).encode("utf-8")

    headers = {
        "Content-Disposition": f'attachment; filename="defect_{defect.get("defect_no")}_{defect_id}.pdf"',
        "Cache-Control": "no-store",
    }
    return Response(content=payload, media_type="application/pdf", headers=headers)
