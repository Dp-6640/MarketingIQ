from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest

from synthetic.config import SERVICE_LINES, load_config
from synthetic.rng import Streams
from synthetic.timeline import Calendar


@pytest.fixture(scope="module")
def calendar() -> Calendar:
    return Calendar(load_config("default"))


def test_simulated_days_include_burn_in(calendar):
    days = calendar.sim_days()

    assert days[0] == date(2024, 9, 1)  # 30 burn-in days before 2024-10-01
    assert days[-1] == date(2026, 9, 30)
    assert all(b - a == timedelta(days=1) for a, b in pairwise(days))


@pytest.mark.parametrize("service", SERVICE_LINES)
def test_seasonality_averages_one(calendar, service):
    monthly = [calendar.season(service, date(2025, month, 1)) for month in range(1, 13)]

    assert sum(monthly) / 12 == pytest.approx(1.0)


def test_furnace_peaks_in_winter_and_ac_in_summer(calendar):
    november, july, january = date(2025, 11, 1), date(2025, 7, 1), date(2025, 1, 1)

    ac = "air_conditioner"

    assert calendar.season("furnace", november) > calendar.season("furnace", july)
    assert calendar.season(ac, july) > 2 * calendar.season(ac, january)


def test_growth_averages_one_then_one_plus_rate(calendar):
    def year_average(first_day: date, service: str | None = None) -> float:
        days = [first_day + timedelta(days=i) for i in range(365)]
        return sum(calendar.growth(d, service) for d in days) / 365

    assert year_average(date(2024, 10, 1)) == pytest.approx(1.0, abs=0.002)
    assert year_average(date(2025, 10, 1)) == pytest.approx(1.08, abs=0.002)
    assert year_average(date(2025, 10, 1), "heat_pump") == pytest.approx(1.25, abs=0.002)


def test_local_noon_converts_to_utc_across_daylight_saving(calendar):
    winter = calendar.at(date(2025, 1, 15), 12 * 3600)
    summer = calendar.at(date(2025, 7, 15), 12 * 3600)

    assert winter == datetime(2025, 1, 15, 17, tzinfo=UTC)
    assert summer == datetime(2025, 7, 15, 16, tzinfo=UTC)


def test_export_window_bounds(calendar):
    assert calendar.window_start_utc == datetime(2024, 10, 1, 4, tzinfo=UTC)
    assert calendar.as_of_end_utc == datetime(2026, 10, 1, 4, tzinfo=UTC)
    assert calendar.in_export_window(datetime(2026, 10, 1, 3, 59, tzinfo=UTC))
    assert not calendar.in_export_window(datetime(2026, 10, 1, 4, tzinfo=UTC))


def test_business_hours_never_produce_night_times(calendar):
    rng = Streams(3).rng("hours")

    hours = {
        calendar.random_time(rng, date(2025, 3, 3), "business").astimezone(calendar.tz).hour
        for _ in range(500)
    }

    assert min(hours) >= 7
    assert max(hours) <= 19
