"""Stockholm calendar-year and configured-tournament rollover rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


STOCKHOLM_TIME_ZONE = ZoneInfo("Europe/Stockholm")
Clock = Callable[[], datetime]


class TournamentYearState(StrEnum):
    """Relationship between configured tournament starts and the current year."""

    CURRENT = "current"
    STALE = "stale"
    MIXED = "mixed"
    FUTURE = "future"


@dataclass(frozen=True)
class TournamentYearAssessment:
    """Authoritative year classification for one non-empty tournament list."""

    state: TournamentYearState
    current_year: int
    configured_years: tuple[int, ...]

    @property
    def rollover_available(self) -> bool:
        return self.state is TournamentYearState.STALE

    @property
    def default_generation_allowed(self) -> bool:
        return self.state is TournamentYearState.CURRENT


class DefaultTournamentYearError(ValueError):
    """Raised when configured defaults cannot be used for a full generation."""

    def __init__(self, assessment: TournamentYearAssessment) -> None:
        self.assessment = assessment
        super().__init__(
            "configured tournament start years "
            f"{assessment.configured_years!r} cannot be used for a default "
            f"full generation in {assessment.current_year}"
        )


def stockholm_today(clock: Clock) -> date:
    """Return the date in Stockholm for an injected aware-datetime clock."""
    instant = clock()
    if not isinstance(instant, datetime):
        raise TypeError("clock must return a datetime")
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return instant.astimezone(STOCKHOLM_TIME_ZONE).date()


def assess_tournament_years(
    start_dates: Iterable[date],
    current_year: int,
) -> TournamentYearAssessment:
    """Classify tournament starts without inferring a year from their ids."""
    dates = tuple(start_dates)
    if not dates:
        raise ValueError("at least one tournament start date is required")
    if any(not isinstance(start_date, date) for start_date in dates):
        raise TypeError("tournament start dates must be dates")

    configured_years = tuple(sorted({start_date.year for start_date in dates}))
    if len(configured_years) > 1:
        state = TournamentYearState.MIXED
    elif configured_years[0] < current_year:
        state = TournamentYearState.STALE
    elif configured_years[0] > current_year:
        state = TournamentYearState.FUTURE
    else:
        state = TournamentYearState.CURRENT
    return TournamentYearAssessment(state, current_year, configured_years)


def require_current_default_tournaments(
    assessment: TournamentYearAssessment,
) -> None:
    """Block a default full run unless all tournament starts are current-year."""
    if not assessment.default_generation_allowed:
        raise DefaultTournamentYearError(assessment)
