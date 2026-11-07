"""Persistence and validation for the tool's single active configuration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import tomllib

from .atomic_write import atomic_replace_text
from .numeric_validation import (
    is_non_negative_finite_number,
    is_non_negative_integer,
    is_positive_finite_number,
    is_positive_integer,
)


ACTIVE_CONFIGURATION_FILENAME = "active-configuration.toml"
DEFAULT_CONTRIBUTOR_NAME = "Stockholms Schackförbunds Ungdomsutskott"
DEFAULT_CONTRIBUTOR_EMAIL = "uu@stockholmsschack.se"


class ConfigurationValidationError(ValueError):
    """Raised with every problem found in an active configuration."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class StaleConfigurationError(RuntimeError):
    """Raised when a save is based on an obsolete configuration revision."""

    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        self.current_revision = current_revision
        super().__init__(message)


@dataclass(frozen=True)
class LayoutConfiguration:
    landscape_starts_at: int = 15
    base_side_margin_cm: float = 0.8
    margin_reduction_starts_after: int = 7
    margin_reduction_per_tournament_cm: float = 0.05
    minimum_side_margin_cm: float = 0.5


@dataclass(frozen=True)
class ActiveConfiguration:
    """Defaults and presentation settings persisted for the tool."""

    default_tournament_ids: tuple[int, ...]
    contributor: Mapping[str, str]
    known_local_players: Mapping[str, str] = field(default_factory=dict)
    known_local_player_names: Mapping[str, str] = field(default_factory=dict)
    layout: LayoutConfiguration = field(default_factory=LayoutConfiguration)
    club_display_names: Mapping[str, str] = field(default_factory=dict)
    finals_separators: tuple[int, ...] = ()
    revision: int = 0


def configuration_path(state_directory: Path) -> Path:
    """Return the sole active-configuration path for a state directory."""
    return Path(state_directory) / ACTIVE_CONFIGURATION_FILENAME


def load_configuration(state_directory: Path) -> ActiveConfiguration:
    """Load and validate the active configuration from a state directory."""
    path = configuration_path(state_directory)
    try:
        with path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationValidationError(
            (f"could not read active configuration: {error}",)
        ) from error

    configuration, structural_problems = _configuration_from_document(data)
    problems = [
        *structural_problems,
        *_configuration_problems(configuration),
    ]
    if problems:
        raise ConfigurationValidationError(problems)
    return configuration


def save_configuration(
    state_directory: Path,
    configuration: ActiveConfiguration,
    *,
    expected_revision: int | None = None,
) -> ActiveConfiguration:
    """Validate and atomically replace the active configuration.

    The caller's revision is used as the optimistic-lock revision unless an
    explicit expected revision is supplied.
    """
    validate_active_configuration(configuration)
    state_directory = Path(state_directory)
    path = configuration_path(state_directory)
    expected = (
        configuration.revision
        if expected_revision is None
        else expected_revision
    )
    current_revision = _current_revision(path)
    if expected != current_revision:
        raise StaleConfigurationError(
            f"configuration revision {expected} is stale; "
            f"current revision is {current_revision}",
            current_revision=current_revision,
        )

    saved = replace(configuration, revision=current_revision + 1)
    document = _configuration_document(saved)
    atomic_replace_text(path, document, replace=os.replace)
    return saved


def validate_active_configuration(
    configuration: ActiveConfiguration,
) -> None:
    """Report all active-configuration problems in one exception."""
    problems = _configuration_problems(configuration)
    if problems:
        raise ConfigurationValidationError(problems)


