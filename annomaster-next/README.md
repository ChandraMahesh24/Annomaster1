# AnnoMaster-next

Port of AnnoMaster to **FastAPI + Postgres + Celery/Redis** (backend) and
**React + Vite** (frontend). Behaviour parity with the Flask app in the parent
directory is the acceptance bar — see [`../PORT_PLAN.md`](../PORT_PLAN.md).

## Run it (green `/health` needs Postgres + Redis)

```bash
# 1. infrastructure (needs Docker)
docker compose up -d                 # postgres:5432, redis:6379

# 2. backend
cd backend
pip install -r requirements.txt      # installs celery + psycopg (need network)
cp .env.example .env                 # then edit secrets
alembic upgrade head                 # (no-op until models land in A1)
uvicorn app.main:app --reload        # http://localhost:8000  (/docs, /health)

# 3. worker (Smart Detect / export / ffmpeg jobs — bodies land in Phase B)
celery -A app.core.celery_app.celery_app worker -l info

# 4. frontend
cd ../frontend
npm install                          # needs network
npm run dev                          # http://localhost:5173
```

No Docker? Point `DATABASE_URL` / `REDIS_URL` in `.env` at locally-installed or
managed Postgres/Redis instead — the app only cares about the connection URLs.

## Status: Stage A0 (scaffold) — verified

- Backend boots without a DB driver present (lazy engine); `/health` returns a
  well-formed 503 when Postgres/Redis are down, 200 when both are up.
- Alembic is wired to app settings (single source of truth for the DB URL).
- Frontend files are in place; `npm install` + `npm run dev` pending network.

Next: **A1 — data model + first Alembic migration** (all Section-1 entities with
real Postgres CHECK/UNIQUE/FK constraints).
