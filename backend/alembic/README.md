# Alembic migrations

Run from `backend/` with the venv active and `DATABASE_URL` set in `.env`.

```powershell
# Apply all migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Roll back one revision
alembic downgrade -1
```

`env.py` reads `DATABASE_URL` from `app.config.get_settings()` and binds to `app.db.base.Base.metadata`. New models must be imported in `env.py` (see the `from app.db import models` line) for autogeneration to detect them.

## Audit log append-only role

Migration `0001_initial` creates a Postgres role `jarvis_audit_writer` with INSERT+SELECT only on `audit_log`, plus a trigger blocking UPDATE/DELETE on that table. The application connects as the regular app role for everything except audit writes; audit writes go through a dedicated connection using `jarvis_audit_writer`. See [`docs/SECURITY.md`](../../docs/SECURITY.md).