def _configuration_problems(
    configuration: ActiveConfiguration,
) -> list[str]:
    problems: list[str] = []
    tournament_ids = configuration.default_tournament_ids
    valid_tournament_ids = [
        tournament_id
        for tournament_id in tournament_ids
        if is_positive_integer(tournament_id)
    ]
    if not tournament_ids:
        problems.append("at least one default tournament id is required")
    if len(valid_tournament_ids) != len(tournament_ids):
        problems.append("default tournament ids must be positive integers")
    if len(set(valid_tournament_ids)) != len(valid_tournament_ids):
        problems.append("default tournament ids must be unique")

    if not isinstance(configuration.contributor, Mapping):
        problems.append("contributor must be a table")
    else:
        for field_name in ("name", "email"):
            value = configuration.contributor.get(field_name)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"contributor {field_name} is required")

    if not isinstance(configuration.known_local_players, Mapping):
        problems.append("known_local_players must be a table")
    else:
        for player_id, club_name in configuration.known_local_players.items():
            if not str(player_id).isdigit() or int(player_id) <= 0:
                problems.append(
                    f"known-local player id {player_id!r} "
                    "must be a positive integer"
                )
            if not isinstance(club_name, str) or not club_name.strip():
                problems.append(
                    f"known-local player {player_id!r} must have a club name"
                )

    if not isinstance(configuration.known_local_player_names, Mapping):
        problems.append("known_local_player_names must be a table")
    else:
        known_player_ids = (
            {
                str(player_id)
                for player_id in configuration.known_local_players
            }
            if isinstance(configuration.known_local_players, Mapping)
            else set()
        )
        for player_id, player_name in (
            configuration.known_local_player_names.items()
        ):
            if str(player_id) not in known_player_ids:
                problems.append(
                    f"known-local player name {player_id!r} has no club override"
                )
            if not isinstance(player_name, str) or not player_name.strip():
                problems.append(
                    f"known-local player {player_id!r} must have a name"
                )

    layout = configuration.layout
    if not isinstance(layout, LayoutConfiguration):
        problems.append("layout must contain the supported presentation settings")
    else:
        if not is_non_negative_integer(layout.landscape_starts_at):
            problems.append(
                "layout landscape_starts_at must be a non-negative integer"
            )
        if not is_positive_finite_number(layout.base_side_margin_cm):
            problems.append("layout base_side_margin_cm must be a positive number")
        if not is_non_negative_integer(layout.margin_reduction_starts_after):
            problems.append(
                "layout margin_reduction_starts_after "
                "must be a non-negative integer"
            )
        if not is_non_negative_finite_number(
            layout.margin_reduction_per_tournament_cm
        ):
            problems.append(
                "layout margin_reduction_per_tournament_cm "
                "must be a non-negative number"
            )
        if not is_positive_finite_number(layout.minimum_side_margin_cm):
            problems.append(
                "layout minimum_side_margin_cm must be a positive number"
            )
        if (
            is_positive_finite_number(layout.base_side_margin_cm)
            and is_positive_finite_number(layout.minimum_side_margin_cm)
            and layout.minimum_side_margin_cm > layout.base_side_margin_cm
        ):
            problems.append(
                "layout minimum_side_margin_cm cannot exceed "
                "base_side_margin_cm"
            )

    if not isinstance(configuration.club_display_names, Mapping):
        problems.append("club_display_names must be a table")
    else:
        for canonical_name, display_name in (
            configuration.club_display_names.items()
        ):
            if not isinstance(canonical_name, str) or not canonical_name.strip():
                problems.append("club display aliases require a canonical club name")
            if not isinstance(display_name, str) or not display_name.strip():
                problems.append(
                    f"club display alias {canonical_name!r} "
                    "requires a display name"
                )

    finals_separators = configuration.finals_separators
    if not isinstance(finals_separators, tuple):
        problems.append("finals_separators must be an array")
    else:
        if not all(
            is_positive_integer(position) for position in finals_separators
        ):
            problems.append("finals separators must be positive integers")
        if any(
            position in finals_separators[:index]
            for index, position in enumerate(finals_separators)
        ):
            problems.append("finals separators must be unique")

    if not is_non_negative_integer(configuration.revision):
        problems.append("revision must be a non-negative integer")
    return problems


