# Infra — EL Service Routing App

docker-compose stack for local development and deployment:

- **PostgreSQL + PostGIS** — primary database (Phase 1).
- **OSRM** — routing engine (Phase 2).
- **Vroom** — vehicle-routing optimisation over OSRM (Phase 2).

## Usage

```bash
docker compose -f infra/docker-compose.yml up -d
```

The database is published on host port **5432** by default. If that port is
already in use, set `POSTGRES_HOST_PORT` (e.g. `5433`) and update the port in
the backend's `DATABASE_URL` to match:

```bash
POSTGRES_HOST_PORT=5433 docker compose -f infra/docker-compose.yml up -d
```

> OSRM and Vroom services are added in Phase 2.
