# Backend — EL Service Routing API

FastAPI service: tour-plan extraction (Anthropic Messages API), geocoding
(Nominatim), and route data. PostgreSQL + PostGIS via SQLAlchemy + GeoAlchemy2;
migrations with Alembic; schemas with Pydantic.

## Setup

```bash
# 1. Start Postgres + PostGIS (from repo root)
docker compose -f infra/docker-compose.yml up -d

# 2. Backend env + deps
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e .[dev]
cp .env.example .env                    # then fill in the values

# 3. Apply migrations
alembic upgrade head

# 4. Run the API
uvicorn app.main:app --reload
```

The API is then available at http://localhost:8000 (docs at `/docs`).
`GET /health` returns `{"status": "ok", ...}` once the DB is reachable and
PostGIS is installed.

## Migrations

```bash
alembic upgrade head                    # apply
alembic revision -m "add X"             # new migration (hand-edit as needed)
alembic downgrade -1                    # roll back one
```

## Tooling

- **Format**: `black .`
- **Lint**: `ruff check .`

Both are configured in [`pyproject.toml`](./pyproject.toml).

## Environment

See [`.env.example`](./.env.example). Required keys: `DATABASE_URL`,
`ANTHROPIC_API_KEY`, `EXTRACTION_MODEL`, `NOMINATIM_URL`.
