"""Turning "last month" into exact dates.

Relative periods resolve against the dataset's `data_as_of` date, never the machine's clock,
and every analytics result echoes the resolved dates so a reader can see exactly what "last
month" meant. Dates are calendar days in the organization's reporting time zone (inclusive).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

Preset = Literal[
    "last_7_days",
    "last_30_days",
    "last_month",
    "last_12_months",
    "month_to_date",
    "last_quarter",
    "quarter_to_date",
    "year_to_date",
    "custom",
]
ComparisonKind = Literal["none", "previous_period", "same_period_last_year", "custom"]


class PeriodSpec(BaseModel):
    """A period as a caller asks for it: a preset, or explicit dates with preset 'custom'."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset: Preset
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _dates_match_preset(self) -> "PeriodSpec":
        explicit = self.start is not None or self.end is not None
        if self.preset == "custom":
            if self.start is None or self.end is None:
                raise ValueError("a custom period needs both start and end")
            if self.start > self.end:
                raise ValueError("start is after end")
        elif explicit:
            raise ValueError("start and end are only allowed with preset 'custom'")
        return self


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def utc_bounds(self, tz: ZoneInfo) -> tuple[datetime, datetime]:
        """[first instant, instant after the last) of the period in that time zone, in UTC."""
        begin = datetime.combine(self.start, time(), tzinfo=tz)
        after = datetime.combine(self.end + timedelta(days=1), time(), tzinfo=tz)
        return begin.astimezone(UTC), after.astimezone(UTC)

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _month_end(day: date) -> date:
    following = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def _add_months(day: date, months: int) -> date:
    """The same day `months` later (or earlier), clipped to the end of a shorter month."""
    index = day.year * 12 + day.month - 1 + months
    first = date(index // 12, index % 12 + 1, 1)
    return first.replace(day=min(day.day, _month_end(first).day))


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def _whole_months(period: Period) -> int:
    """How many whole calendar months the period covers exactly (0 if it isn't whole months)."""
    if period.start.day != 1 or period.end != _month_end(period.end):
        return 0
    return (period.end.year - period.start.year) * 12 + period.end.month - period.start.month + 1


def resolve(spec: PeriodSpec, as_of: date) -> Period:
    """Resolve a period against data_as_of, the last day the data covers.

    "Last month" and "last quarter" mean the most recent *complete* one: if data_as_of is
    the last day of a month, that month counts as last month.
    """
    if spec.preset == "custom":
        return Period(spec.start, spec.end)  # type: ignore[arg-type]
    if spec.preset == "last_7_days":
        return Period(as_of - timedelta(days=6), as_of)
    if spec.preset == "last_30_days":
        return Period(as_of - timedelta(days=29), as_of)
    if spec.preset == "month_to_date":
        return Period(_month_start(as_of), as_of)
    if spec.preset == "quarter_to_date":
        return Period(_quarter_start(as_of), as_of)
    if spec.preset == "year_to_date":
        return Period(date(as_of.year, 1, 1), as_of)
    if spec.preset in ("last_month", "last_12_months"):
        end = as_of if as_of == _month_end(as_of) else _month_start(as_of) - timedelta(days=1)
        months = 12 if spec.preset == "last_12_months" else 1
        return Period(_add_months(_month_start(end), 1 - months), end)
    # last_quarter
    quarter_end = _month_end(_add_months(_quarter_start(as_of), 2))
    end = as_of if as_of == quarter_end else _quarter_start(as_of) - timedelta(days=1)
    return Period(_quarter_start(end), end)


def comparison_period(
    period: Period,
    kind: ComparisonKind,
    custom: PeriodSpec | None = None,
    as_of: date | None = None,
) -> Period | None:
    if kind == "none":
        return None
    if kind == "custom":
        if custom is None or as_of is None:
            raise ValueError("a custom comparison needs its own period and data_as_of")
        return resolve(custom, as_of)
    if kind == "same_period_last_year":
        return Period(_add_months(period.start, -12), _add_months(period.end, -12))
    # previous_period: whole months compare with the whole months before them,
    # anything else with the same number of days immediately before.
    months = _whole_months(period)
    if months:
        start = _add_months(period.start, -months)
        return Period(start, _month_end(_add_months(start, months - 1)))
    end = period.start - timedelta(days=1)
    return Period(end - timedelta(days=period.days - 1), end)


def period_warnings(
    period: Period,
    comparison: Period | None,
    kind: ComparisonKind,
    data_start: date | None,
) -> list[str]:
    """Caveat codes (docs/metrics.md) that the periods alone already justify."""
    warnings = []
    if comparison is not None:
        both_whole_months = _whole_months(period) and _whole_months(comparison) == _whole_months(
            period
        )
        if comparison.days != period.days and not both_whole_months:
            warnings.append("unequal_periods")
        # Home-services demand moves with the seasons: comparing a month (or longer) with a
        # different time of year mostly measures weather. Only a year apart is like for like.
        year_apart = abs((period.start - comparison.start).days - 365) <= 7
        if period.days >= 28 and period.days < 360 and not year_apart:
            warnings.append("seasonal_comparison")
    earliest = min(period.start, comparison.start) if comparison else period.start
    if data_start is not None and earliest < data_start:
        warnings.append("source_incomplete")
    return warnings
