"""Learn per-store service durations from completion history (P4).

The crew taps "done" as they finish each stop, so ``completed_at`` marks the
*end* of service. Arrival is never recorded — but when two stops were completed
back to back on the same planned day, the gap between their timestamps is one
drive plus one service:

    service(B) = completed_at(B) - completed_at(A) - drive(A -> B)

with the drive leg taken from the OSRM matrix. An observation is only trusted
when the two stops are adjacent in the day's planned sequence (a missing stop
in between means an unknown detour) and the resulting duration is plausible:

- Near-zero durations are discarded: the offline outbox stamps queued
  completions with the *sync* time, so a reconnecting phone produces a burst of
  completions seconds apart that say nothing about service length.
- Very long durations are discarded: the pair straddled a break, an overnight,
  or a forced re-completion days later.

A store's learned value is the **median** of its surviving observations —
robust to the occasional forgotten tap — and is only set once MIN_SAMPLES
observations exist. Everything is recomputed from scratch on each run
(history is small: one crew, ~26 stores, weekly tours), triggered via
POST /stores/service-times/recompute.

One store is not one duration: the same market can host different services
(often different teams) with very different lengths, so observations are
additionally grouped by the visit's **task signature** and each profile gets
its own median (``store_service_times`` rows). The store-wide median stays on
the store row as the fallback for task profiles never seen before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.stop import Stop
from app.models.store import Store
from app.models.store_service_time import StoreServiceTime as StoreServiceTimeRow
from app.models.store_service_time import task_signature
from app.models.task import Task
from app.services.optimiser import MatrixProvider, _osrm_matrix

MIN_SERVICE_MINUTES = 10
MAX_SERVICE_MINUTES = 600  # matches the manual estimate cap on stops
MIN_SAMPLES = 2


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
    """One derived service duration, tagged with the visit's task profile."""

    seconds: int
    task_signature: str
    tasks_label: str | None


def _completed_day_groups(db: Session) -> list[list]:
    """Completed, located, scheduled stops grouped by (tour, planned day)."""
    rows = db.execute(
        select(
            Stop.id,
            Stop.tour_id,
            Stop.assigned_day,
            Stop.sequence,
            Stop.store_id,
            Stop.completed_at,
            func.ST_X(Stop.geom).label("lon"),
            func.ST_Y(Stop.geom).label("lat"),
        )
        .where(
            Stop.completed_at.isnot(None),
            Stop.assigned_day.isnot(None),
            Stop.sequence.isnot(None),
            Stop.geom.isnot(None),
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


def collect_observations(
    db: Session, matrix_provider: MatrixProvider | None = None
) -> dict[int, list[Observation]]:
    """Observed service durations, keyed by store id and tagged with the
    visit's task profile.

    One OSRM matrix call per (tour, day) group; the observation belongs to the
    *later* stop of each pair (it's the one whose service the gap contains).
    """
    matrix_provider = matrix_provider or _osrm_matrix
    groups = _completed_day_groups(db)
    profiles = _stop_profiles(db, [row.id for group in groups for row in group])
    observations: dict[int, list[Observation]] = {}

    for group in groups:
        matrix = matrix_provider([(row.lon, row.lat) for row in group])
        for index, (prev, cur) in enumerate(zip(group, group[1:], strict=False)):
            # Sequence-adjacent only: a gap in the planned order means an
            # uncompleted stop sat between them and the drive is unknown.
            if cur.sequence != prev.sequence + 1 or cur.store_id is None:
                continue
            gap = (cur.completed_at - prev.completed_at).total_seconds()
            service = gap - matrix[index][index + 1]
            if MIN_SERVICE_MINUTES * 60 <= service <= MAX_SERVICE_MINUTES * 60:
                signature, label = profiles.get(cur.id, ("", None))
                observations.setdefault(cur.store_id, []).append(
                    Observation(int(service), signature, label)
                )

    return observations


def recompute_service_times(
    db: Session, matrix_provider: MatrixProvider | None = None
) -> list[StoreServiceTime]:
    """Re-learn every store's service times from history and persist them.

    Stores without enough usable history get learned_service_minutes = NULL
    (their sample count is still recorded), so a store whose observations were
    later invalidated also un-learns. Per-profile rows are rebuilt from
    scratch, so vanished profiles disappear with their history.
    """
    observations = collect_observations(db, matrix_provider)
    db.query(StoreServiceTimeRow).delete()

    results: list[StoreServiceTime] = []
    for store in db.scalars(select(Store).order_by(Store.name)):
        samples = observations.get(store.id, [])
        learned = (
            int(round(median(o.seconds for o in samples) / 60))
            if len(samples) >= MIN_SAMPLES
            else None
        )
        store.learned_service_minutes = learned
        store.service_time_samples = len(samples)
        store.service_times_updated_at = func.now()

        by_signature: dict[str, list[Observation]] = {}
        for obs in samples:
            by_signature.setdefault(obs.task_signature, []).append(obs)
        by_service: list[ServiceProfileTime] = []
        for signature, group in sorted(by_signature.items()):
            profile_learned = (
                int(round(median(o.seconds for o in group) / 60))
                if len(group) >= MIN_SAMPLES
                else None
            )
            label = next((o.tasks_label for o in group if o.tasks_label), None)
            db.add(
                StoreServiceTimeRow(
                    store_id=store.id,
                    task_signature=signature,
                    tasks_label=label,
                    learned_minutes=profile_learned,
                    samples=len(group),
                )
            )
            by_service.append(
                ServiceProfileTime(
                    task_signature=signature,
                    tasks_label=label,
                    samples=len(group),
                    learned_minutes=profile_learned,
                )
            )

        results.append(
            StoreServiceTime(
                store_id=store.id,
                name=store.name,
                samples=len(samples),
                learned_service_minutes=learned,
                by_service=by_service,
            )
        )

    db.commit()
    return results
