"""Server-rendered pages and browser-facing API adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from ..active_configuration import (
    ActiveConfiguration,
    ConfigurationValidationError,
    DEFAULT_CONTRIBUTOR_EMAIL,
    DEFAULT_CONTRIBUTOR_NAME,
    StaleConfigurationError,
    load_configuration,
    save_configuration,
)
from ..calendar_year import (
    TournamentYearAssessment,
    TournamentYearState,
    assess_tournament_years,
    stockholm_today,
)
from ..generation_orchestrator import (
    DISTRICT_ID,
    GenerationTournamentYearError,
    ResolvedGenerationRequest,
    TournamentSelectionValidationError,
    resolve_generation_request as resolve_application_generation_request,
    GenerationValidationError,
    resolve_generation_inputs,
)
from ..member_system_client import (
    CanonicalClub,
    CanonicalTournament,
    MemberSystemClient,
    PlayerInfo,
    TournamentGroupSearchHit,
    TournamentResolutionError,
    TournamentKlassNamingError,
    UpstreamError,
    resolve_canonical_tournaments,
)
from ..numeric_validation import is_non_negative_integer, is_positive_integer
from ..typst_rules import (
    MAX_RULES_FILE_BYTES,
    RulesFileValidationError,
    custom_rules_path,
    effective_rules_path,
    restore_built_in_rules,
    save_rules_file,
)

from .available_files import list_available_files, list_report_files
from .errors import json_error, register_error_handlers
from .klass_naming import klass_naming_problems
from .generation_operations import (
    GenerationBusyError,
    GenerationOperationManager,
)
from .localization import register_localization


pages = Blueprint("flickornas", __name__, template_folder="templates", static_folder="static")
register_localization(pages)
register_error_handlers(pages)

TOURNAMENT_DRAFT_SESSION_KEY = "flickornas.tournament_draft"
PLAYER_OVERRIDE_DRAFT_SESSION_KEY = "flickornas.player_override_draft"


@dataclass(frozen=True)
class _ResolvedGenerationSubmission:
    configuration: ActiveConfiguration
    request: ResolvedGenerationRequest


def _flickornas() -> dict[str, Any]:
    return current_app.extensions["flickornas"]


@pages.before_request
def _protect_mutations():
    """Let the host's `MUTATION_PROTECTION`, when supplied, reject any Flickornas POST, PUT or DELETE."""
    protect = _flickornas()["settings"].get("MUTATION_PROTECTION")
    if protect and request.method not in ("GET", "HEAD", "OPTIONS") and not protect():
        abort(403)


@pages.context_processor
def _base_template() -> dict[str, str]:
    settings = _flickornas()["settings"]
    return {
        "flickornas_base_template": settings["BASE_TEMPLATE"],
        "flickornas_mercure_hub": settings["MERCURE_PUBLIC_URL"],
    }


def _state_directory() -> Path:
    return Path(_flickornas()["settings"]["STATE_DIRECTORY"])


def _output_directory() -> Path:
    return Path(_flickornas()["settings"]["OUTPUT_DIRECTORY"])


def _files_public_origin() -> str:
    return _flickornas()["settings"]["FILES_PUBLIC_ORIGIN"]


def _member_system_client() -> MemberSystemClient:
    return _flickornas()["member_system_client"]


def _district_clubs() -> tuple[CanonicalClub, ...]:
    client = _member_system_client()
    if isinstance(client, MemberSystemClient):
        return tuple(client.district_clubs(DISTRICT_ID))

    cached = _flickornas().get("injected_client_clubs")
    if cached is None:
        cached = tuple(client.district_clubs(DISTRICT_ID))
        _flickornas()["injected_client_clubs"] = cached
    return cached


def _generation_operations() -> GenerationOperationManager:
    return _flickornas()["generation_operations"]


def _current_stockholm_date() -> date:
    return stockholm_today(_flickornas()["settings"]["CLOCK"])


def _actor() -> str | None:
    actor = _flickornas()["settings"].get("ACTOR")
    return actor() if actor else None


def _can_select_generation_tournaments() -> bool:
    # Require an administrator check from the host or standalone `create_app`.
    authorizer = _flickornas()["settings"].get(
        "GENERATION_TOURNAMENT_SELECTION_AUTHORIZER"
    )
    if authorizer is None:
        return False
    return bool(authorizer()) if callable(authorizer) else bool(authorizer)


def local_host_request() -> bool:
    """Authorize standalone requests whose Host header identifies a local machine."""
    hostname = urlsplit(f"//{request.host}").hostname
    if hostname is not None:
        normalized_hostname = hostname.rstrip(".").lower()
        if (
            normalized_hostname == "localhost"
            or normalized_hostname.endswith(".localhost")
        ):
            return True
        try:
            if ipaddress.ip_address(normalized_hostname).is_loopback:
                return True
        except ValueError:
            pass
    return False


def _configuration_state():
    try:
        return load_configuration(_state_directory()), None
    except ConfigurationValidationError as error:
        return None, tuple(error.problems)


def _active_configuration() -> ActiveConfiguration:
    """Load the validated active configuration for an API request."""
    return load_configuration(_state_directory())


def _current_configuration(revision: int) -> ActiveConfiguration:
    """Load configuration and enforce a submitted revision before mutation."""
    configuration = _active_configuration()
    if revision != configuration.revision:
        raise StaleConfigurationError(
            f"configuration revision {revision} is stale; current revision is "
            f"{configuration.revision}",
            current_revision=configuration.revision,
        )
    return configuration


