"""Build the service ledger from history and learn from it (P4).

Two ways a service duration is measured, direct preferred over derived:

DIRECT — the worker taps "Start" then "Done", so both ends are stamped:

    service = completed_at - started_at

No drive term, no dependence on a neighbouring stop — this is the primary
measurement whenever a stop has a ``started_at``.

DERIVED (fallback) — for stops the worker never explicitly started, only the
"done" tap exists, marking the *end* of service. Arrival is never recorded, but
when two stops were completed back to back on the same planned day the gap
between their timestamps is one drive plus one service:

    service(B) = completed_at(B) - completed_at(A) - drive(A -> B)

with the drive leg taken from the OSRM matrix. A derived observation is only
trusted when the two stops are adjacent in the day's planned sequence (a
missing stop in between means an unknown detour) and the resulting duration is
plausible. Both methods apply the same plausibility bounds:

- Near-zero durations are discarded: the offline outbox stamps queued
  completions with the *sync* time, so a reconnecting phone produces a burst of
  completions seconds apart that say nothing about service length.
- Very long durations are discarded: the pair straddled a break, an overnight,
  a forced re-completion days later, or a "Start" left open for hours.

Each surviving observation is persisted as a ``service_records`` row — the
ledger of services actually performed, linking store, tour, responsible team,
tasks, duration, and how it was measured (``measurement_method``). Everything
learned is an aggregate of that ledger:

- the store-wide estimate (median of the store's records, cached on the store
  row) — the fallback for task profiles never seen before;
- per-profile estimates (median per task signature), because one store is not
  one duration: different task profiles — often different teams — take very
  different time at the same market.

Where a store (or a profile) has enough DIRECT records, only those feed the
estimate — a direct measurement never gets diluted by the noisier derived
one; otherwise the two are pooled.

Everything is recomputed from scratch on each run (history is small: one
crew, ~26 stores, weekly tours), triggered via
POST /stores/service-times/recompute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.service_record import (
    MIN_SAMPLES,
    MeasurementMethod,
    ServiceRecord,
    learned_minutes,
    task_signature,
)
from app.models.stop import Stop
from app.models.store import Store
from app.models.task import Task
from app.models.tour import Tour
from app.models.user import User
from app.services.optimiser import MatrixProvider, _osrm_matrix

MIN_SERVICE_MINUTES = 10
MAX_SERVICE_MINUTES = 600  # matches the manual estimate cap on stops


@dataclass
class ServiceProfileTime:
    """One service profile's learned duration at a store."""

    task_signature: str
    tasks_label: str | None
    samples: int
    learned_minutes: int | None


@dataclass
class StoreServiceTime:
    """Per-store outcome of a recompute run, for the office view."""

    store_id: int
    name: str
    samples: int
    learned_service_minutes: int | None
    by_service: list[ServiceProfileTime] = field(default_factory=list)


@dataclass
class Observation:
    """One measured service, ready to be written to the ledger."""

    stop_id: int
    tour_id: int
    store_id: int
    serviced_on: date | None
    minutes: int
    task_signature: str
    tasks_label: str | None
    # How the duration was measured — direct (start/done stamps) or derived
    # (adjacent completions minus the drive leg).
    measurement_method: MeasurementMethod
    # Carried from the stop so a rebuild never launders demo history into
    # real-looking ledger rows.
    is_demo: bool


def _plausible(seconds: float) -> bool:
    """A duration a service could really take — rejects near-zero (offline
    sync bursts) and hours-long (a break, an overnight, a forgotten Start)."""
    return MIN_SERVICE_MINUTES * 60 <= seconds <= MAX_SERVICE_MINUTES * 60


