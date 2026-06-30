# EL Service Routing App

Field-service routing for EL Service GmbH. Photograph a paper tour plan; the app
extracts the stops, geocodes them, and shows an optimised multi-day driving
route on a map.

See [CLAUDE.md](./CLAUDE.md) for the full vision, stack, and build phases.

## Monorepo layout

| Folder       | Purpose                                            |
| ------------ | -------------------------------------------------- |
| `backend/`   | FastAPI API, SQLAlchemy models, Alembic migrations |
| `mobile/`    | Expo / React Native client (iOS + Android)         |
| `dashboard/` | Next.js dashboard (Phase 3)                        |
| `infra/`     | docker-compose: Postgres/PostGIS, OSRM, Vroom      |

## Getting started

Each subproject has its own README. Start with [`backend/`](./backend/README.md).
