"""FastAPI application entrypoint for the EL Service routing API.

Feature endpoints (extraction, geocoding, routing) are added in later phases.
For now this exposes a health check that also verifies the database connection
and that PostGIS is available.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import feedback_router, stops_router, stores_router, tours_router
from app.config import settings
from app.db import engine

app = FastAPI(title="EL Service Routing API", version="0.1.0")

# Allow browser clients (the web build / dashboard) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tours_router)
app.include_router(stops_router)
app.include_router(stores_router)
app.include_router(feedback_router)

# Uploaded visit-feedback photos; photo_path values are relative URLs under
# this mount ("media/feedback/<uuid>.jpg").
Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")


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
