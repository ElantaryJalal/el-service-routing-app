"""FastAPI application entrypoint for the EL Service routing API.

Feature endpoints (extraction, geocoding, routing) are added in later phases.
For now this exposes only a health check so the app boots and can be deployed.
"""

from fastapi import FastAPI

app = FastAPI(title="EL Service Routing API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
