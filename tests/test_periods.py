from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from marketingiq.analytics.periods import (
    Period,
    PeriodSpec,
    comparison_period,
    period_warnings,
    resolve,
)

AS_OF = date(2026, 9, 30)  # the default synthetic dataset's data_as_of: a month end


@pytest.mark.parametrize(
    ("preset", "as_of", "expected"),
    [
        ("last_7_days", AS_OF, Period(date(2026, 9, 24), AS_OF)),
        ("last_30_days", AS_OF, Period(date(2026, 9, 1), AS_OF)),
        # data_as_of is the last day of September, so September is complete: it's "last month".
        ("last_month", AS_OF, Period(date(2026, 9, 1), AS_OF)),
        ("last_month", date(2026, 9, 15), Period(date(2026, 8, 1), date(2026, 8, 31))),
        ("month_to_date", date(2026, 9, 15), Period(date(2026, 9, 1), date(2026, 9, 15))),
        ("last_quarter", AS_OF, Period(date(2026, 7, 1), AS_OF)),
        ("last_quarter", date(2026, 8, 10), Period(date(2026, 4, 1), date(2026, 6, 30))),
        ("quarter_to_date", date(2026, 8, 10), Period(date(2026, 7, 1), date(2026, 8, 10))),
        ("year_to_date", AS_OF, Period(date(2026, 1, 1), AS_OF)),
    ],
)
def test_presets_resolve_against_data_as_of(preset, as_of, expected):
    assert resolve(PeriodSpec(preset=preset), as_of) == expected


def test_custom_periods_need_valid_dates():
    assert resolve(
        PeriodSpec(preset="custom", start=date(2026, 3, 1), end=date(2026, 3, 31)), AS_OF
    ) == Period(date(2026, 3, 1), date(2026, 3, 31))
    with pytest.raises(ValidationError):
        PeriodSpec(preset="custom", start=date(2026, 3, 1))
    with pytest.raises(ValidationError):
        PeriodSpec(preset="custom", start=date(2026, 3, 31), end=date(2026, 3, 1))
    with pytest.raises(ValidationError):
        PeriodSpec(preset="last_month", start=date(2026, 3, 1), end=date(2026, 3, 31))


def test_previous_period_of_a_month_is_the_previous_month():
    march = Period(date(2026, 3, 1), date(2026, 3, 31))

    assert comparison_period(march, "previous_period") == Period(
        date(2026, 2, 1), date(2026, 2, 28)
    )


def test_previous_period_of_days_has_the_same_length():
    week = Period(date(2026, 9, 24), date(2026, 9, 30))

    assert comparison_period(week, "previous_period") == Period(
        date(2026, 9, 17), date(2026, 9, 23)
    )


def test_same_period_last_year_handles_leap_days():
    february = Period(date(2028, 2, 1), date(2028, 2, 29))

    assert comparison_period(february, "same_period_last_year") == Period(
        date(2027, 2, 1), date(2027, 2, 28)
    )


def test_custom_comparison():
    spec = PeriodSpec(preset="custom", start=date(2026, 5, 1), end=date(2026, 5, 11))
    after = Period(date(2026, 5, 12), date(2026, 5, 22))

    assert comparison_period(after, "custom", spec, AS_OF) == Period(
        date(2026, 5, 1), date(2026, 5, 11)
    )
    assert comparison_period(after, "none") is None


def test_warnings_for_seasonal_unequal_and_incomplete_comparisons():
    march = Period(date(2026, 3, 1), date(2026, 3, 31))
    february = comparison_period(march, "previous_period")
    data_start = date(2024, 10, 1)

    # Whole months compare cleanly despite 31 vs 28 days, but month-over-month is seasonal.
    assert period_warnings(march, february, "previous_period", data_start) == [
        "seasonal_comparison"
    ]
    uneven = Period(date(2026, 3, 1), date(2026, 3, 10))
    assert "unequal_periods" in period_warnings(march, uneven, "custom", data_start)
    last_year = comparison_period(march, "same_period_last_year")
    assert period_warnings(march, last_year, "same_period_last_year", data_start) == []
    early = comparison_period(
        Period(date(2024, 12, 1), date(2024, 12, 31)), "same_period_last_year"
    )
    assert period_warnings(march, early, "same_period_last_year", data_start) == [
        "source_incomplete"
    ]


def test_utc_bounds_follow_the_reporting_time_zone():
    toronto = ZoneInfo("America/Toronto")
    start, after = Period(date(2026, 3, 1), date(2026, 3, 31)).utc_bounds(toronto)

    assert start == datetime(2026, 3, 1, 5, tzinfo=UTC)  # EST
    assert after == datetime(2026, 4, 1, 4, tzinfo=UTC)  # EDT after the March switch
