# EL Service Routing App

Field-service routing for **EL Service GmbH**, a cleaning company. Employees
travel for a week from a hotel base and service 26+ supermarkets (e.g. Aldi Nord
stores around Leipzig), 5–12 per day, finishing every stop before the week ends.

## What the app does

1. An employee photographs a paper tour plan — a printed table with handwritten
   annotations.
2. The app extracts the stops from the photo, geocodes them, and shows an
   optimised multi-day driving route on a map.
3. Tapping a stop reveals its address, tasks, parking info, and a navigate
   button.

## Stack (decided — do not propose alternatives)

- **Monorepo** with folders:
  - `/backend` — Python, FastAPI
  - `/mobile` — Expo / React Native (ships to iOS and Android)
  - `/dashboard` — Next.js (later)
  - `/infra` — docker-compose
- **Database**: PostgreSQL + PostGIS
- **ORM**: SQLAlchemy + GeoAlchemy2
- **Migrations**: Alembic
- **API schemas**: Pydantic
- **Extraction**: vision-capable Claude model via the Anthropic Messages API
  (default `claude-sonnet-5`, swappable via the `EXTRACTION_MODEL` env var)
- **Geocoding**: Nominatim (cached), with a fallback provider later
- **Route optimisation (Phase 2)**: self-hosted OSRM + Vroom in Docker

## Build phases

- **P1 — Core flow**: photo → extract → confirm → geocode → map.
- **P2 — Optimisation**: self-hosted OSRM + Vroom for multi-day route
  optimisation.
- **P3 — Enrichment + dashboard**: richer stop data (tasks, parking) and the
  Next.js dashboard.
- **P4 — Learned service-times**: model per-stop service durations from history
  to improve scheduling.

## Repo layout

```
.
├── backend/      # FastAPI app, SQLAlchemy models, Alembic migrations
├── mobile/       # Expo / React Native client
├── dashboard/    # Next.js dashboard (P3)
├── infra/        # docker-compose: Postgres/PostGIS, OSRM, Vroom
└── CLAUDE.md
```

## Conventions

- Backend formatting/linting: **black** + **ruff** (config in
  `backend/pyproject.toml`).
- Secrets live in `.env` (never committed); see `backend/.env.example` for the
  required keys: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `EXTRACTION_MODEL`,
  `NOMINATIM_URL`.
