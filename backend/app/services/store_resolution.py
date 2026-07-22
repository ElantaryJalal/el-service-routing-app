"""Commit-time store resolution: plan rows resolve against the store catalog
before anything else.

The catalog holds verified stores; the plan is the less reliable source. Each
unlinked row runs a conservative cascade:

1. exact order_no ("Auftrag/VST", the branch number printed on the plan) —
   used only when history maps that number to exactly one store, so a reused
   or per-tour number can never mislink;
2. normalized claimed-address fuzzy match (rapidfuzz token_sort_ratio);
3. geospatial: the claim's geocode within GEO_RADIUS_M of a store.

MATCHING IS CONSERVATIVE. Ambiguity (several accepted candidates, or a fuzzy
score in the grey band) is returned as a review item and never auto-linked: a
false link silently sends a crew to the wrong store, which is far worse than
asking the dispatcher. A row that matches nothing becomes a *candidate new
store* (address_provenance='geocoded') and is reported, not silently inserted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

from geoalchemy2.elements import WKTElement
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.stop import Stop
from app.models.store import AddressProvenance, GeomProvenance, Store

# token_sort_ratio at or above this links outright (unless several stores hit).
FUZZY_ACCEPT = 90.0
# Scores in [FUZZY_REVIEW, FUZZY_ACCEPT) are the grey band: never auto-linked,
# always surfaced for the dispatcher.
FUZZY_REVIEW = 85.0
# A geocoded claim within this distance of a store's geometry is that store.
GEO_RADIUS_M = 50.0

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_address(
    street: str | None, postal_code: str | None, city: str | None
) -> str:
    """One comparable line: lowercased, punctuation-free, straße folded to str."""
    parts = " ".join(p for p in (street, postal_code, city) if p)
    lowered = _PUNCT.sub(" ", parts.casefold())
    lowered = lowered.replace("strasse", "str").replace("straße", "str")
    return _WS.sub(" ", lowered).strip()


def _store_address(store: Store) -> str:
    return normalize_address(store.street, store.postal_code, store.city)


def claim_matches_store(stop: Stop, store: Store) -> bool | None:
    """Does the plan's claim agree with the store's verified address?

    Compares only the fields the plan actually printed (a blank cell is not a
    contradiction); every printed field must agree after normalization. None
    when the plan printed no address at all — nothing to check.
    """

    def norm(value: str | None) -> str:
        return normalize_address(value, None, None)

    checks: list[bool] = []
    if stop.claimed_street:
        checks.append(norm(stop.claimed_street) == norm(store.street))
    if stop.claimed_postal_code:
        checks.append(
            stop.claimed_postal_code.strip() == (store.postal_code or "").strip()
        )
    if stop.claimed_city:
        checks.append(norm(stop.claimed_city) == norm(store.city))
    if not checks:
        return None
    return all(checks)


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    h = (
        sin(radians(lat2 - lat1) / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371000.0 * asin(sqrt(h))


@dataclass
class Candidate:
    store: Store
    score: float  # fuzzy score, or 100 for exact rules
    rule: str  # order_no | address | proximity


@dataclass
class Resolution:
    """Outcome for one row. 'linked' and 'created' carry the store;
    'ambiguous' carries the candidates for the dispatcher to resolve;
    'unresolved' is a row with nothing to match or create from."""

    outcome: str  # linked | created | ambiguous | unresolved
    store: Store | None = None
    rule: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str | None = None


def order_no_index(db: Session) -> dict[str, int]:
    """order_no -> store_id, only where history is unanimous.

    The plan's "Auftrag/VST" column is the branch number, which the data shows
    mapping 1:1 to stores. Guarded anyway: a number that ever pointed at two
    different stores is dropped, so if the numbers turn out per-tour the rule
    silently stops matching instead of mislinking.
    """
    rows = db.execute(
        select(Stop.order_no, func.count(func.distinct(Stop.store_id)))
        .where(
            Stop.store_id.isnot(None),
            Stop.order_no.isnot(None),
            Stop.order_no != "",
        )
        .group_by(Stop.order_no)
    ).all()
    unanimous = {order_no for order_no, stores in rows if stores == 1}
    if not unanimous:
        return {}
    pairs = db.execute(
        select(Stop.order_no, Stop.store_id)
        .where(Stop.order_no.in_(unanimous), Stop.store_id.isnot(None))
        .distinct()
    ).all()
    return dict(pairs)


def store_coords(db: Session, stores: list[Store]) -> dict[int, tuple[float, float]]:
    ids = [s.id for s in stores if s.geom is not None]
    if not ids:
        return {}
    rows = db.execute(
        select(Store.id, func.ST_X(Store.geom), func.ST_Y(Store.geom)).where(
            Store.id.in_(ids)
        )
    ).all()
    return {sid: (lon, lat) for sid, lon, lat in rows}


def resolve_stop(
    stop: Stop,
    stores: list[Store],
    *,
    by_order_no: dict[str, int],
    coords: dict[int, tuple[float, float]],
    claim_coord: tuple[float, float] | None,
) -> Resolution:
    """Run the cascade for one unlinked stop. Pure matching — no DB writes,
    no geocoding (the caller controls when a geocode is worth spending)."""
    store_by_id = {s.id: s for s in stores}

    # 1. Exact order_no (branch number), only where history is unanimous.
    order_no = (stop.order_no or "").strip()
    if order_no and order_no in by_order_no:
        store = store_by_id.get(by_order_no[order_no])
        if store is not None:
            return Resolution(outcome="linked", store=store, rule="order_no")

    # 2. Normalized address fuzzy match.
    claim = normalize_address(
        stop.claimed_street, stop.claimed_postal_code, stop.claimed_city
    )
    if claim:
        scored = sorted(
            (
                Candidate(
                    store=s, score=fuzz.token_sort_ratio(claim, addr), rule="address"
                )
                for s in stores
                if (addr := _store_address(s))
            ),
            key=lambda c: c.score,
            reverse=True,
        )
        accepted = [c for c in scored if c.score >= FUZZY_ACCEPT]
        grey = [c for c in scored if FUZZY_REVIEW <= c.score < FUZZY_ACCEPT]
        if len(accepted) == 1:
            return Resolution(outcome="linked", store=accepted[0].store, rule="address")
        if len(accepted) > 1:
            return Resolution(
                outcome="ambiguous",
                candidates=accepted,
                reason="several stores match the claimed address equally well",
            )
        if grey:
            return Resolution(
                outcome="ambiguous",
                candidates=grey[:3],
                reason="claimed address is close to a store but not close enough"
                " to link safely",
            )

    # 3. Geospatial: the claim's geocode sits on top of a store.
    if claim_coord is not None:
        lon, lat = claim_coord
        near = [
            Candidate(store=store_by_id[sid], score=100.0, rule="proximity")
            for sid, (slon, slat) in coords.items()
            if _haversine_m(lon, lat, slon, slat) <= GEO_RADIUS_M
        ]
        if len(near) == 1:
            return Resolution(outcome="linked", store=near[0].store, rule="proximity")
        if len(near) > 1:
            return Resolution(
                outcome="ambiguous",
                candidates=near,
                reason=f"claimed address geocodes within {GEO_RADIUS_M:.0f} m"
                " of several stores",
            )

    return Resolution(outcome="unresolved")


def create_store_from_claim(
    stop: Stop, claim_coord: tuple[float, float] | None
) -> Store:
    """A row that matched nothing is a candidate new store — created from the
    claim, marked geocoded (never verified), and reported for review."""
    store = Store(
        name=(stop.customer or "").strip() or "Unknown store",
        street=stop.claimed_street,
        postal_code=stop.claimed_postal_code,
        city=stop.claimed_city,
        address_provenance=(
            AddressProvenance.geocoded
            if claim_coord is not None
            else AddressProvenance.printed
        ),
    )
    if claim_coord is not None:
        lon, lat = claim_coord
        store.geom = WKTElement(f"POINT({lon} {lat})", srid=4326)
        store.geom_provenance = GeomProvenance.geocoded
    return store