def _configuration_from_document(
    data: object,
) -> tuple[ActiveConfiguration, list[str]]:
    problems: list[str] = []
    if not isinstance(data, dict):
        data = {}
        problems.append("active configuration must be a TOML document")

    allowed_keys = {
        "revision",
        "tournament_ids",
        "known_local_players",
        "known_local_player_names",
        "contributor",
        "layout",
        "club_display_names",
        "finals_separators",
    }
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        problems.append(
            "unknown active configuration fields: " + ", ".join(unknown_keys)
        )
    revision = data.get("revision")
    if revision is None:
        problems.append("stored configuration revision is required")
        revision = 0
    elif not is_positive_integer(revision):
        problems.append(
            "stored configuration revision must be a positive integer"
        )

    raw_layout = data.get("layout", {})
    if not isinstance(raw_layout, dict):
        problems.append("layout must be a table")
        raw_layout = {}
    allowed_layout_keys = set(LayoutConfiguration.__dataclass_fields__)
    # Accept the retired UI preference in previously saved configurations.
    unknown_layout_keys = sorted(
        set(raw_layout) - allowed_layout_keys - {"default_orientation"}
    )
    if unknown_layout_keys:
        problems.append(
            "unknown layout fields: " + ", ".join(unknown_layout_keys)
        )
    defaults = LayoutConfiguration()
    layout = LayoutConfiguration(
        **{
            name: raw_layout.get(name, getattr(defaults, name))
            for name in allowed_layout_keys
        }
    )

    raw_tournament_ids = data.get("tournament_ids", ())
    if not isinstance(raw_tournament_ids, list):
        problems.append("tournament_ids must be an array")
        raw_tournament_ids = ()
    contributor = data.get("contributor", {})
    if isinstance(contributor, dict):
        unknown_contributor_keys = sorted(
            set(contributor) - {"name", "email"}
        )
        if unknown_contributor_keys:
            problems.append(
                "unknown contributor fields: "
                + ", ".join(unknown_contributor_keys)
            )
    known_local_players = data.get("known_local_players", {})
    known_local_player_names = data.get("known_local_player_names", {})
    club_display_names = data.get("club_display_names", {})
    raw_finals_separators = data.get("finals_separators", [])
    if not isinstance(raw_finals_separators, list):
        problems.append("finals_separators must be an array")
        raw_finals_separators = []
    return (
        ActiveConfiguration(
            default_tournament_ids=tuple(raw_tournament_ids),
            contributor=contributor,
            known_local_players=known_local_players,
            known_local_player_names=known_local_player_names,
            layout=layout,
            club_display_names=club_display_names,
            finals_separators=tuple(raw_finals_separators),
            revision=revision,
        ),
        problems,
    )


def _configuration_document(configuration: ActiveConfiguration) -> str:
    layout = configuration.layout
    lines = [
        f"revision = {configuration.revision}",
        "tournament_ids = ["
        + ", ".join(str(value) for value in configuration.default_tournament_ids)
        + "]",
        "finals_separators = ["
        + ", ".join(str(value) for value in configuration.finals_separators)
        + "]",
        "",
        "[contributor]",
        f"name = {_toml_string(configuration.contributor['name'])}",
        f"email = {_toml_string(configuration.contributor['email'])}",
        "",
        "[known_local_players]",
    ]
    lines.extend(
        f"{_toml_string(str(player_id))} = {_toml_string(club_name)}"
        for player_id, club_name in sorted(
            configuration.known_local_players.items(),
            key=lambda item: str(item[0]),
        )
    )
    lines.extend(["", "[known_local_player_names]"])
    lines.extend(
        f"{_toml_string(str(player_id))} = {_toml_string(player_name)}"
        for player_id, player_name in sorted(
            configuration.known_local_player_names.items(),
            key=lambda item: str(item[0]),
        )
    )
    lines.extend(
        [
            "",
            "[layout]",
            f"landscape_starts_at = {layout.landscape_starts_at}",
            f"base_side_margin_cm = {layout.base_side_margin_cm}",
            "margin_reduction_starts_after = "
            f"{layout.margin_reduction_starts_after}",
            "margin_reduction_per_tournament_cm = "
            f"{layout.margin_reduction_per_tournament_cm}",
            f"minimum_side_margin_cm = {layout.minimum_side_margin_cm}",
            "",
            "[club_display_names]",
        ]
    )
    lines.extend(
        f"{_toml_string(canonical)} = {_toml_string(display)}"
        for canonical, display in sorted(
            configuration.club_display_names.items()
        )
    )
    return "\n".join(lines) + "\n"


def _current_revision(path: Path) -> int:
    if not path.exists():
        return 0
    return load_configuration(path.parent).revision


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
