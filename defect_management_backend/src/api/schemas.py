from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WorkflowStatus = Literal["open", "in_review", "rca_required", "closed"]
DefectSeverity = Literal["low", "medium", "high", "critical"]
ActionStatus = Literal["open", "in_progress", "done", "verified", "cancelled"]


class PageMeta(BaseModel):
    limit: int = Field(..., description="Page size limit applied")
    offset: int = Field(..., description="Offset applied")
    total: int = Field(..., description="Total matching rows (when available)")


class PagedResponse(BaseModel):
    meta: PageMeta
    items: List[Dict[str, Any]]


class ConfigItem(BaseModel):
    id: UUID
    code: Optional[str] = None
    name: str
    is_active: bool = True


class DefectCreate(BaseModel):
    occurred_at: datetime = Field(..., description="When the defect occurred")
    line_id: UUID
    shift_id: UUID
    part_id: Optional[UUID] = None
    defect_type_id: UUID
    quantity: int = Field(1, ge=1)
    description: Optional[str] = None
    station: Optional[str] = None
    plant: Optional[str] = None


class DefectUpdate(BaseModel):
    occurred_at: Optional[datetime] = None
    line_id: Optional[UUID] = None
    shift_id: Optional[UUID] = None
    part_id: Optional[UUID] = None
    defect_type_id: Optional[UUID] = None
    severity: Optional[DefectSeverity] = None
    quantity: Optional[int] = Field(None, ge=1)
    description: Optional[str] = None
    station: Optional[str] = None
    plant: Optional[str] = None
    status: Optional[WorkflowStatus] = None


class DefectOut(BaseModel):
    id: UUID
    defect_no: int
    occurred_at: datetime
    reported_at: datetime
    line_id: UUID
    shift_id: UUID
    part_id: Optional[UUID]
    defect_type_id: UUID
    severity: DefectSeverity
    quantity: int
    description: Optional[str]
    station: Optional[str]
    status: WorkflowStatus
    plant: Optional[str]
    created_at: datetime
    updated_at: datetime


class WhyAnalysisItem(BaseModel):
    text: str = Field(..., description="One why statement")


class RcaUpsert(BaseModel):
    problem_statement: Optional[str] = None
    root_cause: Optional[str] = None
    containment_action: Optional[str] = None
    why_analysis: List[str] = Field(
        default_factory=list, description="List of '5 whys' entries"
    )
    contributing_factors: Optional[str] = None
    completed: bool = Field(False, description="If true, marks RCA completed")


class RcaOut(BaseModel):
    id: UUID
    defect_id: UUID
    problem_statement: Optional[str]
    root_cause: Optional[str]
    containment_action: Optional[str]
    why_analysis: List[Any]
    contributing_factors: Optional[str]
    completed_by: Optional[UUID]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ActionCreate(BaseModel):
    defect_id: UUID
    title: str
    description: Optional[str] = None
    owner_user_id: Optional[UUID] = None
    due_date: Optional[date] = None


class ActionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    owner_user_id: Optional[UUID] = None
    due_date: Optional[date] = None
    status: Optional[ActionStatus] = None
    verified: Optional[bool] = Field(
        None, description="If true sets verified_at/by; if false clears verification"
    )


class ActionOut(BaseModel):
    id: UUID
    defect_id: UUID
    rca_id: Optional[UUID]
    title: str
    description: Optional[str]
    owner_user_id: Optional[UUID]
    due_date: Optional[date]
    status: ActionStatus
    closed_at: Optional[datetime]
    verified_by: Optional[UUID]
    verified_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class AttachmentCreate(BaseModel):
    """
    Metadata-only attachment creation.

    The binary upload is expected to be handled via Supabase Storage from the frontend.
    Backend stores metadata and ties it to the defect.
    """

    defect_id: UUID
    bucket: Optional[str] = Field(None, description="Supabase bucket")
    object_key: str = Field(..., description="Path/key in storage")
    url: Optional[str] = Field(None, description="Public or signed URL if applicable")
    content_type: Optional[str] = None
    bytes: Optional[int] = Field(None, ge=0)


class AttachmentOut(BaseModel):
    id: UUID
    defect_id: UUID
    storage_provider: str
    bucket: Optional[str]
    object_key: str
    url: Optional[str]
    content_type: Optional[str]
    bytes: Optional[int]
    uploaded_by: Optional[UUID]
    uploaded_at: datetime


class AuditLogOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: Optional[UUID]
    action: str
    actor_user_id: Optional[UUID]
    at: datetime
    ip: Optional[str]
    user_agent: Optional[str]
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    meta: Dict[str, Any]


class DashboardParetoItem(BaseModel):
    defect_type_id: UUID
    defect_type_name: str
    total_quantity: int
    defect_count: int


class DashboardTrendItem(BaseModel):
    day: date
    defect_count: int
    total_quantity: int


class DueActionItem(BaseModel):
    corrective_action_id: UUID
    defect_id: UUID
    title: str
    due_date: Optional[date]
    status: str
    days_overdue: Optional[int]
