from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from src.api.routers import router as api_router
from src.core.config import load_settings


openapi_tags = [
    {"name": "configs", "description": "Configuration master data (defect types, lines, shifts, parts, severity rules)."},
    {"name": "defects", "description": "Defect logging, listing, updating, and history."},
    {"name": "rca", "description": "Root Cause Analysis (RCA) capture and completion."},
    {"name": "actions", "description": "Corrective actions workflow and status history."},
    {"name": "dashboards", "description": "Dashboard data (Pareto, trends, due actions) backed by DB views."},
    {"name": "audit", "description": "Audit log read APIs (immutable audit trail)."},
    {"name": "uploads", "description": "Attachment metadata. Binary upload is performed via Supabase Storage client-side."},
    {"name": "export", "description": "Exports (PDF)."},
]


def create_app() -> FastAPI:
    """
    Create the FastAPI application.

    - Validates Supabase JWT via Authorization: Bearer <token>
    - Enforces RBAC via Postgres `users/roles/user_roles` tables
    - Provides REST APIs for defect management backed by PostgreSQL
    """
    settings = load_settings()

    app = FastAPI(
        title="Manufacturing Defect Management API",
        description=(
            "Backend service for defect logging, RCA capture, corrective actions workflow, dashboards, and audit export.\n\n"
            "Authentication: Supabase JWT via `Authorization: Bearer <access_token>`.\n"
            "RBAC: Roles resolved from PostgreSQL tables (`users`, `roles`, `user_roles`)."
        ),
        version="0.1.0",
        openapi_tags=openapi_tags,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins or ["*"],
        allow_credentials=True,
        allow_methods=settings.allowed_methods or ["*"],
        allow_headers=settings.allowed_headers or ["*"],
        max_age=int(__import__("os").environ.get("CORS_MAX_AGE", "600")),
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", tags=["health"])
    def health_check():
        """Health check endpoint."""
        return {"message": "Healthy"}

    @app.get("/docs/auth", response_class=PlainTextResponse, tags=["health"])
    def auth_docs():
        """Notes on how to call the API with Supabase JWTs."""
        return (
            "Auth usage:\n"
            "- Obtain a Supabase access token from the frontend login.\n"
            "- Call API endpoints with header:\n"
            "    Authorization: Bearer <access_token>\n\n"
            "RBAC:\n"
            "- Backend maps token 'sub' (Supabase user id) to `users.supabase_uid`.\n"
            "- Roles are granted via `user_roles` -> `roles.name`.\n"
        )

    return app


app = create_app()
