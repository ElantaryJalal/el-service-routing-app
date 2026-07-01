"""Thin OSRM client.

Currently wraps the `/table` service to fetch a duration matrix. OSRM is fast
and stateless, so nothing is cached here.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.config import settings

# (longitude, latitude), matching OSRM's coordinate order.
Coordinate = tuple[float, float]


class OSRMError(RuntimeError):
    """Raised when OSRM returns an error or is unreachable."""


class OSRMClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 30.0) -> None:
        self.base_url = (base_url or settings.osrm_url).rstrip("/")
        self.timeout = timeout

    def duration_matrix(
        self,
        coordinates: Sequence[Coordinate],
        *,
        profile: str = "driving",
    ) -> list[list[float]]:
        """Return an N×N matrix of travel times in seconds.

        `coordinates` is a sequence of (lon, lat) pairs. Entry [i][j] is the
        driving time from coordinate i to coordinate j.
        """
        if not coordinates:
            raise ValueError("coordinates must be non-empty")

        coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coordinates)
        url = f"{self.base_url}/table/v1/{profile}/{coord_str}"

        try:
            response = httpx.get(
                url, params={"annotations": "duration"}, timeout=self.timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OSRMError(f"OSRM request failed: {exc}") from exc

        data = response.json()
        if data.get("code") != "Ok":
            raise OSRMError(
                f"OSRM returned code={data.get('code')!r}: {data.get('message')}"
            )

        return data["durations"]
