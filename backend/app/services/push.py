"""Send Expo push notifications to a user's registered devices.

Notifications are a courtesy channel on top of the app's pull-based refresh
(the worker home screen re-fetches on focus/foreground), so delivery is
strictly best-effort: :func:`notify_user` never raises, and endpoints call it
via ``BackgroundTasks`` so a slow or down push service cannot delay or fail
the API response. It opens its own database session because background tasks
run after the request's session is closed.

Expo's push API (https://exp.host/--/api/v2/push/send) takes a JSON array of
messages and returns one ticket per message in order. A ticket error of
``DeviceNotRegistered`` means the app was uninstalled or the token revoked —
that row is pruned so dead tokens don't accumulate.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models.push_token import PushToken

logger = logging.getLogger(__name__)

# Expo accepts at most 100 messages per request.
_BATCH_SIZE = 100


def _post_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """POST one batch to the Expo push API; returns the per-message tickets."""
    response = httpx.post(
        f"{settings.expo_push_url}/--/api/v2/push/send",
        json=messages,
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    return data if isinstance(data, list) else []


def notify_user(
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> int:
    """Push ``title``/``body`` to every device of the user; returns the number
    of accepted messages. Best-effort by contract: any failure is logged and
    swallowed."""
    try:
        with SessionLocal() as db:
            tokens = list(
                db.scalars(select(PushToken).where(PushToken.user_id == user_id))
            )
            if not tokens:
                return 0

            accepted = 0
            for start in range(0, len(tokens), _BATCH_SIZE):
                batch = tokens[start : start + _BATCH_SIZE]
                tickets = _post_messages(
                    [
                        {
                            "to": row.token,
                            "title": title,
                            "body": body,
                            "sound": "default",
                            **({"data": data} if data else {}),
                        }
                        for row in batch
                    ]
                )
                for row, ticket in zip(batch, tickets, strict=False):
                    if ticket.get("status") == "ok":
                        accepted += 1
                    elif (
                        ticket.get("details", {}).get("error") == "DeviceNotRegistered"
                    ):
                        db.delete(row)
            db.commit()
            return accepted
    except Exception:
        logger.exception("push delivery to user %s failed", user_id)
        return 0
