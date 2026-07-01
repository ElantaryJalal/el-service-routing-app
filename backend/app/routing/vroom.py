"""Thin Vroom client.

POSTs a Vroom problem (vehicles + jobs) to vroom-express and returns the
parsed solution. See https://github.com/VROOM-Project/vroom/blob/master/docs/API.md
for the request/response schema.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class VroomError(RuntimeError):
    """Raised when Vroom returns an error or is unreachable."""


class VroomClient:
    def __init__(self, base_url: str | None = None, *, timeout: float = 60.0) -> None:
        self.base_url = (base_url or settings.vroom_url).rstrip("/")
        self.timeout = timeout

    def solve(self, problem: dict[str, Any]) -> dict[str, Any]:
        """Send a Vroom problem and return the parsed solution.

        `problem` is a dict with at least `vehicles` and `jobs` keys.
        """
        try:
            response = httpx.post(
                f"{self.base_url}/", json=problem, timeout=self.timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VroomError(f"Vroom request failed: {exc}") from exc

        data = response.json()
        # Vroom uses code 0 for success; anything else is an error.
        if data.get("code", 0) != 0:
            raise VroomError(
                f"Vroom returned code={data.get('code')!r}: {data.get('error')}"
            )

        return data
