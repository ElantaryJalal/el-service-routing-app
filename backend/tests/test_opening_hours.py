from datetime import time

import pytest

from app.services.opening_hours import parse_opening_hours


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Mo-Fr 08:00-20:00", (time(8, 0), time(20, 0))),
        ("Mo-Sa 07:00-22:00", (time(7, 0), time(22, 0))),
        ("Mo-Fr 07:00-20:00; Sa 07:00-20:00; Su off", (time(7, 0), time(20, 0))),
        ("Mo-Sa 08:00-20:00; Su,PH off", (time(8, 0), time(20, 0))),
        # split midday break -> earliest open, latest close
        ("Mo-Fr 08:00-13:00,14:00-18:00", (time(8, 0), time(18, 0))),
        # end of day 24:00 -> 23:59
        ("Mo-Fr 06:00-24:00", (time(6, 0), time(23, 59))),
        ("24/7", (time(0, 0), time(23, 59))),
    ],
)
def test_parse_common_patterns(value, expected):
    assert parse_opening_hours(value) == expected


@pytest.mark.parametrize("value", ["", "Su off", "sunrise-sunset", "garbage"])
def test_parse_unparseable_returns_none(value):
    assert parse_opening_hours(value) is None


def test_weekend_only_rule_is_skipped():
    # Saturday-only hours should not be used as weekday hours.
    assert parse_opening_hours("Sa 09:00-13:00") is None
