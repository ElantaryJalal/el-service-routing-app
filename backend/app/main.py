"""FastAPI application entrypoint for the EL Service routing API.

Feature endpoints (extraction, geocoding, routing) are added in later phases.
For now this exposes a health check that also verifies the database connection
and that PostGIS is available.
"""

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from app.api import stops_router, tours_router
from app.db import engine

app = FastAPI(title="EL Service Routing API", version="0.1.0")

app.include_router(tours_router)
app.include_router(stops_router)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            postgis_version = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            ).scalar()
    except Exception as exc:  # pragma: no cover - surfaced as 503
        raise HTTPException(
            status_code=503, detail=f"database unavailable: {exc}"
        ) from exc

    if postgis_version is None:
        raise HTTPException(status_code=503, detail="postgis extension not installed")

    return {"status": "ok", "database": "ok", "postgis": postgis_version}