def _completed_day_groups(db: Session) -> list[list]:
    """Completed, located, scheduled stops grouped by (tour, planned day)."""
    # Drive legs are measured between store geometries — the authoritative
    # coordinates the crew actually drove to (claimed_geom is diagnostic).
    rows = db.execute(
        select(
            Stop.id,
            Stop.tour_id,
            Stop.assigned_day,
            Stop.sequence,
            Stop.store_id,
            Stop.completed_at,
            Stop.is_demo,
            func.ST_X(Store.geom).label("lon"),
            func.ST_Y(Store.geom).label("lat"),
        )
        .join(Store, Stop.store_id == Store.id)
        .where(
            Stop.completed_at.isnot(None),
            Stop.assigned_day.isnot(None),
            Stop.sequence.isnot(None),
            Store.geom.isnot(None),
        )
        .order_by(Stop.tour_id, Stop.assigned_day, Stop.sequence)
    ).all()

    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((row.tour_id, row.assigned_day), []).append(row)
    return [group for group in groups.values() if len(group) >= 2]


def _stop_profiles(db: Session, stop_ids: list[int]) -> dict[int, tuple[str, str]]:
    """(task signature, display label) per stop id, from its task rows."""
    rows = db.execute(
        select(Task.stop_id, Task.task_type, Task.raw_label).where(
            Task.stop_id.in_(stop_ids)
        )
    ).all()
    by_stop: dict[int, list[tuple[str, str]]] = {}
    for stop_id, task_type, raw_label in rows:
        by_stop.setdefault(stop_id, []).append((task_type, raw_label or task_type))
    return {
        stop_id: (
            task_signature(t for t, _ in tasks),
            ", ".join(sorted({label for _, label in tasks})),
        )
        for stop_id, tasks in by_stop.items()
    }


def _direct_observations(db: Session) -> list[Observation]:
    """DIRECT services: a stop with both started_at and completed_at gives
    completed_at - started_at — no drive term, no neighbour dependence."""
    rows = db.execute(
        select(
            Stop.id,
            Stop.tour_id,
            Stop.store_id,
            Stop.assigned_day,
            Stop.started_at,
            Stop.completed_at,
            Stop.is_demo,
        ).where(
            Stop.started_at.isnot(None),
            Stop.completed_at.isnot(None),
            Stop.store_id.isnot(None),
        )
    ).all()
    profiles = _stop_profiles(db, [row.id for row in rows])

    observations: list[Observation] = []
    for row in rows:
        service = (row.completed_at - row.started_at).total_seconds()
        # A forgotten Start left open for hours must never enter the ledger.
        if not _plausible(service):
            continue
        signature, label = profiles.get(row.id, ("", None))
        observations.append(
            Observation(
                stop_id=row.id,
                tour_id=row.tour_id,
                store_id=row.store_id,
                serviced_on=row.assigned_day,
                minutes=int(round(service / 60)),
                task_signature=signature,
                tasks_label=label,
                measurement_method=MeasurementMethod.direct,
                is_demo=row.is_demo,
            )
        )
    return observations


def _derived_observations(
    db: Session, matrix_provider: MatrixProvider, skip_stop_ids: set[int]
) -> list[Observation]:
    """DERIVED services: adjacent same-day completions minus the OSRM drive
    leg. One matrix call per (tour, day) group; the observation belongs to the
    *later* stop of each pair. Stops already measured directly are skipped."""
    groups = _completed_day_groups(db)
    profiles = _stop_profiles(db, [row.id for group in groups for row in group])
    observations: list[Observation] = []

    for group in groups:
        matrix = matrix_provider([(row.lon, row.lat) for row in group])
        for index, (prev, cur) in enumerate(zip(group, group[1:], strict=False)):
            # A direct measurement already covers this stop — don't dilute it.
            if cur.id in skip_stop_ids:
                continue
            # Sequence-adjacent only: a gap in the planned order means an
            # uncompleted stop sat between them and the drive is unknown.
            if cur.sequence != prev.sequence + 1 or cur.store_id is None:
                continue
            gap = (cur.completed_at - prev.completed_at).total_seconds()
            service = gap - matrix[index][index + 1]
            if not _plausible(service):
                continue
            signature, label = profiles.get(cur.id, ("", None))
            observations.append(
                Observation(
                    stop_id=cur.id,
                    tour_id=cur.tour_id,
                    store_id=cur.store_id,
                    serviced_on=cur.assigned_day,
                    minutes=int(round(service / 60)),
                    task_signature=signature,
                    tasks_label=label,
                    measurement_method=MeasurementMethod.derived,
                    is_demo=cur.is_demo,
                )
            )

    return observations


