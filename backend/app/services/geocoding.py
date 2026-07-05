"""Nominatim geocoding with a PostGIS-backed cache.

Addresses are geocoded once and cached in ``geocode_cache`` keyed by a
normalized address string, so re-running extract on the same tour (or across
overlapping tours) costs no extra Nominatim calls. Any failure yields ``None``
— the stop simply stays ungeocoded (its lat/lng are null on the map) rather
than failing the request.

Nominatim's usage policy requires a descriptive ``User-Agent`` and asks for at
most one request per second; volumes here are low (5–12 stops per tour, most
served from cache).
"""

from __future__ import annotations

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.geocode_cache import GeocodeCache

_USER_AGENT = (
    "el-service-routing/0.1 (field-service routing; +https://el-service.example)"
)

# (lon, lat) — PostGIS point order.
Coordinate = tuple[float, float]


def _normalize(
    street: str | None, postal_code: str | None, city: str | None, country: str
) -> str | None:
    parts = [p.strip() for p in (street, postal_code, city, country) if p and p.strip()]
    if not parts:
        return None
    return ", ".join(parts).lower()


def geocode_address(
    db: Session,
    street: str | None,
    postal_code: str | None,
    city: str | None,
    *,
    country: str = "Germany",
    timeout: float = 10.0,
) -> Coordinate | None:
    """Return the (lon, lat) of an address, caching the result. None on failure."""
    normalized = _normalize(street, postal_code, city, country)
    if normalized is None:
        return None

    cached = db.execute(
        select(func.ST_X(GeocodeCache.geom), func.ST_Y(GeocodeCache.geom)).where(
            GeocodeCache.normalized_address == normalized
        )
    ).first()
    if cached is not None:
        return (cached[0], cached[1])

    params: dict[str, str | int] = {
        "format": "json",
        "limit": 1,
        "countrycodes": "de",
    }
    if street:
        params["street"] = street
    if postal_code:
        params["postalcode"] = postal_code
    if city:
        params["city"] = city

    try:
        response = httpx.get(
            f"{settings.nominatim_url}/search",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    if not results:
        return None
    try:
        lon = float(results[0]["lon"])
        lat = float(results[0]["lat"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    db.add(
        GeocodeCache(
            normalized_address=normalized,
            geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
            provider="nominatim",
        )
    )
    db.flush()
    return (lon, lat)
