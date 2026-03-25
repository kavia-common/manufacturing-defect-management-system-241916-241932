# manufacturing-defect-management-system-241916-241932

## Integration notes (step 04.01 placeholders)

This workspace contains the **backend** container (`defect_management_backend`). It depends on:

- `defect_management_database` (PostgreSQL) workspace (sibling folder)
- `defect_management_frontend` (Next.js) workspace (sibling folder)
- Supabase (3rd party) for authentication + storage (credentials may be placeholders for now)

### Environment variables (backend)

Create/set `defect_management_backend/.env` from `.env.example`.

Required:
- `DATABASE_URL` (recommended): `postgresql+psycopg://...`
  - If not set, backend will attempt to locate the database container’s `db_connection.txt`
    by scanning sibling workspaces and convert `postgresql://` to `postgresql+psycopg://`.

Supabase (can be placeholders to boot the service):
- `SUPABASE_URL`
- `SUPABASE_KEY`

CORS:
- `ALLOWED_ORIGINS` (comma-separated)

### Making non-auth flows operable

For local demos / CI wiring with placeholders:
- Set `AUTH_DISABLED=true` in backend `.env` to bypass JWT verification and RBAC.
- Use `GET /health/ready` to verify env wiring (no DB query).

Where real Supabase is required:
- Any endpoint that requires authentication when `AUTH_DISABLED` is not enabled.
- JWT verification needs a real Supabase project URL (JWKS endpoint must resolve).

Frontend environment reference (in its container):
- `NEXT_PUBLIC_API_BASE_URL` should point to the backend base URL (e.g. `http://localhost:8000`)
- `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` should be set for real auth.

Supabase JWT verification defaults (backend):
- JWKS: `${SUPABASE_URL}/auth/v1/keys`
- Issuer: `${SUPABASE_URL}/auth/v1`
- Audience: not enforced (Supabase access tokens may vary); backend disables aud verification by default.