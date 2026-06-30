# Backend — EL Service Routing API

FastAPI service: tour-plan extraction (Anthropic Messages API), geocoding
(Nominatim), and route data. PostgreSQL + PostGIS via SQLAlchemy + GeoAlchemy2;
migrations with Alembic; schemas with Pydantic.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e .[dev]
cp .env.example .env                    # then fill in the values
uvicorn app.main:app --reload
```

The API is then available at http://localhost:8000 (docs at `/docs`).

## Tooling

- **Format**: `black .`
- **Lint**: `ruff check .`

Both are configured in [`pyproject.toml`](./pyproject.toml).

## Environment

See [`.env.example`](./.env.example). Required keys: `DATABASE_URL`,
`ANTHROPIC_API_KEY`, `EXTRACTION_MODEL`, `NOMINATIM_URL`.
