"""Best-effort opening-hours lookup via OSM/Overpass.

`fetch_opening_hours` finds a nearby shop node with an `opening_hours` tag and
returns its weekday (Mon–Fri) opening/closing pair. It is deliberately
forgiving: any error, timeout, or unparseable value yields None so callers can
treat hours as unknown rather than failing.

The parser handles the common German-retail shapes only (e.g.
"Mo-Fr 08:00-20:00", "Mo-Sa 07:00-22:00; Su off"). Full opening_hours syntax
(https://wiki.openstreetmap.org/wiki/Key:opening_hours) is out of scope.
"""

from __future__ import annotations

import re
from datetime import time

import httpx

from app.config import settings

# Mon..Sun -> index 0..6; weekdays are 0..4.
_DAY_INDEX = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_WEEKDAYS = frozenset(range(5))

_TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_DAY_TOKEN = re.compile(r"(Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*-\s*(Mo|Tu|We|Th|Fr|Sa|Su))?")

OpeningWindow = tuple[time, time]


def _clamp_time(hour: int, minute: int) -> time:
    # opening_hours allows 24:00 as "end of day"; map it to 23:59.
    if hour >= 24:
        return time(23, 59)
    return time(hour, minute)


def _days_for_rule(rule: str) -> set[int]:
    days: set[int] = set()
    for start, end in _DAY_TOKEN.findall(rule):
        s = _DAY_INDEX[start]
        if end:
            e = _DAY_INDEX[end]
            if s <= e:
                span = list(range(s, e + 1))
            else:  # wrap-around, e.g. Sa-Mo
                span = list(range(s, 7)) + list(range(0, e + 1))
            days.update(span)
        else:
            days.add(s)
    return days


def parse_opening_hours(value: str) -> OpeningWindow | None:
    """Parse an opening_hours tag into a weekday (Mon–Fri) [open, close] pair."""
    if not value:
        return None

    value = value.strip()
    if value == "24/7":
        return (time(0, 0), time(23, 59))

    for rule in value.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        lowered = rule.lower()
        if "off" in lowered or "closed" in lowered:
            continue

        ranges = _TIME_RANGE.findall(rule)
        if not ranges:
            continue

        days = _days_for_rule(rule)
        # A rule with no day selector applies to every day, weekdays included.
        if days and not (days & _WEEKDAYS):
            continue

        opens = [_clamp_time(int(h1), int(m1)) for h1, m1, _, _ in ranges]
        closes = [_clamp_time(int(h2), int(m2)) for _, _, h2, m2 in ranges]
        return (min(opens), max(closes))

    return None


def fetch_opening_hours(
    lon: float,
    lat: float,
    *,
    radius_m: int = 60,
    timeout: float = 10.0,
    overpass_url: str | None = None,
) -> OpeningWindow | None:
    """Look up nearby shop opening hours. Returns None on any failure."""
    url = overpass_url or settings.overpass_url
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f"("
        f'node(around:{radius_m},{lat},{lon})["shop"]["opening_hours"];'
        f'way(around:{radius_m},{lat},{lon})["shop"]["opening_hours"];'
        f");"
        f"out tags center 20;"
    )

    try:
        response = httpx.post(url, data={"data": query}, timeout=timeout)
        response.raise_for_status()
        elements = response.json().get("elements", [])
    except (httpx.HTTPError, ValueError):
        return None

    # Prefer explicit supermarkets, then any shop.
    def sort_key(el: dict) -> int:
        return 0 if el.get("tags", {}).get("shop") == "supermarket" else 1

    for element in sorted(elements, key=sort_key):
        tag = element.get("tags", {}).get("opening_hours")
        if not tag:
            continue
        window = parse_opening_hours(tag)
        if window is not None:
            return window

    return None
