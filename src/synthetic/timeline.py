"""Calendar for the simulation: dates, seasonality, growth and local-time conversion.

All instants are stored as UTC datetimes; "days" are local calendar dates in the
reporting time zone unless a time zone is passed explicitly (Meta uses its account's).
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from synthetic.config import SERVICE_LINES, WorldConfig
from synthetic.rng import Categorical


class Calendar:
    def __init__(self, config: WorldConfig) -> None:
        window = config.window
        self.start = window.start
        self.end = window.end
        self.data_as_of = window.data_as_of
        self.sim_start = window.start - timedelta(days=window.burn_in_days)
        self.tz = ZoneInfo(config.organization.reporting_tz)
        self._weekday = config.traffic.weekday
        self._growth = config.traffic.growth_per_year
        self._growth_by_service = config.traffic.growth_by_service
        self._season: dict[str, list[float]] = {}
        for service in SERVICE_LINES:
            values = config.seasonality.get(service, [1.0] * 12)
            mean = sum(values) / 12
            self._season[service] = [value / mean for value in values]
        self._hours = {
            name: Categorical(dict(enumerate(weights))) for name, weights in config.hours.items()
        }
        # First exported instant, and the instant just after the last exported one.
        self.window_start_utc = self.at(self.start, 0)
        self.as_of_end_utc = self.at(self.data_as_of + timedelta(days=1), 0)

    def sim_days(self) -> list[date]:
        """Every simulated day: the burn-in period followed by the export window."""
        count = (self.end - self.sim_start).days + 1
        return [self.sim_start + timedelta(days=offset) for offset in range(count)]

    def season(self, service: str | None, day: date) -> float:
        return 1.0 if service is None else self._season[service][day.month - 1]

    def weekday(self, day: date) -> float:
        return self._weekday[day.weekday()]

    def growth(self, day: date, service: str | None = None) -> float:
        """Linear trend: the window's first year averages 1.0, the second 1 + growth rate."""
        rate = self._growth_by_service.get(service, self._growth) if service else self._growth
        years_from_middle_of_first_year = ((day - self.start).days - 182.5) / 365
        return max(0.1, 1.0 + rate * years_from_middle_of_first_year)

    def at(self, day: date, seconds: float, tz: ZoneInfo | None = None) -> datetime:
        """UTC instant for the local wall-clock time `seconds` after midnight on `day`."""
        local = datetime.combine(day, time(), tzinfo=tz or self.tz) + timedelta(seconds=seconds)
        return local.astimezone(UTC)

    def random_time(
        self, rng: np.random.Generator, day: date, hours: str, tz: ZoneInfo | None = None
    ) -> datetime:
        hour = self._hours[hours].sample(rng)
        return self.at(day, hour * 3600 + int(rng.integers(0, 3600)), tz)

    def local_date(self, instant: datetime, tz: ZoneInfo | None = None) -> date:
        return instant.astimezone(tz or self.tz).date()

    def in_export_window(self, instant: datetime) -> bool:
        return self.window_start_utc <= instant < self.as_of_end_utc
