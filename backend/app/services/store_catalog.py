"""Resolve an extracted stop to a known catalog store (fuzzy name match).

EL Service services a fixed set of ~26 supermarkets, so instead of trusting the
model to read a full address off a photo we match the extracted store name
against the catalog and pull the canonical address, coordinate, and default
tasks from there. Matching is deliberately lightweight — normalized string
similarity (stdlib ``difflib``) over 26 rows, boosted when the postal code or
city agrees — no embeddings/vector store needed at this scale.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service_record import learned_minutes, task_signature
from app.models.store import Store
from app.models.task import Task

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

# Minimum blended score (name similarity + locality boost) to accept a match.
MATCH_THRESHOLD = 0.6

# Chain/format words that don't distinguish one store from another. Street-type
# words are here because aliases often hold full addresses ("Georg-Schwarz-Str.
# 92-96, Leipzig"): "str"/"weg" would otherwise identify a store to any row that
# merely contains an address.
_GENERIC_NAME_TOKENS = {
    "aldi",
    "markt",
    "supermarkt",
    "nord",
    "sud",
    "sued",
    "gmbh",
    "str",
    "strasse",
    "weg",
    "allee",
    "platz",
}


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    lowered = _PUNCT.sub(" ", value.casefold())
    return _WS.sub(" ", lowered).strip()


def _distinctive_tokens(name: str) -> list[str]:
    """The name tokens that actually identify a store (e.g. 'gohlis')."""
    return [
        tok
        for tok in _normalize(name).split()
        if len(tok) >= 3 and not tok.isdigit() and tok not in _GENERIC_NAME_TOKENS
    ]


def _name_similarity(query: str, store: Store) -> float:
    """Best normalized similarity of the query against a store's names.

    Compared on distinctive tokens when both sides have them: chain names
    share a long generic prefix ("Aldi …"), which otherwise inflates the
    similarity of two entirely different branches (e.g. "Aldi Zwickau" vs
    "Aldi Lindenau") past the match threshold.
    """
    query_distinct = " ".join(_distinctive_tokens(query))
    best = 0.0
    for cand in [store.name, *(store.aliases or [])]:
        cand_distinct = " ".join(_distinctive_tokens(cand))
        if query_distinct and cand_distinct:
            ratio = SequenceMatcher(None, query_distinct, cand_distinct).ratio()
        else:
            ratio = SequenceMatcher(None, query, _normalize(cand)).ratio()
        best = max(best, ratio)
    return best


def match_store(
    db: Session,
    name: str | None,
    city: str | None = None,
    postal_code: str | None = None,
    *,
    threshold: float = MATCH_THRESHOLD,
) -> Store | None:
    """Return the best catalog store for an extracted stop, or None.

    Scores each store by normalized name similarity and adds a locality boost:
    +0.3 when the postal code matches exactly, else +0.1 when the city matches.
    A postal code that *contradicts* the store's (each store's PLZ is unique)
    is penalized -0.3: a similar chain name with a different PLZ is almost
    certainly a different branch, and a false match would silently pin the
    stop to the wrong store's coordinate.
    """
    query = _normalize(name)
    if not query:
        return None

    plz = (postal_code or "").strip()
    city_norm = _normalize(city)

    best: Store | None = None
    best_score = 0.0
    for store in db.scalars(select(Store)).all():
        score = _name_similarity(query, store)
        if plz and store.postal_code:
            if plz == store.postal_code.strip():
                score += 0.3
            else:
                score -= 0.3
        elif city_norm and _normalize(store.city) == city_norm:
            score += 0.1
        if score > best_score:
            best, best_score = store, score

    return best if best_score >= threshold else None


def match_store_in_text(
    db: Session,
    text: str,
    postal_code: str | None = None,
    *,
    threshold: float = MATCH_THRESHOLD,
) -> Store | None:
    """Resolve a noisy OCR line (a whole table row) to a catalog store.

    Unlike ``match_store`` (which compares against a clean store name), this
    scans the full line: it looks for each store's distinctive name token
    *inside* the line (tolerating OCR typos via similarity) and anchors on the
    postal code, which OCRs reliably and is unique per store. The postal code
    alone can carry a match even when the name was misread; the name alone
    carries it when the postal code is illegible.
    """
    norm = _normalize(text)
    if not norm:
        return None
    line_tokens = norm.split()
    plz = (postal_code or "").strip()

    best: Store | None = None
    best_score = 0.0
    for store in db.scalars(select(Store)).all():
        exact_hit = False
        fuzzy_name = 0.0
        for name in [store.name, *(store.aliases or [])]:
            for token in _distinctive_tokens(name):
                # Whole-token equality; substring only for tokens long enough
                # not to hide inside unrelated words ("leipzig" still hits the
                # OCR-merged "leipzigleutzsch", but "see" can't hit "kasse").
                if token in line_tokens or (len(token) >= 5 and token in norm):
                    exact_hit = True
                    fuzzy_name = 1.0
                else:
                    fuzzy_name = max(
                        fuzzy_name,
                        max(
                            (
                                SequenceMatcher(None, token, other).ratio()
                                for other in line_tokens
                            ),
                            default=0.0,
                        ),
                    )

        plz_match = bool(plz and store.postal_code and plz == store.postal_code.strip())
        if plz_match:
            # Postal code is the anchor; a fuzzy name only sharpens it. This is
            # what rescues an OCR-mangled name whose postal code read cleanly.
            score = 0.7 + 0.3 * fuzzy_name
        elif exact_hit:
            # No postal match, but a distinctive name token is clearly present.
            score = 0.9
        else:
            # A weak fuzzy name alone (no postal anchor) is not trustworthy.
            score = 0.0
        if score > best_score:
            best, best_score = store, score

    return best if best_score >= threshold else None


def enrich_stop_from_store(stop, store: Store) -> None:
    """Link a draft stop to its matched catalog store and inherit plan data.

    The store is the source of truth for address, coordinate, and hours — the
    stop reads those through its effective_* views, so nothing is copied onto
    the row. The claimed_* fields stay exactly what the plan printed (audit
    trail). Only plan-level data is filled in: default tasks and the service
    estimate.
    """
    stop.store_id = store.id

    if not stop.tasks and store.default_tasks:
        for label in store.default_tasks:
            label = (label or "").strip()
            if label:
                stop.tasks.append(Task(task_type=label, raw_label=label))

    # The learned median from completion history (P4) beats the hand-set
    # default: each week's plan is extracted fresh, so this is where past
    # weeks' actual durations flow into the next tour's schedule. The row's
    # own service profile is matched first — the same store takes a different
    # time depending on which tasks the visit is for.
    if stop.service_minutes is None:
        signature = task_signature(t.task_type for t in stop.tasks)
        profile_minutes = learned_minutes(
            [
                record.duration_minutes
                for record in store.service_records
                if record.task_signature == signature
            ]
        )
        catalog_minutes = (
            profile_minutes
            or store.learned_service_minutes
            or store.default_service_minutes
        )
        if catalog_minutes is not None:
            stop.service_minutes = catalog_minutes
