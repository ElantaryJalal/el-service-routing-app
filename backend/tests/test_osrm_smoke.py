"""Smoke test: requires a running OSRM with the regional (Saxony area) dataset.

Run the stack first (see infra/README.md), then:

    cd backend && pytest tests/test_osrm_smoke.py
"""

from app.routing import OSRMClient

# Three points around Leipzig, as (lon, lat).
LEIPZIG_COORDS = [
    (12.3731, 51.3397),  # Markt
    (12.3833, 51.3455),  # Hauptbahnhof
    (12.4265, 51.3230),  # Stötteritz
]


def test_osrm_duration_matrix_leipzig() -> None:
    client = OSRMClient()
    matrix = client.duration_matrix(LEIPZIG_COORDS)

    # 3×3 matrix.
    assert len(matrix) == 3
    assert all(len(row) == 3 for row in matrix)

    for i in range(3):
        for j in range(3):
            duration = matrix[i][j]
            assert duration is not None, f"no route between {i} and {j}"
            if i == j:
                assert duration == 0
            else:
                assert duration > 0, f"non-positive duration {i}->{j}: {duration}"