def _search_result(
    tournament_id: int,
    tournament_name: str,
    matches: list[TournamentGroupSearchHit],
) -> dict[str, Any]:
    return {
        "tournament_id": tournament_id,
        "name": tournament_name,
        "matching_groups": [
            {
                "group_id": int(match.matching_group_id),
                "name": match.matching_group_name,
                "latest_updated_game": match.latest_updated_game,
            }
            for match in matches
        ],
    }


def _group_search_hits(
    hits: list[TournamentGroupSearchHit],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[TournamentGroupSearchHit]] = {}
    for hit in hits:
        tournament_id = int(hit.tournament_id)
        grouped.setdefault(tournament_id, []).append(hit)

    grouped_tournaments = sorted(
        grouped.items(),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        _search_result(
            tournament_id,
            matches[0].tournament_name,
            matches,
        )
        for tournament_id, matches in grouped_tournaments
    ]


def _canonical_tournament_result(
    tournament: CanonicalTournament,
) -> dict[str, Any]:
    return {
        "tournament_id": int(tournament.tournament_id),
        "name": tournament.name,
        "start_date": tournament.start_date.isoformat(),
        "end_date": tournament.end_date.isoformat(),
        "processable_groups": [
            {
                "group_id": int(group.group_id),
                "name": group.name,
                "klass": group.klass,
            }
            for group in tournament.processable_groups
        ],
    }


def _player_result(player: PlayerInfo) -> dict[str, Any]:
    return {
        "player_id": int(player.player_id),
        "first_name": player.first_name,
        "last_name": player.last_name,
        "birth_year": player.birth_year,
        "current_club": {
            "club_id": (
                int(player.current_club_id)
                if player.current_club_id is not None
                else None
            ),
            "name": player.current_club_name,
        },
        "country": player.country,
        "fide_id": player.fide_id,
    }


def _club_result(club: CanonicalClub) -> dict[str, Any]:
    return {
        "club_id": int(club.club_id),
        "name": club.name,
    }


def _tournament_summary(tournament: CanonicalTournament) -> dict[str, Any]:
    return {
        "tournament_id": int(tournament.tournament_id),
        "name": tournament.name,
        "start_date": tournament.start_date.isoformat(),
        "end_date": tournament.end_date.isoformat(),
    }


def _klass_naming_error(error: TournamentKlassNamingError):
    return json_error(
        "klass_naming", "errors.klass_naming.heading", 422,
        details={"problems": klass_naming_problems(error.klass_problems)},
    )


@pages.get("/help/group-names")
def klass_naming_help():
    """Show naming conventions in the organiser's chosen language."""
    return render_template("flickornas/klass_naming.jinja2")


def _generation_problem(
    field: str,
    message_key: str,
    **parameters: object,
) -> dict[str, Any]:
    return {
        "field": field,
        "message_key": message_key,
        "parameters": parameters,
    }


def _generation_input_error(problems: list[dict[str, Any]]):
    return json_error(
        "invalid_generation_inputs",
        "errors.generation.invalid_input",
        422,
        details={"problems": problems},
    )


def _resolve_tournaments(
    tournament_ids: tuple[int, ...],
) -> tuple[CanonicalTournament, ...]:
    return resolve_canonical_tournaments(
        _member_system_client(), tournament_ids, collect_problems=True
    ).require_all()


def _positive_integer(value: object) -> int | None:
    if not is_positive_integer(value):
        return None
    assert isinstance(value, int)
    return value


