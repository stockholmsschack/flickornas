"""Bounded, validated access to the Swedish Chess Federation member system."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
import threading
import time
from typing import Any, NewType
from urllib.parse import quote

import requests

from .klass_naming import KlassNameRefused, KlassNamingProblem, read_klass
from .numeric_validation import (
    is_non_negative_finite_number,
    is_non_negative_integer,
    is_positive_finite_number,
    is_positive_integer,
)


JsonValue = Any
PlayerId = NewType("PlayerId", int)
ClubId = NewType("ClubId", int)
TournamentId = NewType("TournamentId", int)
TournamentGroupId = NewType("TournamentGroupId", int)


@dataclass(frozen=True)
class PlayerInfo:
    """Validated player identity returned by search or dated resolution."""

    player_id: PlayerId
    first_name: str
    last_name: str
    birth_year: int
    current_club_id: ClubId | None = None
    current_club_name: str | None = None
    country: str | None = None
    fide_id: int | None = None


@dataclass(frozen=True)
class CanonicalClub:
    """One verified club from the configured district's canonical list."""

    club_id: ClubId
    name: str


@dataclass(frozen=True)
class TournamentGroupSearchHit:
    """One matching group returned by tournament-group search."""

    matching_group_id: TournamentGroupId
    tournament_id: TournamentId
    matching_group_name: str
    tournament_name: str
    latest_updated_game: str | None = None


@dataclass(frozen=True)
class ProcessableTournamentGroup:
    """A canonical tournament group understood by Flickornas generation."""

    group_id: TournamentGroupId
    name: str
    klass: str
    registered_rounds: int = 0

    def __post_init__(self) -> None:
        if not is_non_negative_integer(self.registered_rounds):
            raise ValueError("registered_rounds must be a non-negative integer")


@dataclass(frozen=True)
class CanonicalTournament:
    """An authoritatively resolved tournament suitable for selection."""

    tournament_id: TournamentId
    name: str
    start_date: date
    end_date: date
    processable_groups: tuple[ProcessableTournamentGroup, ...]


@dataclass(frozen=True)
class TournamentResolutionProblem:
    """One tournament identifier that could not be resolved."""

    tournament_id: int
    detail: str
    klass_problems: tuple[KlassNamingProblem, ...] = ()


@dataclass(frozen=True)
class TournamentResolutionResult:
    """Ordered tournaments and any identifier-specific problems."""

    tournaments: tuple[CanonicalTournament, ...]
    problems: tuple[TournamentResolutionProblem, ...] = ()

    def require_all(self) -> tuple[CanonicalTournament, ...]:
        """Return all tournaments or report naming failures before other refusals."""
        if self.problems:
            problem = self.problems[0]
            klass_problems = tuple(
                klass_problem for failure in self.problems
                for klass_problem in failure.klass_problems
            )
            if klass_problems:
                raise TournamentKlassNamingError(klass_problems[0].tournament_id, klass_problems)
            raise TournamentResolutionError(problem.tournament_id, problem.detail)
        return self.tournaments


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: Any


class UpstreamError(RuntimeError):
    """Base class for actionable member-system failures."""

    def __init__(self, stage: str, detail: str) -> None:
        self.stage = stage
        super().__init__(f"upstream failure while {stage}: {detail}")


class UpstreamRetryExhausted(UpstreamError):
    """Raised after every permitted attempt failed transiently."""


class UpstreamResponseError(UpstreamError):
    """Raised for a non-retryable HTTP response."""

    def __init__(
        self,
        stage: str,
        detail: str,
        *,
        status_code: int | None = None,
    ) -> None:
        self.status_code = status_code
        super().__init__(stage, detail)


class UpstreamDataError(UpstreamError):
    """Raised when a successful response violates its contract."""


class TournamentResolutionError(RuntimeError):
    """Raised when an id cannot become a verified tournament selection."""

    def __init__(self, tournament_id: int, detail: str) -> None:
        self.tournament_id = tournament_id
        self.detail = detail
        super().__init__(
            f"tournament {tournament_id} cannot be resolved: {detail}"
        )


