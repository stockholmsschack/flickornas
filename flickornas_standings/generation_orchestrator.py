"""Synchronous, in-memory orchestration for a Flickornas generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .active_configuration import (
    ActiveConfiguration,
    ConfigurationValidationError,
    validate_active_configuration,
)
from .calendar_year import (
    DefaultTournamentYearError,
    TournamentYearState,
    assess_tournament_years,
    require_current_default_tournaments,
)
from .generation_core import (
    GenerationDiagnostics,
    GenerationResult,
    TournamentInput,
    build_generation_result,
    collate_standings,
)
from .generation_progress import ProgressReporter, operation
from .member_system_client import (
    CanonicalTournament,
    MemberSystemClient,
    ProcessableTournamentGroup,
    TournamentResolutionProblem,
    TournamentKlassNamingError,
    resolve_canonical_tournaments,
)
from .klass_naming import KlassNamingProblem
from .numeric_validation import is_positive_integer


DISTRICT_ID = 5821
JDM_NAME_MARKERS = ("Junior-DM", "JuniorDM", "JDM", "Flick-DM", "FlickDM")


class GenerationStageError(RuntimeError):
    """A terminal generation failure attributed to one pipeline stage."""

    def __init__(self, stage: str, detail: str) -> None:
        self.stage = stage
        super().__init__(f"generation failed during {stage}: {detail}")


class GenerationValidationError(GenerationStageError):
    """Raised when configuration or resolved inputs cannot start a generation."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("validation", "; ".join(self.problems))


class KlassNamingError(GenerationValidationError):
    """Group names that must be corrected before generation."""

    def __init__(self, klass_problems: Sequence[KlassNamingProblem]) -> None:
        self.klass_problems = tuple(klass_problems)
        super().__init__(tuple(map(str, self.klass_problems)))

    def report(self) -> str:
        return (
            "Rename these groups in the member system and try again:\n"
            + "\n".join(self.problems)
        )


class TournamentSelectionValidationError(GenerationValidationError):
    """Raised with every selected tournament that cannot be resolved."""

    def __init__(self, problems: Sequence[TournamentResolutionProblem]) -> None:
        self.tournament_problems = tuple(problems)
        super().__init__(
            tuple(
                f"tournament {problem.tournament_id} cannot be resolved: "
                f"{problem.detail}"
                for problem in self.tournament_problems
            )
        )


class GenerationTournamentYearError(GenerationValidationError):
    """Raised when configured tournament years cannot run as defaults."""

    def __init__(self, state: TournamentYearState, problem: str) -> None:
        self.state = state
        super().__init__((problem,))


@dataclass(frozen=True)
class GenerationInputs:
    effective_year: int
    tournament_ids: tuple[int, ...]
    is_partial: bool = False
    layout: str = "auto"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tournament_ids", tuple(self.tournament_ids))


