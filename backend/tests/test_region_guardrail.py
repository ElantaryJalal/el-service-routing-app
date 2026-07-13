"""Unit tests for the optimized-mode region guardrail (pure functions, no DB).

plan_region_days keeps far-apart areas off the same working day by clustering
stops, grouping compatible clusters, and splitting the week's days between the
groups by workload.
"""

from datetime import date, timedelta

from app.services.optimiser import (
    _allocate_days,
    _cluster_by_proximity,
    _haversine_km,
    plan_region_days,
)

LEIPZIG = (12.37, 51.34)
AACHEN = (6.08, 50.77)

WEEK = [date(2026, 6, 29) + timedelta(days=i) for i in range(5)]

HOUR = 3600


def test_haversine_known_distance():
    assert 400 < _haversine_km(LEIPZIG, AACHEN) < 480
    assert _haversine_km(LEIPZIG, LEIPZIG) == 0


def test_cluster_by_proximity_chains_neighbours():
    # Three points 10 km apart chain into one cluster; Aachen stays alone.
    coords = [
        LEIPZIG,
        (LEIPZIG[0] + 0.13, LEIPZIG[1]),  # ~9 km east
        (LEIPZIG[0] + 0.26, LEIPZIG[1]),  # ~9 km further (18 km from first)
        AACHEN,
    ]
    clusters = _cluster_by_proximity(coords, eps_km=10)
    assert sorted(sorted(c) for c in clusters) == [[0, 1, 2], [3]]


def test_allocate_days_single_group_takes_all():
    assert _allocate_days([10 * HOUR], 5) == [5]


def test_allocate_days_proportional_and_complete():
    counts = _allocate_days([6 * HOUR, 6 * HOUR], 5)
    assert sum(counts) == 5
    assert all(c >= 1 for c in counts)


def test_allocate_days_dominant_group_leaves_one_day():
    assert _allocate_days([100 * HOUR, 1 * HOUR], 5) == [4, 1]


def test_allocate_days_more_groups_than_days():
    assert _allocate_days([5 * HOUR, 4 * HOUR, 3 * HOUR], 2) == [1, 1, 0]


def test_allocate_days_no_days():
    assert _allocate_days([HOUR, HOUR], 0) == [0, 0]


def test_plan_region_days_single_region_gets_whole_week():
    stops = {i: ((LEIPZIG[0] + i * 0.01, LEIPZIG[1]), HOUR) for i in range(6)}
    allowed = plan_region_days(stops, WEEK, max_span_km=120)
    assert all(allowed[i] == WEEK for i in stops)


def test_plan_region_days_far_regions_get_disjoint_blocks():
    stops = {i: ((LEIPZIG[0] + i * 0.01, LEIPZIG[1]), HOUR) for i in range(4)}
    stops |= {10 + i: ((AACHEN[0] + i * 0.01, AACHEN[1]), HOUR) for i in range(4)}

    allowed = plan_region_days(stops, WEEK, max_span_km=120)

    leipzig_days = {d for i in range(4) for d in allowed[i]}
    aachen_days = {d for i in range(4) for d in allowed[10 + i]}
    assert leipzig_days and aachen_days
    assert leipzig_days.isdisjoint(aachen_days)


def test_plan_region_days_depot_orders_blocks_by_distance():
    # Big Leipzig region, one stop near Aachen, base just west of Aachen: the
    # small region is on the way out and must get day 1, not the leftover
    # Friday its workload rank would give it.
    stops = {i: ((LEIPZIG[0] + i * 0.01, LEIPZIG[1]), HOUR) for i in range(4)}
    stops[10] = (AACHEN, HOUR)
    depot = (AACHEN[0] - 0.05, AACHEN[1])

    allowed = plan_region_days(stops, WEEK, max_span_km=120, depot=depot)

    assert allowed[10] == [WEEK[0]]
    assert all(allowed[i] == WEEK[1:] for i in range(4))


def test_plan_region_days_without_depot_keeps_workload_order():
    stops = {i: ((LEIPZIG[0] + i * 0.01, LEIPZIG[1]), HOUR) for i in range(4)}
    stops[10] = (AACHEN, HOUR)

    allowed = plan_region_days(stops, WEEK, max_span_km=120)

    assert allowed[10] == [WEEK[4]]
    assert all(allowed[i] == WEEK[:4] for i in range(4))


def test_plan_region_days_loser_region_gets_no_day():
    # One day, two regions: the smaller-workload region maps to [].
    stops = {
        0: (LEIPZIG, HOUR),
        1: ((LEIPZIG[0] + 0.01, LEIPZIG[1]), HOUR),
        2: (AACHEN, HOUR),
    }
    allowed = plan_region_days(stops, WEEK[:1], max_span_km=120)
    assert allowed[0] == allowed[1] == WEEK[:1]
    assert allowed[2] == []