def collect_observations(
    db: Session, matrix_provider: MatrixProvider | None = None
) -> list[Observation]:
    """Every measurable service — direct first, then derived for the stops a
    direct measurement doesn't already cover."""
    matrix_provider = matrix_provider or _osrm_matrix
    direct = _direct_observations(db)
    covered = {o.stop_id for o in direct}
    derived = _derived_observations(db, matrix_provider, covered)
    return direct + derived


def _tour_teams(db: Session, tour_ids: set[int]) -> dict[int, tuple[int | None, str]]:
    """(assigned user id, display name) per tour: the responsible team."""
    if not tour_ids:
        return {}
    rows = db.execute(
        select(Tour.id, Tour.assigned_user_id, Tour.employee, Tour.team_lead, User.name)
        .outerjoin(User, Tour.assigned_user_id == User.id)
        .where(Tour.id.in_(tour_ids))
    ).all()
    return {
        tour_id: (user_id, user_name or employee or team_lead)
        for tour_id, user_id, employee, team_lead, user_name in rows
    }


def _preferred(samples: list[Observation]) -> list[Observation]:
    """The observations that feed a learned estimate: direct only when there
    are enough of them (so a trusted direct reading is never diluted by the
    noisier derived one), otherwise the whole pool."""
    direct = [o for o in samples if o.measurement_method == MeasurementMethod.direct]
    return direct if len(direct) >= MIN_SAMPLES else samples


def recompute_service_times(
    db: Session, matrix_provider: MatrixProvider | None = None
) -> list[StoreServiceTime]:
    """Rebuild the service ledger from history and re-learn every estimate.

    Stores without enough usable history get learned_service_minutes = NULL
    (their sample count is still recorded), so a store whose observations were
    later invalidated also un-learns; vanished ledger rows disappear with
    their history.
    """
    observations = collect_observations(db, matrix_provider)
    teams = _tour_teams(db, {o.tour_id for o in observations})
    db.query(ServiceRecord).delete()

    by_store: dict[int, list[Observation]] = {}
    for obs in observations:
        by_store.setdefault(obs.store_id, []).append(obs)
        user_id, team = teams.get(obs.tour_id, (None, None))
        db.add(
            ServiceRecord(
                stop_id=obs.stop_id,
                store_id=obs.store_id,
                tour_id=obs.tour_id,
                user_id=user_id,
                team=team,
                serviced_on=obs.serviced_on,
                task_signature=obs.task_signature,
                tasks_label=obs.tasks_label,
                duration_minutes=obs.minutes,
                measurement_method=obs.measurement_method,
                is_demo=obs.is_demo,
            )
        )

    results: list[StoreServiceTime] = []
    for store in db.scalars(select(Store).order_by(Store.name)):
        samples = by_store.get(store.id, [])
        # Prefer direct readings for the store-wide estimate when there are
        # enough; the ledger keeps every row, but the number learned trusts
        # the better source.
        chosen = _preferred(samples)
        store.learned_service_minutes = learned_minutes([o.minutes for o in chosen])
        store.service_time_samples = len(chosen)
        store.service_times_updated_at = func.now()

        by_signature: dict[str, list[Observation]] = {}
        for obs in samples:
            by_signature.setdefault(obs.task_signature, []).append(obs)
        results.append(
            StoreServiceTime(
                store_id=store.id,
                name=store.name,
                samples=len(chosen),
                learned_service_minutes=store.learned_service_minutes,
                by_service=[
                    ServiceProfileTime(
                        task_signature=signature,
                        tasks_label=next(
                            (o.tasks_label for o in group if o.tasks_label), None
                        ),
                        samples=len(chosen_group),
                        learned_minutes=learned_minutes(
                            [o.minutes for o in chosen_group]
                        ),
                    )
                    for signature, group in sorted(by_signature.items())
                    if (chosen_group := _preferred(group))
                ],
            )
        )

    db.commit()
    return results


__all__ = [
    "MIN_SAMPLES",
    "MIN_SERVICE_MINUTES",
    "MAX_SERVICE_MINUTES",
    "Observation",
    "ServiceProfileTime",
    "StoreServiceTime",
    "collect_observations",
    "recompute_service_times",
]