class TournamentKlassNamingError(TournamentResolutionError):
    """Every refused first-root group in one tournament."""

    def __init__(
        self, tournament_id: int, klass_problems: Sequence[KlassNamingProblem]
    ) -> None:
        self.klass_problems = tuple(klass_problems)
        super().__init__(tournament_id, "\n".join(map(str, self.klass_problems)))


def _require_mapping(value: JsonValue, stage: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UpstreamDataError(stage, "expected a JSON object")
    return value


def _require_list(value: JsonValue, stage: str) -> list[Any]:
    if not isinstance(value, list):
        raise UpstreamDataError(stage, "expected a JSON array")
    return value


def _require_fields(
    value: Mapping[str, Any], required: set[str], stage: str, subject: str
) -> None:
    missing = sorted(required.difference(value))
    if missing:
        raise UpstreamDataError(
            stage, f"{subject} is missing required field(s): {', '.join(missing)}"
        )


def _require_positive_int(
    value: Any,
    stage: str,
    subject: str,
) -> int:
    if not is_positive_integer(value):
        raise UpstreamDataError(stage, f"{subject} must be a positive integer")
    return value


def _require_nonnegative_int(
    value: Any,
    stage: str,
    subject: str,
) -> int:
    if not is_non_negative_integer(value):
        raise UpstreamDataError(stage, f"{subject} must be a non-negative integer")
    return value


def _require_nonempty_string(
    value: Any,
    stage: str,
    subject: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpstreamDataError(stage, f"{subject} must be a non-empty string")
    return value.strip()


def _require_iso_date(value: Any, stage: str, subject: str) -> date:
    raw_value = _require_nonempty_string(value, stage, subject)
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        try:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).date()
        except ValueError as error:
            raise UpstreamDataError(
                stage, f"{subject} must be an ISO date or date-time"
            ) from error


def _require_birth_year(value: Any, stage: str, subject: str) -> int:
    raw_value = _require_nonempty_string(value, stage, subject)
    if len(raw_value) == 4 and raw_value.isascii() and raw_value.isdigit():
        birth_year = int(raw_value)
        if birth_year > 0:
            return birth_year
        raise UpstreamDataError(stage, f"{subject} must contain a valid year")
    return _require_iso_date(raw_value, stage, subject).year


def _optional_nonempty_string(
    value: Mapping[str, Any],
    field: str,
    stage: str,
    subject: str,
) -> str | None:
    raw_value = value.get(field)
    if raw_value is None or raw_value == "":
        return None
    return _require_nonempty_string(raw_value, stage, subject)


def _optional_identifier(
    value: Mapping[str, Any],
    field: str,
    stage: str,
    subject: str,
) -> int | None:
    raw_value = value.get(field)
    if raw_value is None:
        return None
    if not isinstance(raw_value, bool) and raw_value == 0:
        return None
    return _require_positive_int(raw_value, stage, subject)


def _player_info(value: JsonValue, stage: str, subject: str) -> PlayerInfo:
    player = _require_mapping(value, stage)
    _require_fields(
        player,
        {"id", "firstName", "lastName", "birthdate"},
        stage,
        subject,
    )
    current_club_id = _optional_identifier(
        player,
        "clubId",
        stage,
        f"{subject} clubId",
    )
    return PlayerInfo(
        player_id=PlayerId(
            _require_positive_int(player["id"], stage, f"{subject} id")
        ),
        first_name=_require_nonempty_string(
            player["firstName"], stage, f"{subject} firstName"
        ),
        last_name=_require_nonempty_string(
            player["lastName"], stage, f"{subject} lastName"
        ),
        birth_year=_require_birth_year(
            player["birthdate"], stage, f"{subject} birthdate"
        ),
        current_club_id=(
            ClubId(current_club_id) if current_club_id is not None else None
        ),
        current_club_name=_optional_nonempty_string(
            player,
            "club",
            stage,
            f"{subject} club",
        ),
        country=_optional_nonempty_string(
            player,
            "country",
            stage,
            f"{subject} country",
        ),
        fide_id=_optional_identifier(
            player,
            "fideid",
            stage,
            f"{subject} fideid",
        ),
    )


_TROJANSKA_7132_GROUPS = {
    19203: ("Gymnasiet och äldre 2006-2010", "a"),
    19204: ("Högstadiet 2011-2013", "b"),
    19205: ("Mellanstadiet Elit 2014-2016", "c"),
    19206: ("Lågstadiet Elit 2017-2019", "d"),
    19207: ("Mellanstadiet Allmän 2014-2016", "y"),
    19208: ("Lågstadiet Nybörjare 2017-2019 (utan klocka)", "z"),
}


def _processable_tournament_groups(
    root_classes_value: Any,
    stage: str,
    tournament_id: int,
    tournament_name: str,
    start_date: date,
    end_date: date,
) -> tuple[ProcessableTournamentGroup, ...]:
    """Validate every group and return compatible groups from generation's root."""
    root_classes = _require_list(root_classes_value, stage)
    processable_groups = []
    problems = []
    mapped_group_ids: set[int] = set()
    mapping_problems = []
    for root_class_index, root_class in enumerate(root_classes):
        root = _require_mapping(root_class, stage)
        _require_fields(root, {"groups"}, stage, "root class")
        for group in _require_list(root["groups"], stage):
            group_object = _require_mapping(group, stage)
            _require_fields(
                group_object,
                {"id", "name", "nrofrounds", "pointSystem"},
                stage,
                "tournament group",
            )
            group_id = _require_positive_int(
                group_object["id"], stage, "tournament group id"
            )
            group_name = _require_nonempty_string(
                group_object["name"], stage, "tournament group name"
            )
            registered_rounds = _require_nonnegative_int(
                group_object["nrofrounds"],
                stage,
                "tournament group nrofrounds",
            )
            if root_class_index != 0:
                continue
            if tournament_id == 7132:
                expected = _TROJANSKA_7132_GROUPS.get(group_id)
                subject = f"group {group_id} ({group_name!r})"
                if expected is None:
                    mapping_problems.append(f"unexpected {subject}")
                    continue
                if group_id in mapped_group_ids:
                    mapping_problems.append(f"duplicate {subject}")
                mapped_group_ids.add(group_id)
                expected_name, klass = expected
                if group_name != expected_name:
                    mapping_problems.append(
                        f"{subject}: expected name {expected_name!r}"
                    )
            else:
                try:
                    klass = read_klass(group_name)
                except KlassNameRefused as refusal:
                    problems.append(KlassNamingProblem(
                        tournament_id, tournament_name, group_id, group_name,
                        refusal.reason, refusal.detail,
                    ))
                    continue
            if klass is not None:
                processable_groups.append(
                    ProcessableTournamentGroup(
                        group_id=TournamentGroupId(group_id),
                        name=group_name,
                        klass=klass,
                        registered_rounds=registered_rounds,
                    )
                )
    if tournament_id == 7132:
        if start_date.year != 2026 or end_date.year != 2026:
            mapping_problems.append(
                f"expected season 2026, got {start_date} through {end_date}"
            )
        for group_id in sorted(_TROJANSKA_7132_GROUPS.keys() - mapped_group_ids):
            expected_name, _ = _TROJANSKA_7132_GROUPS[group_id]
            mapping_problems.append(
                f"missing group {group_id} ({expected_name!r}) in first root class"
            )
        if mapping_problems:
            raise TournamentResolutionError(
                tournament_id, "; ".join(mapping_problems)
            )
    if problems:
        raise TournamentKlassNamingError(tournament_id, problems)
    return tuple(processable_groups)


class MemberSystemClient:
    """HTTP client with a single timeout, retry, and validation policy."""

    DEFAULT_BASE_URL = "https://member.schack.se/public/api/v1"
    DEFAULT_SHORT_CACHE_TTL = 300.0
    DEFAULT_REFERENCE_CACHE_TTL = 3600.0

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout: float = 3.0,
        response_timeout: float = 15.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.25,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        short_cache_ttl: float = DEFAULT_SHORT_CACHE_TTL,
        reference_cache_ttl: float = DEFAULT_REFERENCE_CACHE_TTL,
    ) -> None:
        if not all(
            is_positive_finite_number(value)
            for value in (connect_timeout, response_timeout)
        ):
            raise ValueError("timeouts must be greater than zero")
        if not is_positive_integer(max_attempts):
            raise ValueError("max_attempts must be at least one")
        if not is_non_negative_finite_number(backoff_seconds):
            raise ValueError("backoff_seconds cannot be negative")
        if not all(
            is_non_negative_finite_number(value)
            for value in (short_cache_ttl, reference_cache_ttl)
        ):
            raise ValueError("cache TTLs cannot be negative")

        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout, response_timeout)
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.short_cache_ttl = short_cache_ttl
        self.reference_cache_ttl = reference_cache_ttl
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._cache_lock = threading.RLock()

    def district_rating_list(
        self,
        district_id: int,
        request_date: date,
        *,
        rating_type: int = 1,
        category: int = 0,
    ) -> list[Mapping[str, Any]]:
        stage = "fetching district rating list"
        path = (
            f"/ratinglist/district/{district_id}/date/{request_date.isoformat()}"
            f"/ratingtype/{rating_type}/category/{category}"
        )
        return self._validated_request(
            "district-rating-list",
            path,
            stage,
            self.short_cache_ttl,
            lambda data: self._list_of_objects(
                data, {"id"}, stage, "rating-list player"
            ),
        )

    def district_clubs(self, district_id: int) -> list[CanonicalClub]:
        stage = "fetching district club list"
        path = f"/organisation/district/clubs/{district_id}"

        def validate(data: JsonValue) -> list[CanonicalClub]:
            clubs = self._list_of_objects(data, {"id", "name"}, stage, "club")
            return [
                CanonicalClub(
                    club_id=ClubId(
                        _require_positive_int(club["id"], stage, "club id")
                    ),
                    name=_require_nonempty_string(
                        club["name"], stage, "club name"
                    ),
                )
                for club in clubs
            ]

        return self._validated_request(
            "district-clubs",
            path,
            stage,
            self.reference_cache_ttl,
            validate,
        )

    def group_table(self, group_id: int) -> list[Mapping[str, Any]]:
        stage = f"fetching group table for {group_id}"
        path = f"/tournamentresults/table/id/{group_id}"

        def validate(data: JsonValue) -> list[Mapping[str, Any]]:
            rows = self._list_of_objects(
                data,
                {
                    "contenderId",
                    "playerInfo",
                    "points",
                    "secPoints",
                    "wonGames",
                    "drawGames",
                    "lostGames",
                },
                stage,
                "group-table row",
            )
            for row in rows:
                player = _require_mapping(row["playerInfo"], stage)
                _require_fields(
                    player,
                    {
                        "clubId",
                        "club",
                        "firstName",
                        "lastName",
                        "sex",
                        "birthdate",
                    },
                    stage,
                    "playerInfo",
                )
            return rows

        return self._validated_request(
            "group-table",
            path,
            stage,
            self.short_cache_ttl,
            validate,
        )

    def group_round_results(self, group_id: int) -> list[Mapping[str, Any]]:
        stage = f"fetching round results for {group_id}"
        path = f"/tournamentresults/roundresults/id/{group_id}"

        def validate(data: JsonValue) -> list[Mapping[str, Any]]:
            rounds = self._list_of_objects(
                data, {"roundNr", "games"}, stage, "round"
            )
            for round_result in rounds:
                games = _require_list(round_result["games"], stage)
                for game in games:
                    game_object = _require_mapping(game, stage)
                    _require_fields(
                        game_object,
                        {"whiteId", "blackId", "result"},
                        stage,
                        "game",
                    )
            return rounds

        return self._validated_request(
            "group-round-results",
            path,
            stage,
            self.short_cache_ttl,
            validate,
        )

    def tournament_group_search(
        self, search_word: str
    ) -> list[TournamentGroupSearchHit]:
        stage = "searching tournament groups"
        path = f"/tournament/group/search/{quote(search_word, safe='')}"
        return self._validated_request(
            "tournament-group-search",
            path,
            stage,
            self.short_cache_ttl,
            lambda data: self._tournament_group_search_results(data, stage),
        )

    def _tournament_group_search_results(
        self,
        data: JsonValue,
        stage: str,
    ) -> list[TournamentGroupSearchHit]:
        rows = self._list_of_objects(
            data,
            {"id", "name", "tournamentid", "tournamentname"},
            stage,
            "tournament search result",
        )
        results = []
        for row in rows:
            latest_updated_game = row.get("latestUpdatedGame")
            if latest_updated_game is not None:
                latest_updated_game = _require_nonempty_string(
                    latest_updated_game,
                    stage,
                    "tournament search result latestUpdatedGame",
                )
            results.append(
                TournamentGroupSearchHit(
                    matching_group_id=TournamentGroupId(
                        _require_positive_int(
                            row["id"],
                            stage,
                            "tournament search result group id",
                        )
                    ),
                    tournament_id=TournamentId(
                        _require_positive_int(
                            row["tournamentid"],
                            stage,
                            "tournament search result tournamentid",
                        )
                    ),
                    matching_group_name=_require_nonempty_string(
                        row["name"],
                        stage,
                        "tournament search result group name",
                    ),
                    tournament_name=_require_nonempty_string(
                        row["tournamentname"],
                        stage,
                        "tournament search result tournament name",
                    ),
                    latest_updated_game=latest_updated_game,
                )
            )
        return results

    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        """Resolve and validate one tournament for the verified picker."""
        if not is_positive_integer(tournament_id):
            raise TournamentResolutionError(
                tournament_id, "id must be a positive integer"
            )

        stage = f"resolving canonical tournament {tournament_id}"
        path = f"/tournament/tournament/id/{tournament_id}"
        try:
            return self._validated_request(
                "canonical-tournament",
                path,
                stage,
                self.short_cache_ttl,
                lambda data: self._canonical_tournament_from_data(
                    tournament_id, data, stage
                ),
            )
        except UpstreamResponseError as error:
            if error.status_code == 404:
                raise TournamentResolutionError(
                    tournament_id, "not found"
                ) from error
            raise

    @staticmethod
    def _canonical_tournament_from_data(
        tournament_id: int,
        data: JsonValue,
        stage: str,
    ) -> CanonicalTournament:
        tournament = _require_mapping(data, stage)
        _require_fields(
            tournament,
            {"id", "name", "start", "end", "rootClasses"},
            stage,
            "tournament",
        )
        resolved_id = _require_positive_int(
            tournament["id"], stage, "tournament id"
        )
        if resolved_id != tournament_id:
            raise UpstreamDataError(
                stage,
                f"response tournament id {resolved_id} does not match requested id",
            )

        name = _require_nonempty_string(
            tournament["name"], stage, "tournament name"
        )
        start_date = _require_iso_date(
            tournament["start"], stage, "tournament start"
        )
        end_date = _require_iso_date(tournament["end"], stage, "tournament end")
        if end_date < start_date:
            raise UpstreamDataError(
                stage, "tournament end cannot be before its start"
            )

        processable_groups = _processable_tournament_groups(
            tournament["rootClasses"],
            stage,
            tournament_id,
            name,
            start_date,
            end_date,
        )

        if not processable_groups:
            raise TournamentResolutionError(
                tournament_id, "no processable Flickornas group"
            )

        return CanonicalTournament(
            tournament_id=TournamentId(resolved_id),
            name=name,
            start_date=start_date,
            end_date=end_date,
            processable_groups=processable_groups,
        )

    def player_name_search(
        self, first_name: str, last_name: str
    ) -> list[PlayerInfo]:
        stage = "searching players by name"
        first_name = _require_nonempty_string(first_name, stage, "first name")
        last_name = _require_nonempty_string(last_name, stage, "last name")
        path = (
            f"/player/fornamn/{quote(first_name, safe='')}"
            f"/efternamn/{quote(last_name, safe='')}"
        )
        return self._validated_request(
            "player-name-search",
            path,
            stage,
            self.short_cache_ttl,
            lambda data: [
                _player_info(value, stage, "player search result")
                for value in _require_list(data, stage)
            ],
        )

    def _validated_request(
        self,
        contract: str,
        path: str,
        stage: str,
        ttl: float,
        validator: Callable[[JsonValue], Any],
    ) -> Any:
        key = (contract, path)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                if cached.expires_at > self.clock():
                    return deepcopy(cached.value)
                del self._cache[key]

        value = validator(self._get_json(path, stage))
        if ttl > 0:
            entry = _CacheEntry(self.clock() + ttl, deepcopy(value))
            with self._cache_lock:
                self._cache[key] = entry
        return value

    def _get_json(self, path: str, stage: str) -> JsonValue:
        url = f"{self.base_url}{path}"
        last_failure = "unknown transient error"

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as error:
                last_failure = f"{type(error).__name__}: {error}"
                if attempt == self.max_attempts:
                    break
                self._backoff(attempt)
                continue

            if response.status_code == 429 or 500 <= response.status_code <= 599:
                last_failure = f"HTTP {response.status_code}"
                if attempt == self.max_attempts:
                    break
                self._backoff(attempt)
                continue

            if not 200 <= response.status_code <= 299:
                raise UpstreamResponseError(
                    stage,
                    f"HTTP {response.status_code} (not retried)",
                    status_code=response.status_code,
                )

            try:
                return response.json()
            except (TypeError, ValueError) as error:
                raise UpstreamDataError(stage, "response was not valid JSON") from error

        raise UpstreamRetryExhausted(
            stage,
            f"{last_failure}; exhausted {self.max_attempts} attempts",
        )

    def _backoff(self, failed_attempt: int) -> None:
        delay = self.backoff_seconds * failed_attempt
        if delay:
            self.sleep(delay)

    @staticmethod
    def _list_of_objects(
        data: JsonValue,
        required_fields: set[str],
        stage: str,
        subject: str,
    ) -> list[Mapping[str, Any]]:
        values = _require_list(data, stage)
        result = []
        for value in values:
            item = _require_mapping(value, stage)
            _require_fields(item, required_fields, stage, subject)
            result.append(item)
        return result


def resolve_canonical_tournaments(
    client: MemberSystemClient,
    tournament_ids: Sequence[int],
    *,
    collect_problems: bool = False,
) -> TournamentResolutionResult:
    """Resolve tournaments once and apply the shared chronological order."""
    tournaments: list[CanonicalTournament] = []
    problems: list[TournamentResolutionProblem] = []
    for tournament_id in tournament_ids:
        try:
            tournaments.append(client.canonical_tournament(tournament_id))
        except TournamentResolutionError as error:
            if not collect_problems:
                raise
            problems.append(
                TournamentResolutionProblem(
                    tournament_id=tournament_id,
                    detail=error.detail,
                    klass_problems=getattr(error, "klass_problems", ()),
                )
            )
    tournaments.sort(
        key=lambda tournament: (
            tournament.start_date,
            int(tournament.tournament_id),
        )
    )
    return TournamentResolutionResult(tuple(tournaments), tuple(problems))