@dataclass(frozen=True)
class ResolvedGenerationRequest:
    """Validated run inputs and their authoritative tournament snapshot."""

    inputs: GenerationInputs
    tournaments: tuple[CanonicalTournament, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tournaments", tuple(self.tournaments))


def resolve_generation_inputs(
    configuration: ActiveConfiguration,
    *,
    explicit_year: int | None = None,
    explicit_tournament_ids: Sequence[int] | None = None,
    current_calendar_year: int,
    layout: str = "auto",
) -> GenerationInputs:
    """Resolve and validate one run's inputs at the application boundary."""
    tournament_ids = (
        configuration.default_tournament_ids
        if explicit_tournament_ids is None
        else tuple(explicit_tournament_ids)
    )
    inputs = GenerationInputs(
        effective_year=(
            current_calendar_year
            if explicit_year is None
            else explicit_year
        ),
        tournament_ids=tournament_ids,
        is_partial=explicit_tournament_ids is not None,
        layout=layout,
    )

    problems: list[str] = []
    if (
        explicit_year is not None
        and explicit_year != current_calendar_year
        and explicit_tournament_ids is None
    ):
        problems.append(
            "an explicit non-current year requires explicit tournament ids"
        )
    try:
        validate_generation_request(configuration, inputs)
    except GenerationValidationError as error:
        problems.extend(error.problems)
    if problems:
        raise GenerationValidationError(problems)
    return inputs


def resolve_generation_request(
    configuration: ActiveConfiguration,
    inputs: GenerationInputs,
    client: MemberSystemClient,
    *,
    collect_tournament_problems: bool = False,
) -> ResolvedGenerationRequest:
    """Validate and resolve the complete input snapshot for one run."""
    validate_generation_request(configuration, inputs)
    try:
        resolution = resolve_canonical_tournaments(
            client,
            inputs.tournament_ids,
            collect_problems=collect_tournament_problems,
        )
    except TournamentKlassNamingError as error:
        raise KlassNamingError(error.klass_problems) from error
    if resolution.problems:
        raise TournamentSelectionValidationError(resolution.problems)

    tournaments = resolution.tournaments
    ordered_inputs = GenerationInputs(
        effective_year=inputs.effective_year,
        tournament_ids=tuple(
            int(tournament.tournament_id) for tournament in tournaments
        ),
        is_partial=inputs.is_partial,
        layout=inputs.layout,
    )
    if not ordered_inputs.is_partial:
        _require_current_tournament_year(tournaments, inputs.effective_year)
    return ResolvedGenerationRequest(ordered_inputs, tournaments)


@dataclass(frozen=True)
class _Group:
    tournament_name: str
    tournament_date: str
    group_id: int
    klass: str
    registered_rounds: int


def run_generation(
    configuration: ActiveConfiguration,
    request: ResolvedGenerationRequest | GenerationInputs,
    client: MemberSystemClient,
    *,
    progress: ProgressReporter | None = None,
) -> GenerationResult:
    """Run validation, upstream fetching, calculation, and artifacts once."""
    with operation(progress, "Validating configuration"):
        inputs = (
            request.inputs
            if isinstance(request, ResolvedGenerationRequest)
            else request
        )
        validate_generation_request(configuration, inputs)

    try:
        resolved = (
            request
            if isinstance(request, ResolvedGenerationRequest)
            else resolve_generation_request(
                configuration, request, client, collect_tournament_problems=True
            )
        )
    except TournamentSelectionValidationError as error:
        klass_problems = tuple(
            klass_problem for failure in error.tournament_problems
            for klass_problem in failure.klass_problems
        )
        if klass_problems:
            raise KlassNamingError(klass_problems) from error
        raise
    except GenerationValidationError:
        raise
    except Exception as error:
        raise GenerationStageError("fetching", str(error)) from error

    inputs = resolved.inputs

    try:
        tournaments, player_list, stats, diagnostics = _fetch_inputs(
            configuration,
            inputs,
            resolved.tournaments,
            client,
            progress,
            report_tournament_resolution=not isinstance(
                request, ResolvedGenerationRequest
            ),
        )
    except GenerationStageError:
        raise
    except Exception as error:
        raise GenerationStageError("fetching", str(error)) from error

    if progress is not None:
        progress.begin_phase("Processing results", 5, "steps")

    try:
        with operation(progress, "Calculating standings"):
            standings = collate_standings(
                effective_year=inputs.effective_year,
                tournaments=tournaments,
                player_list=player_list,
                tournament_stats=stats,
                contributor=configuration.contributor,
                diagnostics=diagnostics,
            )
    except Exception as error:
        raise GenerationStageError("calculation", str(error)) from error

    try:
        with operation(progress, "Producing output artifacts"):
            return build_generation_result(
                standings,
                layout_configuration=configuration.layout,
                club_display_names=configuration.club_display_names,
                finals_separators=configuration.finals_separators,
                layout=inputs.layout,
            )
    except Exception as error:
        raise GenerationStageError("artifact production", str(error)) from error


def validate_generation_request(
    configuration: ActiveConfiguration,
    inputs: GenerationInputs,
) -> None:
    """Report every persisted-setting and resolved-input problem at once."""
    problems: list[str] = []
    try:
        validate_active_configuration(configuration)
    except ConfigurationValidationError as error:
        problems.extend(error.problems)

    problems.extend(_generation_input_problems(inputs))
    if problems:
        raise GenerationValidationError(problems)


def validate_generation_inputs(inputs: GenerationInputs) -> None:
    """Report every problem in one operation's resolved inputs."""
    problems = _generation_input_problems(inputs)
    if problems:
        raise GenerationValidationError(problems)


def _generation_input_problems(inputs: GenerationInputs) -> list[str]:
    problems: list[str] = []
    if (
        isinstance(inputs.effective_year, bool)
        or not isinstance(inputs.effective_year, int)
        or not 1900 <= inputs.effective_year <= 9999
    ):
        problems.append("effective_year must be a four-digit integer")

    tournament_ids = inputs.tournament_ids
    valid_tournament_ids = [
        tournament_id
        for tournament_id in tournament_ids
        if is_positive_integer(tournament_id)
    ]
    if not tournament_ids:
        problems.append("at least one tournament id is required")
    if len(valid_tournament_ids) != len(tournament_ids):
        problems.append("tournament ids must be positive integers")
    if len(set(valid_tournament_ids)) != len(valid_tournament_ids):
        problems.append("tournament ids must be unique")
    if not isinstance(inputs.is_partial, bool):
        problems.append("is_partial must be a boolean")
    if inputs.layout not in {"auto", "portrait", "landscape"}:
        problems.append("layout must be auto, portrait, or landscape")

    return problems


def _require_current_tournament_year(
    tournaments: Sequence[CanonicalTournament],
    effective_year: int,
) -> None:
    assessment = assess_tournament_years(
        (tournament.start_date for tournament in tournaments),
        effective_year,
    )
    try:
        require_current_default_tournaments(assessment)
    except DefaultTournamentYearError as error:
        if assessment.state is TournamentYearState.STALE:
            problem = (
                "configured tournaments belong to a previous year; "
                f"start the {effective_year} season or supply an explicit "
                "year and tournament selection"
            )
        elif assessment.state is TournamentYearState.MIXED:
            problem = (
                "configured tournaments span multiple calendar years; "
                "replace the defaults or supply an explicit year and "
                "tournament selection"
            )
        else:
            problem = (
                "configured tournaments start in a future calendar year; "
                "replace the defaults or supply an explicit year and "
                "tournament selection"
            )
        raise GenerationTournamentYearError(assessment.state, problem) from error


def _fetch_inputs(
    configuration: ActiveConfiguration,
    inputs: GenerationInputs,
    canonical_tournaments: tuple[CanonicalTournament, ...],
    client: MemberSystemClient,
    progress: ProgressReporter | None,
    *,
    report_tournament_resolution: bool = False,
) -> tuple[
    tuple[TournamentInput, ...],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    GenerationDiagnostics,
]:
    tournament_count = len(canonical_tournaments)
    if progress is not None:
        progress.begin_phase(
            "Fetching tournaments",
            tournament_count,
            "tournaments",
        )
        if report_tournament_resolution:
            for tournament in canonical_tournaments:
                progress.start(
                    "Resolving tournament "
                    f"{int(tournament.tournament_id)}"
                )

    request_date = max(
        tournament.end_date for tournament in canonical_tournaments
    )
    if progress is not None:
        progress.start("Fetching district players and clubs")
    local_player_ids = {
        int(player["id"])
        for player in client.district_rating_list(DISTRICT_ID, request_date)
    }
    local_club_ids = {
        int(club.club_id) for club in client.district_clubs(DISTRICT_ID)
    }

    tournament_inputs = []
    player_list: dict[str, dict[str, Any]] = {}
    tournament_stats: dict[str, dict[str, Any]] = {}
    walkovers: dict[str, list[str]] = {}
    no_matches_played: dict[str, list[str]] = {}
    dropouts: dict[str, list[str]] = {}
    round_count_mismatches = []

    for tournament_number, tournament in enumerate(
        canonical_tournaments,
        start=1,
    ):
        tournament_id = int(tournament.tournament_id)
        tournament_name = tournament.name
        if progress is not None:
            progress.start(
                f"Fetching tournament {tournament_number}/{tournament_count}: "
                f"{tournament_name}"
            )
        groups = _generation_groups(tournament)

        records = []
        for group in groups:
            group_records = [
                deepcopy(dict(record))
                for record in client.group_table(group.group_id)
            ]
            _add_players(
                group_records,
                player_list,
                local_club_ids,
                local_player_ids,
            )
            no_shows, group_dropouts, actual_rounds = _player_status(
                client.group_round_results(group.group_id),
                group.registered_rounds,
            )
            if actual_rounds != group.registered_rounds:
                round_count_mismatches.append(
                    f"group {group.group_id} in {tournament_name}: "
                    f"expected {group.registered_rounds}, got {actual_rounds}"
                )
            for player_id in group_dropouts:
                player = player_list.get(str(player_id))
                if player is not None:
                    dropouts.setdefault(tournament_name, []).append(
                        f"{player['name']} ({player_id})"
                    )

            records.extend(
                _prepare_group_records(
                    group_records,
                    group,
                    no_shows,
                    group_dropouts,
                    player_list,
                    walkovers,
                    no_matches_played,
                )
            )

        identifier = str(tournament_id)
        tournament_inputs.append(
            TournamentInput(
                identifier=identifier,
                source_name=f"{groups[0].tournament_date}-{identifier}.json",
                records=tuple(records),
            )
        )
        tournament_stats[identifier] = {
            "name": tournament_name,
            "nrofplayers": len(records),
            "jdm": any(marker in tournament_name for marker in JDM_NAME_MARKERS),
        }
        if progress is not None:
            progress.complete()

    _apply_known_local_overrides(
        player_list,
        configuration.known_local_players,
    )
    diagnostics = GenerationDiagnostics(
        walkovers=walkovers,
        no_matches_played=no_matches_played,
        dropouts=dropouts,
        round_count_mismatches=tuple(round_count_mismatches),
    )
    return (
        tuple(tournament_inputs),
        player_list,
        tournament_stats,
        diagnostics,
    )


def _generation_groups(tournament: CanonicalTournament) -> tuple[_Group, ...]:
    return tuple(
        _generation_group(tournament, group)
        for group in tournament.processable_groups
    )


def _generation_group(
    tournament: CanonicalTournament,
    group: ProcessableTournamentGroup,
) -> _Group:
    return _Group(
        tournament_name=tournament.name,
        tournament_date=tournament.start_date.strftime("%Y%m%d"),
        group_id=int(group.group_id),
        klass=group.klass,
        registered_rounds=group.registered_rounds,
    )


def _add_players(
    records: Sequence[Mapping[str, Any]],
    player_list: dict[str, dict[str, Any]],
    local_club_ids: set[int],
    local_player_ids: set[int],
) -> None:
    for record in records:
        player = record["playerInfo"]
        player_id = int(record["contenderId"])
        club_id = player.get("clubId")
        player_list[str(player_id)] = {
            "klubb": player.get("club"),
            "local": club_id in local_club_ids or player_id in local_player_ids,
            "name": f"{player.get('firstName')} {player.get('lastName')}",
            "gender": player.get("sex"),
            "playdate": player.get("birthdate"),
        }


def _player_status(
    rounds: Sequence[Mapping[str, Any]],
    registered_rounds: int,
) -> tuple[set[int], set[int], int]:
    statuses: dict[int, list[str]] = {}
    actual_rounds = 0
    for round_result in rounds:
        actual_rounds = max(actual_rounds, int(round_result["roundNr"]))
        for game in round_result["games"]:
            white_id = int(game["whiteId"])
            black_id = int(game["blackId"])
            if white_id == -100 and black_id == -100:
                continue
            result = game["result"]
            if white_id == -100:
                statuses.setdefault(black_id, []).append("played")
                continue
            if black_id == -100:
                statuses.setdefault(white_id, []).append("played")
                continue
            statuses.setdefault(white_id, [])
            statuses.setdefault(black_id, [])
            if result == 2:
                statuses[black_id].append("walkover_loss")
                statuses[white_id].append("played")
            elif result == -2:
                statuses[white_id].append("walkover_loss")
                statuses[black_id].append("played")
            else:
                statuses[white_id].append("played")
                statuses[black_id].append("played")

    expected_rounds = (
        actual_rounds if actual_rounds != registered_rounds else registered_rounds
    )
    no_shows = {
        player_id
        for player_id, results in statuses.items()
        if set(results) == {"walkover_loss"}
    }
    dropouts = {
        player_id
        for player_id, results in statuses.items()
        if results[-1] == "walkover_loss" or len(results) != expected_rounds
    }
    return no_shows, dropouts, actual_rounds


def _prepare_group_records(
    records: Sequence[dict[str, Any]],
    group: _Group,
    no_shows: set[int],
    group_dropouts: set[int],
    player_list: Mapping[str, Mapping[str, Any]],
    walkovers: dict[str, list[str]],
    no_matches_played: dict[str, list[str]],
) -> list[dict[str, Any]]:
    prepared = []
    for record in records:
        player_id = int(record["contenderId"])
        player_name = str(player_list[str(player_id)]["name"])
        if player_id in no_shows:
            walkovers.setdefault(group.tournament_name, []).append(
                f"{player_name} ({player_id})"
            )
            continue
        if not any(
            record[field] for field in ("wonGames", "drawGames", "lostGames")
        ):
            no_matches_played.setdefault(group.tournament_name, []).append(
                player_name
            )
            continue
        if player_id in group_dropouts:
            record["points"] *= -1
            record["secPoints"] *= -1
        record["klass"] = group.klass
        record["scaled_pts"] = record["points"] / group.registered_rounds
        prepared.append(record)
    return prepared


def _apply_known_local_overrides(
    player_list: dict[str, dict[str, Any]],
    known_local_players: Mapping[str, str],
) -> None:
    for player_id, club_name in known_local_players.items():
        player = player_list.get(str(player_id))
        if player is not None:
            player["local"] = True
            player["klubb"] = club_name
