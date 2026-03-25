from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from src.api.routers import router as api_router
from src.core.config import load_settings


openapi_tags = [
    {"name": "health", "description": "Health, readiness, and environment diagnostics."},
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

    Integration notes (04.01 placeholders):
    - DB connectivity is required to serve most API routes.
    - Supabase configuration can be placeholder values to boot the service and serve
      non-auth endpoints, but auth-protected endpoints require real Supabase credentials
      unless AUTH_DISABLED=true (DEV ONLY).

    CORS is configured via:
    - ALLOWED_ORIGINS (comma-separated)
    - ALLOWED_METHODS
    - ALLOWED_HEADERS
    - CORS_MAX_AGE (seconds)
    """
    settings = load_settings()

    app = FastAPI(
        title="Manufacturing Defect Management API",
        description=(
            "Backend service for defect logging, RCA capture, corrective actions workflow, dashboards, and audit export.\n\n"
            "Authentication: Supabase JWT via `Authorization: Bearer <access_token>`.\n"
            "RBAC: Roles resolved from PostgreSQL tables (`users`, `roles`, `user_roles`).\n\n"
            "Dev/Integration:\n"
            "- Set AUTH_DISABLED=true to bypass auth for local demos (never enable in production).\n"
            "- If SUPABASE_URL/SUPABASE_KEY are placeholders, auth-protected endpoints will fail.\n"
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
        max_age=int(os.environ.get("CORS_MAX_AGE", "600")),
    )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", tags=["health"])
    def health_check():
        """Health check endpoint."""
        return {"message": "Healthy"}

    @app.get("/health/ready", tags=["health"])
    def readiness():
        """
        Readiness/diagnostics endpoint (no DB query).

        Returns key integration settings (redacted) so containers can be wired up
        using placeholders and still verify configuration flow.
        """
        supabase_is_placeholder = settings.supabase_anon_key.startswith("placeholder") or "placeholder" in settings.supabase_url
        return {
            "status": "ready",
            "database_url_set": bool(settings.database_url),
            "auth_disabled": settings.auth_disabled,
            "supabase_url": settings.supabase_url,
            "supabase_configured": not supabase_is_placeholder,
            "cors": {
                "allowed_origins": settings.allowed_origins,
                "allowed_methods": settings.allowed_methods,
                "allowed_headers": settings.allowed_headers,
            },
        }

    @app.get("/docs/auth", response_class=PlainTextResponse, tags=["health"])
    def auth_docs():
        """Notes on how to call the API with Supabase JWTs (or how to disable auth in dev)."""
        return (
            "Auth usage:\n"
            "- Obtain a Supabase access token from the frontend login.\n"
            "- Call API endpoints with header:\n"
            "    Authorization: Bearer <access_token>\n\n"
            "RBAC:\n"
            "- Backend maps token 'sub' (Supabase user id) to `users.supabase_uid`.\n"
            "- Roles are granted via `user_roles` -> `roles.name`.\n\n"
            "Dev bypass (NEVER in production):\n"
            "- Set AUTH_DISABLED=true to bypass Supabase JWT verification and RBAC.\n"
        )

    return app


app = create_app()