def _submitted_revision(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    revision = payload.get("revision")
    if not is_non_negative_integer(revision):
        return None
    assert isinstance(revision, int)
    return revision


def _submitted_tournament_ids(payload: object) -> tuple[int, ...] | None:
    if not isinstance(payload, dict):
        return None
    values = payload.get("tournament_ids")
    if not isinstance(values, list):
        return None
    tournament_ids: list[int] = []
    for value in values:
        tournament_id = _positive_integer(value)
        if tournament_id is None:
            return None
        tournament_ids.append(tournament_id)
    if not tournament_ids or len(set(tournament_ids)) != len(tournament_ids):
        return None
    return tuple(tournament_ids)


def _draft_tournament(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    tournament_id = _positive_integer(value.get("tournament_id"))
    name = value.get("name")
    start_date = value.get("start_date")
    end_date = value.get("end_date")
    if (
        tournament_id is None
        or not isinstance(name, str)
        or not name.strip()
        or not isinstance(start_date, str)
        or not isinstance(end_date, str)
    ):
        return None
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError:
        return None
    if parsed_end < parsed_start:
        return None
    return {
        "tournament_id": tournament_id,
        "name": name.strip(),
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
    }


def _tournament_draft_document_for(
    configuration: ActiveConfiguration,
    current_year: int,
) -> dict[str, Any] | None:
    draft = session.get(TOURNAMENT_DRAFT_SESSION_KEY)
    if (
        not isinstance(draft, dict)
        or draft.get("revision") != configuration.revision
        or not isinstance(draft.get("tournaments"), list)
    ):
        session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
        return None
    rollover_year = draft.get("rollover_year")
    if rollover_year is not None and rollover_year != current_year:
        session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
        return None
    tournaments: list[dict[str, Any]] = []
    for value in draft["tournaments"]:
        tournament = _draft_tournament(value)
        if tournament is None:
            session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
            return None
        tournaments.append(tournament)
    return {
        "revision": configuration.revision,
        "tournaments": tuple(tournaments),
        "rollover_year": rollover_year,
    }


def _tournament_year_assessment(
    tournaments: tuple[CanonicalTournament, ...],
    current_year: int,
) -> TournamentYearAssessment:
    return assess_tournament_years(
        (tournament.start_date for tournament in tournaments),
        current_year,
    )


def _player_override_draft(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    player_id = _positive_integer(value.get("player_id"))
    first_name = value.get("first_name")
    last_name = value.get("last_name")
    club_id = value.get("club_id")
    club_name = value.get("club_name")
    if (
        player_id is None
        or (
            first_name is not None
            and (not isinstance(first_name, str) or not first_name.strip())
        )
        or (
            last_name is not None
            and (not isinstance(last_name, str) or not last_name.strip())
        )
        or (first_name is None) != (last_name is None)
        or (
            club_id is not None
            and _positive_integer(club_id) is None
        )
        or not isinstance(club_name, str)
        or not club_name.strip()
    ):
        return None
    return {
        "player_id": player_id,
        "first_name": first_name.strip() if first_name is not None else None,
        "last_name": last_name.strip() if last_name is not None else None,
        "club_id": club_id,
        "club_name": club_name.strip(),
    }


def _player_override_drafts(
    values: object,
) -> tuple[dict[str, Any], ...] | None:
    if not isinstance(values, list):
        return None
    overrides: list[dict[str, Any]] = []
    player_ids: set[int] = set()
    for value in values:
        override = _player_override_draft(value)
        if override is None or override["player_id"] in player_ids:
            return None
        player_ids.add(override["player_id"])
        overrides.append(override)
    return tuple(overrides)


def _player_override_draft_for(
    configuration: ActiveConfiguration,
) -> tuple[dict[str, Any], ...] | None:
    draft = session.get(PLAYER_OVERRIDE_DRAFT_SESSION_KEY)
    if (
        not isinstance(draft, dict)
        or draft.get("revision") != configuration.revision
    ):
        session.pop(PLAYER_OVERRIDE_DRAFT_SESSION_KEY, None)
        return None
    overrides = _player_override_drafts(draft.get("overrides"))
    if overrides is None:
        session.pop(PLAYER_OVERRIDE_DRAFT_SESSION_KEY, None)
    return overrides


def _saved_player_overrides(
    configuration: ActiveConfiguration,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "player_id": int(player_id),
            "first_name": None,
            "last_name": None,
            "display_name": configuration.known_local_player_names.get(
                str(player_id)
            ),
            "club_id": None,
            "club_name": club_name,
        }
        for player_id, club_name in configuration.known_local_players.items()
    )


def _submitted_player_overrides(
    payload: object,
) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    values = payload.get("known_local_players")
    if not isinstance(values, dict):
        return None
    overrides: dict[str, str] = {}
    for raw_player_id, raw_club_name in values.items():
        if (
            not isinstance(raw_player_id, str)
            or not raw_player_id.isdigit()
            or str(int(raw_player_id)) != raw_player_id
            or int(raw_player_id) <= 0
            or not isinstance(raw_club_name, str)
            or not raw_club_name.strip()
        ):
            return None
        overrides[raw_player_id] = raw_club_name.strip()
    return overrides


def _submitted_player_names(
    payload: object,
    player_ids: set[str],
) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    values = payload.get("known_local_player_names", {})
    if not isinstance(values, dict):
        return None
    names: dict[str, str] = {}
    for raw_player_id, raw_player_name in values.items():
        if (
            raw_player_id not in player_ids
            or not isinstance(raw_player_name, str)
            or not raw_player_name.strip()
            or len(raw_player_name.strip()) > 200
        ):
            return None
        names[raw_player_id] = raw_player_name.strip()
    return names


def _submitted_contributor(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    email = payload.get("email")
    if not isinstance(name, str) or not isinstance(email, str):
        return None
    normalized_name = name.strip() or DEFAULT_CONTRIBUTOR_NAME
    normalized_email = email.strip() or DEFAULT_CONTRIBUTOR_EMAIL
    if (
        len(normalized_name) > 200
        or len(normalized_email) > 320
        or normalized_email.count("@") != 1
        or any(character.isspace() for character in normalized_email)
    ):
        return None
    local_part, domain = normalized_email.split("@")
    if (
        not local_part
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        return None
    return {"name": normalized_name, "email": normalized_email}


def _submitted_finals_separators(payload: object) -> tuple[int, ...] | None:
    if not isinstance(payload, dict):
        return None
    values = payload.get("finals_separators")
    if not isinstance(values, list) or not all(
        is_positive_integer(value) for value in values
    ):
        return None
    return tuple(sorted(set(values)))


def _submitted_club_display_name_change(
    payload: object,
) -> tuple[str, str, str | None] | None:
    if not isinstance(payload, dict):
        return None
    action = payload.get("action")
    canonical_name = payload.get("canonical_name")
    display_name = payload.get("display_name")
    if (
        action not in {"upsert", "remove"}
        or not isinstance(canonical_name, str)
        or not canonical_name.strip()
        or len(canonical_name.strip()) > 200
    ):
        return None
    normalized_canonical_name = canonical_name.strip()
    if action == "remove":
        if display_name is not None:
            return None
        return action, normalized_canonical_name, None
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name.strip()) > 200
    ):
        return None
    return action, normalized_canonical_name, display_name.strip()


@pages.get("/")
def landing():
    configuration, configuration_problems = _configuration_state()
    available_files = list_available_files(
        _output_directory(),
        _files_public_origin(),
    )
    return render_template(
        "flickornas/landing.jinja2",
        configuration=configuration,
        configuration_problems=configuration_problems,
        available_files=available_files,
    )


@pages.get("/configuration")
def configuration():
    active_configuration, problems = _configuration_state()
    current_year = _current_stockholm_date().year
    selected_tournaments: tuple[dict[str, Any], ...] = ()
    selected_player_overrides: tuple[dict[str, Any], ...] = ()
    selection_problem: str | None = None
    selection_klass_problems = []
    tournament_year_state: TournamentYearState | None = None
    rollover_active = False
    if active_configuration is not None:
        draft = _tournament_draft_document_for(
            active_configuration,
            current_year,
        )
        if draft is not None:
            selected_tournaments = draft["tournaments"]
            rollover_active = draft["rollover_year"] is not None
            if rollover_active:
                tournament_year_state = TournamentYearState.STALE
        else:
            try:
                configured_tournaments = _resolve_tournaments(
                    active_configuration.default_tournament_ids
                )
                tournament_year_state = _tournament_year_assessment(
                    configured_tournaments,
                    current_year,
                ).state
                selected_tournaments = tuple(
                    _tournament_summary(tournament)
                    for tournament in configured_tournaments
                )
            except TournamentKlassNamingError as error:
                selection_problem = "errors.klass_naming.heading"
                selection_klass_problems = klass_naming_problems(error.klass_problems)
            except (TournamentResolutionError, UpstreamError):
                selection_problem = "errors.member_system.unavailable"
        player_override_draft = _player_override_draft_for(
            active_configuration
        )
        selected_player_overrides = (
            player_override_draft
            if player_override_draft is not None
            else _saved_player_overrides(active_configuration)
        )
    return render_template(
        "flickornas/configuration.jinja2",
        configuration=active_configuration,
        configuration_problems=problems,
        selected_tournaments=selected_tournaments,
        selected_player_overrides=selected_player_overrides,
        club_display_names=(
            dict(active_configuration.club_display_names)
            if active_configuration is not None
            else {}
        ),
        selection_problem=selection_problem,
        selection_klass_problems=selection_klass_problems,
        current_year=current_year,
        tournament_year_state=tournament_year_state,
        rollover_active=rollover_active,
        can_select_generation_tournaments=(
            _can_select_generation_tournaments()
        ),
        default_contributor_name=DEFAULT_CONTRIBUTOR_NAME,
        default_contributor_email=DEFAULT_CONTRIBUTOR_EMAIL,
        has_custom_rules_file=custom_rules_path(_state_directory()).is_file(),
    )


@pages.get("/api/v1/configuration/rules")
def download_rules_file():
    return send_file(
        effective_rules_path(_state_directory()),
        as_attachment=True,
        download_name="rules.typ",
        mimetype="text/plain; charset=utf-8",
    )


@pages.post("/api/v1/configuration/rules")
def upload_rules_file():
    uploaded = request.files.get("rules")
    if (
        uploaded is None
        or not uploaded.filename
        or Path(uploaded.filename).suffix.lower() != ".typ"
    ):
        return json_error(
            "invalid_rules_file",
            "errors.rules_file.invalid",
            400,
        )

    content = uploaded.stream.read(MAX_RULES_FILE_BYTES + 1)
    try:
        save_rules_file(_state_directory(), content)
    except RulesFileValidationError as error:
        return json_error(
            "invalid_rules_file",
            "errors.rules_file.invalid",
            400,
            details={"reason": str(error)},
        )
    return jsonify({"data": {"filename": "rules.typ"}})


@pages.delete("/api/v1/configuration/rules")
def restore_rules_file():
    restored = restore_built_in_rules(_state_directory())
    return jsonify({"data": {"restored": restored}})


@pages.get("/downloads")
def available_files():
    return render_template(
        "flickornas/available_files.jinja2",
        available_files=list_available_files(
            _output_directory(),
            _files_public_origin(),
        ),
    )


@pages.get("/reports")
def reports():
    return render_template(
        "flickornas/reports.jinja2",
        report_files=list_report_files(
            _output_directory(),
            _files_public_origin(),
        ),
    )


@pages.post("/api/v1/downloads/clear")
def clear_available_files():
    """Remove every generated download without changing configuration."""
    try:
        retained_run_count = _generation_operations().clear_downloads()
    except GenerationBusyError as error:
        return json_error(
            "downloads_busy",
            "errors.downloads.operation_busy",
            409,
            details={"active_operation_id": error.operation_id},
        )
    except Exception:
        return json_error(
            "downloads_clear_failed",
            "errors.downloads.clear_failed",
            500,
        )

    return jsonify(
        {
            "data": {
                "cleared": True,
                "retained_run_count": retained_run_count,
            }
        }
    )


@pages.get("/runs")
def legacy_runs_redirect():
    return redirect(
        url_for("flickornas.available_files", lang=request.args.get("lang"))
    )


@pages.get("/api/v1/generation/defaults")
def generation_defaults():
    configuration = _active_configuration()

    try:
        tournaments = _resolve_tournaments(
            configuration.default_tournament_ids
        )
    except TournamentKlassNamingError as error:
        return _klass_naming_error(error)
    except TournamentResolutionError:
        return json_error(
            "tournament_unresolvable",
            "errors.tournament_lookup.unresolvable",
            422,
        )

    return jsonify(
        {
            "data": {
                "current_year": _current_stockholm_date().year,
                "configuration_revision": configuration.revision,
                "tournaments": [
                    _tournament_summary(tournament)
                    for tournament in tournaments
                ],
            }
        }
    )


def _resolve_generation_submission(payload: object):
    if not isinstance(payload, dict):
        return _generation_input_error(
            [
                _generation_problem(
                    "form",
                    "errors.generation.invalid_input",
                )
            ]
        )

    problems: list[dict[str, Any]] = []
    explicit_year = payload.get("year")
    valid_explicit_year = (
        explicit_year is not None
        and not isinstance(explicit_year, bool)
        and isinstance(explicit_year, int)
        and 1900 <= explicit_year <= 9999
    )
    if explicit_year is not None and not valid_explicit_year:
        problems.append(
            _generation_problem(
                "year",
                "errors.generation.year",
            )
        )

    layout = payload.get("layout", "auto")
    if (
        not isinstance(layout, str)
        or layout not in {"auto", "portrait", "landscape"}
    ):
        problems.append(
            _generation_problem(
                "layout",
                "errors.generation.layout",
            )
        )

    raw_tournament_ids = payload.get("tournament_ids")
    if (
        raw_tournament_ids is not None
        and not _can_select_generation_tournaments()
    ):
        return json_error(
            "generation_tournament_selection_forbidden",
            "errors.generation.tournament_selection_forbidden",
            403,
        )
    explicit_tournament_ids: tuple[int, ...] | None = None
    if raw_tournament_ids is not None:
        if not isinstance(raw_tournament_ids, list):
            problems.append(
                _generation_problem(
                    "tournaments",
                    "errors.generation.tournaments",
                )
            )
        else:
            parsed_ids = tuple(
                value
                for value in raw_tournament_ids
                if _positive_integer(value) is not None
            )
            if len(parsed_ids) != len(raw_tournament_ids):
                problems.append(
                    _generation_problem(
                        "tournaments",
                        "errors.generation.tournaments",
                    )
                )
            elif not parsed_ids:
                problems.append(
                    _generation_problem(
                        "tournaments",
                        "errors.generation.tournaments_required",
                    )
                )
            elif len(set(parsed_ids)) != len(parsed_ids):
                problems.append(
                    _generation_problem(
                        "tournaments",
                        "errors.generation.tournaments_unique",
                    )
                )
            else:
                explicit_tournament_ids = parsed_ids

    current_year = _current_stockholm_date().year
    if (
        valid_explicit_year
        and explicit_year != current_year
        and raw_tournament_ids is None
    ):
        problems.append(
            _generation_problem(
                "tournaments",
                "errors.generation.non_current_tournaments",
                year=explicit_year,
            )
        )
    if problems:
        return _generation_input_error(problems)

    configuration = _active_configuration()

    try:
        inputs = resolve_generation_inputs(
            configuration,
            explicit_year=explicit_year,
            explicit_tournament_ids=explicit_tournament_ids,
            current_calendar_year=current_year,
            layout=layout,
        )
        resolved = resolve_application_generation_request(
            configuration,
            inputs,
            _member_system_client(),
            collect_tournament_problems=True,
        )
    except TournamentSelectionValidationError as error:
        problems = []
        for problem in error.tournament_problems:
            if problem.klass_problems:
                problems.extend(klass_naming_problems(problem.klass_problems))
            else:
                problems.append(_generation_problem(
                    "tournaments", "errors.generation.tournament_unresolvable",
                    tournament_id=problem.tournament_id,
                ))
        return _generation_input_error(problems)
    except GenerationTournamentYearError as error:
        year_message_keys = {
            TournamentYearState.STALE: "errors.generation.defaults_stale",
            TournamentYearState.MIXED: "errors.generation.defaults_mixed",
            TournamentYearState.FUTURE: "errors.generation.defaults_future",
        }
        return _generation_input_error(
            [
                _generation_problem(
                    "tournaments",
                    year_message_keys[error.state],
                    year=inputs.effective_year,
                )
            ]
        )
    except GenerationValidationError:
        return _generation_input_error(
            [
                _generation_problem(
                    "form",
                    "errors.generation.invalid_input",
                )
            ]
        )

    return _ResolvedGenerationSubmission(configuration, resolved)


@pages.post("/api/v1/generation/inputs")
def resolve_generation_request():
    submission = _resolve_generation_submission(request.get_json(silent=True))
    if not isinstance(submission, _ResolvedGenerationSubmission):
        return submission

    inputs = submission.request.inputs
    tournaments = submission.request.tournaments
    publishes_by_default = not inputs.is_partial
    return jsonify(
        {
            "data": {
                "inputs": {
                    "effective_year": inputs.effective_year,
                    "tournament_ids": list(inputs.tournament_ids),
                    "is_partial": inputs.is_partial,
                    "layout": inputs.layout,
                },
                "tournaments": [
                    _tournament_summary(tournament)
                    for tournament in tournaments
                ],
                "publication": {
                    "pdf": publishes_by_default,
                    "json": publishes_by_default,
                },
            }
        }
    )


@pages.post("/api/v1/generation/operations")
def start_generation_operation():
    """Validate one request and start its exclusive background operation."""
    submission = _resolve_generation_submission(request.get_json(silent=True))
    if not isinstance(submission, _ResolvedGenerationSubmission):
        return submission

    resolved = submission.request
    configuration = submission.configuration

    try:
        operation = _generation_operations().start(
            configuration,
            resolved,
            _member_system_client(),
            # Capture the host's actor before starting the background run, which has no request context.
            actor=_actor(),
        )
    except GenerationBusyError as error:
        return json_error(
            "generation_busy",
            "errors.generation.busy",
            409,
            details={
                "active_operation_id": error.operation_id,
                "status_url": _generation_operations().store.status_url(error.operation_id),
            },
        )
    except Exception:
        return json_error(
            "generation_start_failed",
            "errors.generation.start_failed",
            500,
        )

    return jsonify({"data": operation.as_dict()}), 202


@pages.get("/api/v1/generation/operations/<operation_id>")
def generation_operation_status(operation_id: str):
    """Return the durable latest state without relying on event delivery."""
    try:
        operation = _generation_operations().store.load(operation_id)
    except FileNotFoundError:
        return json_error(
            "operation_not_found",
            "errors.generation.operation_not_found",
            404,
        )
    return jsonify({"data": operation.as_dict()})


@pages.get("/api/v1/tournaments/search")
def tournament_search():
    search_text = request.args.get("q")
    if search_text is None or not search_text.strip():
        return json_error(
            "invalid_input",
            "errors.tournament_search.invalid_input",
            400,
            details={"field": "q"},
        )

    query = search_text.strip()
    try:
        results = _group_search_hits(
            _member_system_client().tournament_group_search(query)
        )
    except TournamentKlassNamingError as error:
        return _klass_naming_error(error)

    state = "results" if results else "no_matches"
    return jsonify(
        {
            "data": {
                "state": state,
                "query": query,
                "tournaments": results,
            }
        }
    )


@pages.get("/api/v1/tournaments/<tournament_id>")
def canonical_tournament(tournament_id: str):
    try:
        parsed_tournament_id = int(tournament_id)
    except ValueError:
        parsed_tournament_id = 0
    if parsed_tournament_id <= 0 or str(parsed_tournament_id) != tournament_id:
        return json_error(
            "invalid_input",
            "errors.tournament_lookup.invalid_input",
            400,
            details={"field": "tournament_id"},
        )

    try:
        tournament = _member_system_client().canonical_tournament(
            parsed_tournament_id
        )
    except TournamentKlassNamingError as error:
        return _klass_naming_error(error)
    except TournamentResolutionError:
        return json_error(
            "tournament_unresolvable",
            "errors.tournament_lookup.unresolvable",
            422,
            details={"tournament_id": parsed_tournament_id},
        )

    return jsonify(
        {"data": {"tournament": _canonical_tournament_result(tournament)}}
    )


@pages.get("/api/v1/players/search")
def player_search():
    first_name = request.args.get("first_name")
    last_name = request.args.get("last_name")
    if (
        first_name is None
        or not first_name.strip()
        or last_name is None
        or not last_name.strip()
    ):
        return json_error(
            "invalid_input",
            "errors.player_search.invalid_input",
            400,
            details={"fields": ["first_name", "last_name"]},
        )

    normalized_first_name = first_name.strip()
    normalized_last_name = last_name.strip()
    players = [
        _player_result(player)
        for player in _member_system_client().player_name_search(
            normalized_first_name,
            normalized_last_name,
        )
    ]

    return jsonify(
        {
            "data": {
                "state": "results" if players else "no_matches",
                "query": {
                    "first_name": normalized_first_name,
                    "last_name": normalized_last_name,
                },
                "players": players,
            }
        }
    )


@pages.get("/api/v1/clubs")
def district_clubs():
    clubs = [_club_result(club) for club in _district_clubs()]

    return jsonify(
        {
            "data": {
                "state": "results" if clubs else "no_matches",
                "clubs": clubs,
            }
        }
    )


@pages.put("/api/v1/configuration/tournaments/draft")
def save_tournament_draft():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    raw_tournaments = (
        payload.get("tournaments") if isinstance(payload, dict) else None
    )
    if revision is None or not isinstance(raw_tournaments, list):
        return json_error(
            "invalid_input",
            "errors.configuration.invalid_input",
            400,
        )

    tournaments: list[dict[str, Any]] = []
    for value in raw_tournaments:
        tournament = _draft_tournament(value)
        if tournament is None:
            return json_error(
                "invalid_input",
                "errors.configuration.invalid_input",
                400,
            )
        tournaments.append(tournament)
    tournament_ids = [
        tournament["tournament_id"] for tournament in tournaments
    ]
    if len(set(tournament_ids)) != len(tournament_ids):
        return json_error(
            "invalid_input",
            "errors.configuration.invalid_input",
            400,
        )

    tournaments.sort(
        key=lambda tournament: (
            tournament["start_date"],
            tournament["tournament_id"],
        )
    )
    existing_draft = session.get(TOURNAMENT_DRAFT_SESSION_KEY)
    rollover_year = None
    if (
        isinstance(existing_draft, dict)
        and existing_draft.get("revision") == revision
    ):
        rollover_year = existing_draft.get("rollover_year")
    session[TOURNAMENT_DRAFT_SESSION_KEY] = {
        "revision": revision,
        "tournaments": tournaments,
        **(
            {"rollover_year": rollover_year}
            if isinstance(rollover_year, int)
            else {}
        ),
    }
    return jsonify({"data": {"saved": True}})


@pages.post("/api/v1/configuration/tournaments/rollover")
def start_tournament_rollover():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    if revision is None:
        return json_error(
            "invalid_input",
            "errors.configuration.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)

    current_year = _current_stockholm_date().year
    try:
        tournaments = _resolve_tournaments(
            configuration.default_tournament_ids
        )
    except TournamentKlassNamingError as error:
        return _klass_naming_error(error)
    except TournamentResolutionError:
        return json_error(
            "tournament_unresolvable",
            "errors.tournament_lookup.unresolvable",
            422,
        )

    assessment = _tournament_year_assessment(tournaments, current_year)
    if not assessment.rollover_available:
        return json_error(
            "rollover_unavailable",
            "errors.configuration.rollover_unavailable",
            409,
            details={
                "current_year": current_year,
                "configured_years": list(assessment.configured_years),
                "state": assessment.state.value,
            },
        )

    session[TOURNAMENT_DRAFT_SESSION_KEY] = {
        "revision": configuration.revision,
        "rollover_year": current_year,
        "tournaments": [],
    }
    return jsonify(
        {
            "data": {
                "revision": configuration.revision,
                "rollover_year": current_year,
                "started": True,
            }
        }
    )


@pages.delete("/api/v1/configuration/tournaments/rollover")
def cancel_tournament_rollover():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    if revision is None:
        return json_error(
            "invalid_input",
            "errors.configuration.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)

    draft = session.get(TOURNAMENT_DRAFT_SESSION_KEY)
    cancelled = bool(
        isinstance(draft, dict)
        and draft.get("revision") == revision
        and isinstance(draft.get("rollover_year"), int)
    )
    if cancelled:
        session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
    return jsonify(
        {
            "data": {
                "revision": configuration.revision,
                "cancelled": cancelled,
            }
        }
    )


@pages.put("/api/v1/configuration/player-overrides/draft")
def save_player_override_draft():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    raw_overrides = (
        payload.get("overrides") if isinstance(payload, dict) else None
    )
    if revision is None or not isinstance(raw_overrides, list):
        return json_error(
            "invalid_input",
            "errors.player_overrides.invalid_input",
            400,
        )

    overrides = _player_override_drafts(raw_overrides)
    if overrides is None:
        return json_error(
            "invalid_input",
            "errors.player_overrides.invalid_input",
            400,
        )

    session[PLAYER_OVERRIDE_DRAFT_SESSION_KEY] = {
        "revision": revision,
        "overrides": list(overrides),
    }
    return jsonify({"data": {"saved": True}})


@pages.post("/api/v1/configuration/player-overrides")
def save_player_overrides():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    overrides = _submitted_player_overrides(payload)
    player_names_supplied = (
        isinstance(payload, dict)
        and "known_local_player_names" in payload
    )
    player_names = _submitted_player_names(
        payload,
        set(overrides) if overrides is not None else set(),
    )
    if revision is None or overrides is None or player_names is None:
        return json_error(
            "invalid_input",
            "errors.player_overrides.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)

    current_overrides = dict(configuration.known_local_players)
    current_player_names = dict(configuration.known_local_player_names)
    if not player_names_supplied:
        player_names = {
            player_id: player_name
            for player_id, player_name in current_player_names.items()
            if player_id in overrides
        }
    if overrides == current_overrides and player_names == current_player_names:
        session.pop(PLAYER_OVERRIDE_DRAFT_SESSION_KEY, None)
        return jsonify(
            {
                "data": {
                    "revision": configuration.revision,
                    "known_local_players": overrides,
                    "known_local_player_names": player_names,
                    "changed": False,
                }
            }
        )

    changed_club_names = {
        club_name
        for player_id, club_name in overrides.items()
        if current_overrides.get(player_id) != club_name
    }
    if changed_club_names:
        canonical_club_names = {club.name for club in _district_clubs()}
        noncanonical_names = sorted(
            changed_club_names - canonical_club_names
        )
        if noncanonical_names:
            return json_error(
                "noncanonical_club",
                "errors.player_overrides.noncanonical_club",
                422,
                details={"club_names": noncanonical_names},
            )

    saved = save_configuration(
        _state_directory(),
        replace(
            configuration,
            known_local_players=overrides,
            known_local_player_names=player_names,
        ),
        expected_revision=revision,
    )

    session.pop(PLAYER_OVERRIDE_DRAFT_SESSION_KEY, None)
    return jsonify(
        {
            "data": {
                "revision": saved.revision,
                "known_local_players": dict(saved.known_local_players),
                "known_local_player_names": dict(
                    saved.known_local_player_names
                ),
                "changed": True,
            }
        }
    )


@pages.post("/api/v1/configuration/contributor")
def save_contributor():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    contributor = _submitted_contributor(payload)
    if revision is None or contributor is None:
        return json_error(
            "invalid_input",
            "errors.contributor.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)
    if contributor == dict(configuration.contributor):
        return jsonify(
            {
                "data": {
                    "revision": configuration.revision,
                    "contributor": contributor,
                    "changed": False,
                }
            }
        )

    saved = save_configuration(
        _state_directory(),
        replace(configuration, contributor=contributor),
        expected_revision=revision,
    )

    return jsonify(
        {
            "data": {
                "revision": saved.revision,
                "contributor": dict(saved.contributor),
                "changed": True,
            }
        }
    )


@pages.post("/api/v1/configuration/finals")
def save_finals_separators():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    separators = _submitted_finals_separators(payload)
    if revision is None or separators is None:
        return json_error(
            "invalid_input",
            "errors.finals.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)
    if separators == configuration.finals_separators:
        return jsonify(
            {
                "data": {
                    "revision": configuration.revision,
                    "finals_separators": list(separators),
                    "changed": False,
                }
            }
        )

    saved = save_configuration(
        _state_directory(),
        replace(configuration, finals_separators=separators),
        expected_revision=revision,
    )

    return jsonify(
        {
            "data": {
                "revision": saved.revision,
                "finals_separators": list(saved.finals_separators),
                "changed": True,
            }
        }
    )


@pages.post("/api/v1/configuration/club-display-names")
def save_club_display_name():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    change = _submitted_club_display_name_change(payload)
    if revision is None or change is None:
        return json_error(
            "invalid_input",
            "errors.club_display_names.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)

    action, canonical_name, display_name = change
    aliases = dict(configuration.club_display_names)
    if action == "remove":
        if canonical_name not in aliases:
            return jsonify(
                {
                    "data": {
                        "revision": configuration.revision,
                        "club_display_names": aliases,
                        "changed": False,
                    }
                }
            )
        del aliases[canonical_name]
    else:
        if aliases.get(canonical_name) == display_name:
            return jsonify(
                {
                    "data": {
                        "revision": configuration.revision,
                        "club_display_names": aliases,
                        "changed": False,
                    }
                }
            )
        if canonical_name not in aliases:
            canonical_club_names = {
                club.name for club in _district_clubs()
            }
            if canonical_name not in canonical_club_names:
                return json_error(
                    "noncanonical_club",
                    "errors.club_display_names.noncanonical_club",
                    422,
                )
        aliases[canonical_name] = display_name

    saved = save_configuration(
        _state_directory(),
        replace(configuration, club_display_names=aliases),
        expected_revision=revision,
    )

    return jsonify(
        {
            "data": {
                "revision": saved.revision,
                "club_display_names": dict(saved.club_display_names),
                "changed": True,
            }
        }
    )


@pages.post("/api/v1/configuration/tournaments")
def save_default_tournaments():
    payload = request.get_json(silent=True)
    revision = _submitted_revision(payload)
    tournament_ids = _submitted_tournament_ids(payload)
    if revision is None or tournament_ids is None:
        return json_error(
            "invalid_input",
            "errors.configuration.invalid_input",
            400,
        )

    configuration = _current_configuration(revision)

    draft = session.get(TOURNAMENT_DRAFT_SESSION_KEY)
    rollover_year = (
        draft.get("rollover_year")
        if isinstance(draft, dict) and draft.get("revision") == revision
        else None
    )
    if (
        rollover_year is None
        and tournament_ids == configuration.default_tournament_ids
    ):
        session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
        return jsonify(
            {
                "data": {
                    "revision": configuration.revision,
                    "tournament_ids": list(tournament_ids),
                    "changed": False,
                }
            }
        )

    try:
        tournaments = _resolve_tournaments(tournament_ids)
    except TournamentKlassNamingError as error:
        return _klass_naming_error(error)
    except TournamentResolutionError:
        return json_error(
            "tournament_unresolvable",
            "errors.tournament_lookup.unresolvable",
            422,
        )

    current_year = _current_stockholm_date().year
    assessment = _tournament_year_assessment(tournaments, current_year)
    if assessment.state is TournamentYearState.MIXED:
        return json_error(
            "mixed_tournament_years",
            "errors.configuration.tournament_years_mixed",
            422,
            details={
                "configured_years": list(assessment.configured_years),
            },
        )
    if assessment.state is TournamentYearState.FUTURE:
        return json_error(
            "future_tournament_year",
            "errors.configuration.tournament_year_future",
            422,
            details={
                "current_year": current_year,
                "configured_years": list(assessment.configured_years),
            },
        )

    if rollover_year is not None:
        if rollover_year != current_year or any(
            tournament.start_date.year != rollover_year
            for tournament in tournaments
        ):
            return json_error(
                "invalid_rollover_tournament_year",
                "errors.configuration.rollover_tournament_year",
                422,
                details={"rollover_year": rollover_year},
            )

    ordered_ids = tuple(
        int(tournament.tournament_id) for tournament in tournaments
    )
    if ordered_ids == configuration.default_tournament_ids:
        return jsonify(
            {
                "data": {
                    "revision": configuration.revision,
                    "tournament_ids": list(ordered_ids),
                    "changed": False,
                }
            }
        )

    # A new season starts without the previous season's finals separators.
    finals_separators = (
        () if rollover_year is not None else configuration.finals_separators
    )
    saved = save_configuration(
        _state_directory(),
        replace(
            configuration,
            default_tournament_ids=ordered_ids,
            finals_separators=finals_separators,
        ),
        expected_revision=revision,
    )

    session.pop(TOURNAMENT_DRAFT_SESSION_KEY, None)
    data = {
        "revision": saved.revision,
        "tournament_ids": list(saved.default_tournament_ids),
        "changed": True,
    }
    if rollover_year is not None:
        data["rollover_completed"] = True
    return jsonify({"data": data})
