from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import polars as pl
import xlsxwriter

from .active_configuration import LayoutConfiguration
from .points import assign_standings_point_by_player_rank
from .generation_rules import youngest_group_start_year


PUBLIC_STANDINGS_FIELDS = frozenset(
    {
        "placement",
        "member_id",
        "name",
        "birth_year",
        "club",
        "tournaments",
        "total_points",
    }
)
DIAGNOSTIC_FILENAMES = (
    "walkovers.txt",
    "no_matches_played.txt",
    "dropouts.txt",
    "unmatched_player_ids.txt",
    "round_count_mismatches.txt",
)


@dataclass(frozen=True)
class TournamentInput:
    identifier: str
    source_name: str
    records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class GenerationDiagnostics:
    walkovers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    no_matches_played: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    dropouts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unmatched_player_ids: tuple[int, ...] = ()
    round_count_mismatches: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("walkovers", "no_matches_played", "dropouts"):
            values = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(
                    {key: tuple(items) for key, items in values.items()}
                ),
            )
        object.__setattr__(
            self, "unmatched_player_ids", tuple(self.unmatched_player_ids)
        )
        object.__setattr__(
            self,
            "round_count_mismatches",
            tuple(self.round_count_mismatches),
        )


@dataclass(frozen=True)
class CollatedStandings:
    effective_year: int
    tournament_ids: tuple[str, ...]
    tournament_names: tuple[str, ...]
    validation_rows: pl.DataFrame
    published_rows: pl.DataFrame
    non_local_player_ids: frozenset[int]
    diagnostics: GenerationDiagnostics
    contributor_name: str
    contributor_email: str


@dataclass(frozen=True)
class RenderingProjection:
    """Published values needed to render without recalculating standings."""

    effective_year: int
    tournament_ids: tuple[str, ...]
    tournament_names: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    contributor_name: str
    contributor_email: str


@dataclass(frozen=True)
class GeneratedArtifacts:
    validation_workbook: bytes
    standings_workbook: bytes
    typst_source: str
    standings_json: str
    diagnostic_reports: Mapping[str, str]


@dataclass(frozen=True)
class GenerationResult:
    standings: CollatedStandings
    rendering_projection: RenderingProjection
    artifacts: GeneratedArtifacts


def load_archived_inputs(
    root: Path,
) -> tuple[tuple[TournamentInput, ...], dict[str, Any], dict[str, Any]]:
    """Load archived player lists, tournament statistics and intermediate results."""
    player_list = json.loads((root / "player_list.json").read_text())
    tournament_stats = json.loads((root / "tournament_stats.json").read_text())
    tournament_inputs = tuple(
        TournamentInput(
            identifier=path.stem.split("-", 1)[1],
            source_name=path.name,
            records=tuple(json.loads(path.read_text())),
        )
        for path in sorted((root / "flick-intermediate").glob("*.json"))
    )
    return tournament_inputs, player_list, tournament_stats


def generate_standings(
    *,
    effective_year: int,
    tournaments: Sequence[TournamentInput],
    player_list: Mapping[str, Mapping[str, Any]],
    tournament_stats: Mapping[str, Mapping[str, Any]],
    contributor: Mapping[str, str],
    diagnostics: GenerationDiagnostics | None = None,
    layout_configuration: LayoutConfiguration = LayoutConfiguration(),
    club_display_names: Mapping[str, str] = MappingProxyType({}),
    finals_separators: Sequence[int] = (),
    layout: str = "auto",
) -> GenerationResult:
    """Collate resolved inputs and build artifacts in memory."""
    standings = collate_standings(
        effective_year=effective_year,
        tournaments=tournaments,
        player_list=player_list,
        tournament_stats=tournament_stats,
        contributor=contributor,
        diagnostics=diagnostics,
    )
    return build_generation_result(
        standings,
        layout_configuration=layout_configuration,
        club_display_names=club_display_names,
        finals_separators=finals_separators,
        layout=layout,
    )


def build_generation_result(
    standings: CollatedStandings,
    *,
    layout_configuration: LayoutConfiguration = LayoutConfiguration(),
    club_display_names: Mapping[str, str] = MappingProxyType({}),
    finals_separators: Sequence[int] = (),
    layout: str = "auto",
) -> GenerationResult:
    """Build the rendering projection and artifacts from collated standings."""
    projection = create_rendering_projection(standings)
    return GenerationResult(
        standings=standings,
        rendering_projection=projection,
        artifacts=produce_artifacts(
            standings,
            rendering_projection=projection,
            layout_configuration=layout_configuration,
            club_display_names=club_display_names,
            finals_separators=finals_separators,
            layout=layout,
        ),
    )


def collate_standings(
    *,
    effective_year: int,
    tournaments: Sequence[TournamentInput],
    player_list: Mapping[str, Mapping[str, Any]],
    tournament_stats: Mapping[str, Mapping[str, Any]],
    contributor: Mapping[str, str],
    diagnostics: GenerationDiagnostics | None = None,
) -> CollatedStandings:
    """Run sequence-point allocation, collation, and eligibility resolution."""
    if not tournaments:
        raise ValueError("at least one tournament input is required")

    tournament_ids = tuple(tournament.identifier for tournament in tournaments)
    missing_stats = [
        tournament_id
        for tournament_id in tournament_ids
        if tournament_id not in tournament_stats
    ]
    if missing_stats:
        raise ValueError(
            "missing tournament statistics for: " + ", ".join(missing_stats)
        )

    tournament_standings = [
        _process_tournament(
            tournament,
            index,
            effective_year,
            player_list,
            bool(tournament_stats[tournament.identifier].get("jdm")),
        )
        for index, tournament in enumerate(tournaments, start=1)
    ]
    merged_by_klass = _merge_tournament_standings(tournament_standings)
    if not merged_by_klass:
        raise ValueError("no female player standings were produced")

    validation_rows = pl.concat(list(merged_by_klass.values()))
    validation_rows = validation_rows.drop(
        [
            "playerInfo.firstName",
            "playerInfo.lastName",
            "playerInfo.sex",
            "year_group",
        ]
    )

    known_non_locals = {
        int(player_id)
        for player_id, player in player_list.items()
        if not player.get("local", False)
    }
    contender_ids = set(validation_rows["contenderId"].to_list())
    known_player_ids = {int(player_id) for player_id in player_list}
    unmatched_player_ids = contender_ids - known_player_ids
    non_local_player_ids = frozenset(known_non_locals | unmatched_player_ids)

    klass_columns = [
        column for column in validation_rows.columns if column.startswith("klass_")
    ]
    validation_rows = validation_rows.with_columns(
        pl.sum_horizontal(
            [
                pl.col(column).is_not_null().cast(pl.Int32)
                for column in klass_columns
            ]
        ).alias("played")
    )

    points_columns = sorted(
        [column for column in validation_rows.columns if column.startswith("p_")],
        key=lambda column: int(column.split("_")[1]),
    )
    sort_columns: list[Any] = (
        ["Σ", "klass"]
        + [
            pl.col(column).is_not_null()
            for column in reversed(points_columns)
        ]
        + list(reversed(points_columns))
        + ["playerInfo.birthdate", "played"]
    )
    sort_descending = (
        [True, False]
        + [True] * len(points_columns)
        + [True] * len(points_columns)
        + [False, False]
    )
    validation_rows = validation_rows.sort(
        sort_columns,
        descending=sort_descending,
        maintain_order=True,
    )
    validation_rows = validation_rows.select(
        [column for column in validation_rows.columns if column != "Σ"] + ["Σ"]
    ).rename({"playerInfo.birthdate": "Född"})
    validation_rows = _prepare_validation_rows(validation_rows)

    published_rows = validation_rows.filter(
        ~pl.col("contenderId").is_in(non_local_player_ids)
    ).with_columns(pl.int_range(1, pl.len() + 1).alias("Placering"))
    internal_columns = [
        f"{prefix}_{index}"
        for index in range(1, len(tournaments) + 1)
        for prefix in ("p", "kvp", "klass")
    ] + ["contenderId", "klass"]
    published_rows = _prepare_published_rows(
        published_rows.drop(internal_columns)
    )

    derived_diagnostics = _derive_diagnostics(
        tournaments,
        player_list,
        tournament_stats,
        diagnostics or GenerationDiagnostics(),
        unmatched_player_ids,
    )
    tournament_names = tuple(
        str(tournament_stats[tournament_id]["name"])
        for tournament_id in tournament_ids
    )
    return CollatedStandings(
        effective_year=effective_year,
        tournament_ids=tournament_ids,
        tournament_names=tournament_names,
        validation_rows=validation_rows,
        published_rows=published_rows,
        non_local_player_ids=non_local_player_ids,
        diagnostics=derived_diagnostics,
        contributor_name=contributor.get("name", "NONAME"),
        contributor_email=contributor.get("email", "noname@example.com"),
    )


def produce_artifacts(
    standings: CollatedStandings,
    *,
    rendering_projection: RenderingProjection | None = None,
    layout_configuration: LayoutConfiguration = LayoutConfiguration(),
    club_display_names: Mapping[str, str] = MappingProxyType({}),
    finals_separators: Sequence[int] = (),
    layout: str = "auto",
) -> GeneratedArtifacts:
    """Build artifacts from collated standings."""
    reports = _diagnostic_reports(standings.diagnostics)
    projection = rendering_projection or create_rendering_projection(standings)
    return GeneratedArtifacts(
        validation_workbook=_workbook_bytes(
            standings.validation_rows,
            highlight_player_ids=standings.non_local_player_ids,
        ),
        standings_workbook=_workbook_bytes(standings.published_rows),
        typst_source=render_projection_to_typst(
            projection,
            layout_configuration=layout_configuration,
            club_display_names=club_display_names,
            finals_separators=finals_separators,
            layout=layout,
        ),
        standings_json=serialize_standings_json(
            _public_standings_rows(standings),
            tournament_ids=[int(value) for value in standings.tournament_ids],
        ),
        diagnostic_reports=MappingProxyType(reports),
    )


def serialize_standings_json(
    rows: Iterable[Mapping[str, Any]], *, tournament_ids: Sequence[int],
) -> str:
    """Serialize ordered tournament ids and standings with player member ids."""
    validated_rows = []
    for index, row in enumerate(rows):
        fields = set(row)
        unknown = fields - PUBLIC_STANDINGS_FIELDS
        missing = PUBLIC_STANDINGS_FIELDS - fields
        if unknown:
            raise ValueError(
                f"standings row {index} contains non-allowlisted fields: "
                + ", ".join(sorted(unknown))
            )
        if missing:
            raise ValueError(
                f"standings row {index} is missing public fields: "
                + ", ".join(sorted(missing))
            )
        if (
            isinstance(row["placement"], bool)
            or not isinstance(row["placement"], int)
        ):
            raise ValueError(
                f"standings row {index} placement must be an integer"
            )
        if (
            isinstance(row["member_id"], bool)
            or not isinstance(row["member_id"], int)
            or row["member_id"] <= 0
        ):
            raise ValueError(f"standings row {index} member_id must be a positive integer")
        if (
            isinstance(row["birth_year"], bool)
            or not isinstance(row["birth_year"], int)
            or not 1000 <= row["birth_year"] <= 9999
        ):
            raise ValueError(
                f"standings row {index} birth_year must be a four-digit year"
            )
        for field_name in ("name", "club"):
            if not isinstance(row[field_name], str):
                raise ValueError(
                    f"standings row {index} {field_name} must be text"
                )
        if (
            isinstance(row["total_points"], bool)
            or not isinstance(row["total_points"], (int, float))
        ):
            raise ValueError(
                f"standings row {index} total_points must be numeric"
            )
        tournaments = row["tournaments"]
        if not isinstance(tournaments, Mapping):
            raise ValueError(
                f"standings row {index} tournaments must be an object"
            )
        for tournament_id, sequence_points in tournaments.items():
            if not isinstance(tournament_id, str) or not tournament_id:
                raise ValueError(
                    f"standings row {index} tournament identifiers must be text"
                )
            if (
                isinstance(sequence_points, bool)
                or not isinstance(sequence_points, (int, float))
            ):
                raise ValueError(
                    f"standings row {index} tournament {tournament_id} "
                    "must contain only sequence points"
                )
        validated_rows.append(dict(row))
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in tournament_ids):
        raise ValueError("tournament_ids must contain positive integers")
    if len(set(tournament_ids)) != len(tournament_ids):
        raise ValueError("tournament_ids must be unique")
    return json.dumps(
        {
            "last_updated": datetime.now(UTC).isoformat(timespec="seconds"),
            "tournament_ids": list(tournament_ids),
            "standings": validated_rows,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def create_rendering_projection(
    standings: CollatedStandings,
) -> RenderingProjection:
    """Extract published values needed to render standings."""
    return RenderingProjection(
        effective_year=standings.effective_year,
        tournament_ids=standings.tournament_ids,
        tournament_names=standings.tournament_names,
        rows=tuple(
            MappingProxyType(row)
            for row in standings.published_rows.to_dicts()
        ),
        contributor_name=standings.contributor_name,
        contributor_email=standings.contributor_email,
    )


def standings_to_typst(standings: CollatedStandings) -> str:
    """Render standings with the compatibility presentation defaults."""
    return render_projection_to_typst(create_rendering_projection(standings))


def render_projection_to_typst(
    projection: RenderingProjection,
    *,
    layout_configuration: LayoutConfiguration = LayoutConfiguration(),
    club_display_names: Mapping[str, str] = MappingProxyType({}),
    finals_separators: Sequence[int] = (),
    layout: str = "auto",
) -> str:
    """Render a persisted projection using explicit presentation policy."""
    rows = [
        {
            **row,
            "Klubb": club_display_names.get(row["Klubb"], row["Klubb"]),
        }
        for row in projection.rows
    ]
    frame = pl.DataFrame(rows).rename({"Placering": r"\#"})
    effective_layout = resolve_layout(
        layout,
        len(projection.tournament_ids),
        layout_configuration,
    )
    side_margin_cm = resolve_side_margin(
        len(projection.tournament_ids),
        layout_configuration,
    )
    pages = "\n" + _polars_to_typst(
        frame,
        len(projection.tournament_ids),
        layout=effective_layout,
        side_margin_cm=side_margin_cm,
        finals_separators=finals_separators,
    )
    pages += "\n" + _tournament_info_to_typst(projection.tournament_names)
    pages += "\n" + '#include "rules.typ"'
    pages += f"""\n
        #show link: set text(blue)
        Synpunkter / Comments: #link("mailto:{_typst_string(projection.contributor_email)}")[{_typst_content(projection.contributor_name)}]
        """
    return pages.rstrip() + "\n"


def resolve_layout(
    requested_layout: str,
    tournament_count: int,
    configuration: LayoutConfiguration,
) -> str:
    """Resolve auto presentation to the effective page orientation."""
    if requested_layout not in {"auto", "portrait", "landscape"}:
        raise ValueError("layout must be auto, portrait, or landscape")
    if requested_layout != "auto":
        return requested_layout
    threshold = configuration.landscape_starts_at
    return (
        "landscape"
        if threshold and tournament_count >= threshold
        else "portrait"
    )


def resolve_side_margin(
    tournament_count: int,
    configuration: LayoutConfiguration,
) -> float:
    """Apply the configured bounded side-margin formula."""
    reduction_count = max(
        0,
        tournament_count - configuration.margin_reduction_starts_after,
    )
    return max(
        configuration.minimum_side_margin_cm,
        configuration.base_side_margin_cm
        - configuration.margin_reduction_per_tournament_cm * reduction_count,
    )


def _process_tournament(
    tournament: TournamentInput,
    index: int,
    effective_year: int,
    player_list: Mapping[str, Mapping[str, Any]],
    is_jdm: bool,
) -> dict[str, Any]:
    flattened_data = []
    for record in tournament.records:
        player_info = record["playerInfo"]
        flattened_data.append(
            {
                "points": record["points"],
                "secPoints": record["secPoints"],
                "place": record["place"],
                "contenderId": record["contenderId"],
                "teamNumber": record["teamNumber"],
                "wonGames": record["wonGames"],
                "drawGames": record["drawGames"],
                "lostGames": record["lostGames"],
                "groupId": record["groupId"],
                "klass": record["klass"],
                "scaled_pts": record["scaled_pts"],
                "playerInfo.firstName": player_info["firstName"],
                "playerInfo.lastName": player_info["lastName"],
                "playerInfo.birthdate": player_info["birthdate"],
                "playerInfo.sex": player_info["sex"],
            }
        )
    if not flattened_data:
        return {"tournament_idx": index, "results_by_group": {}}

    tournament_frame = pl.DataFrame(flattened_data)
    player_lookup = pl.DataFrame(
        [
            {
                "contenderId": int(player_id),
                "klubb": player.get("klubb") or "Unknown",
            }
            for player_id, player in player_list.items()
        ],
        schema={"contenderId": pl.Int64, "klubb": pl.String},
    )
    youngest_year = youngest_group_start_year(effective_year)
    tournament_frame = (
        tournament_frame.filter(pl.col("playerInfo.sex") != 0)
        .with_columns(
            [
                pl.col("playerInfo.birthdate").cast(pl.Int64),
                (
                    pl.col("playerInfo.firstName")
                    + " "
                    + pl.col("playerInfo.lastName")
                ).alias("Namn"),
            ]
        )
        .join(player_lookup, on="contenderId", how="left")
        .with_columns(
            [
                pl.col("klubb").fill_null("Unknown").alias("Klubb"),
                pl.when(pl.col("playerInfo.birthdate") >= youngest_year)
                .then(pl.lit(f"{youngest_year} -"))
                .otherwise(pl.col("playerInfo.birthdate").cast(pl.String))
                .alias("year_group"),
            ]
        )
        .drop("klubb")
    )

    results_by_group = {}
    for klass in tournament_frame["klass"].unique().to_list():
        group = tournament_frame.filter(pl.col("klass") == klass)
        results_by_group[klass] = assign_standings_point_by_player_rank(
            klass,
            group,
            "place",
            "scaled_pts",
            "points",
            "secPoints",
            f"STD {index}",
            not is_jdm,
        )
    return {"tournament_idx": index, "results_by_group": results_by_group}


def _merge_tournament_standings(
    tournament_standings: Sequence[Mapping[str, Any]],
) -> dict[str, pl.DataFrame]:
    all_player_data: dict[int, dict[str, Any]] = {}
    for tournament in tournament_standings:
        tournament_index = tournament["tournament_idx"]
        for group in tournament["results_by_group"].values():
            for row in group.to_dicts():
                player_id = row["contenderId"]
                if player_id not in all_player_data:
                    all_player_data[player_id] = {
                        "contenderId": player_id,
                        "playerInfo.firstName": row["playerInfo.firstName"],
                        "playerInfo.lastName": row["playerInfo.lastName"],
                        "playerInfo.birthdate": row["playerInfo.birthdate"],
                        "playerInfo.sex": row["playerInfo.sex"],
                        "Namn": row["Namn"],
                        "Klubb": row["Klubb"],
                        "year_group": row["year_group"],
                    }
                player = all_player_data[player_id]
                player[f"p_{tournament_index}"] = row["points"]
                player[f"kvp_{tournament_index}"] = row["secPoints"]
                player[f"klass_{tournament_index}"] = row["klass"]
                standings_column = f"STD {tournament_index}"
                if standings_column in row:
                    player[standings_column] = row[standings_column]

    if not all_player_data:
        return {}
    players = pl.DataFrame(list(all_player_data.values()))
    klass_columns = sorted(
        [column for column in players.columns if column.startswith("klass_")],
        key=lambda column: int(column.split("_")[1]),
        reverse=True,
    )
    players = players.with_columns(
        pl.coalesce([pl.col(column) for column in klass_columns]).alias("klass")
    )

    merged = {}
    for klass in players.select("klass").unique().to_series():
        if klass is None:
            continue
        frame = players.filter(pl.col("klass") == klass)
        standings_columns = [
            column for column in frame.columns if column.startswith("STD")
        ]
        frame = frame.with_columns(
            pl.sum_horizontal(
                [pl.col(column).fill_null(0) for column in standings_columns]
            ).alias("Σ")
        )
        frame = frame.sort("Σ", descending=True, maintain_order=True)
        frame = frame.with_columns(
            pl.int_range(1, pl.len() + 1).alias("Placering")
        )
        frame = frame.select(
            ["Placering"]
            + [column for column in frame.columns if column != "Placering"]
        )
        standings_columns.sort(key=lambda column: int(column.split(" ")[1]))
        non_standings_columns = [
            column
            for column in frame.columns
            if not column.startswith("STD") and column != "Σ"
        ]
        merged[klass] = frame.select(
            non_standings_columns + standings_columns + ["Σ"]
        )
    return merged


def _prepare_validation_rows(frame: pl.DataFrame) -> pl.DataFrame:
    quality_columns = [
        column for column in frame.columns if column.startswith("kvp_")
    ]
    if quality_columns:
        frame = frame.with_columns(
            [pl.col(column).round(1).alias(column) for column in quality_columns]
        )
    return frame.with_columns(
        pl.int_range(1, pl.len() + 1).alias("Placering")
    )


def _prepare_published_rows(frame: pl.DataFrame) -> pl.DataFrame:
    rename = {
        column: column.split(" ")[1]
        for column in frame.columns
        if column.startswith("STD")
    }
    if rename:
        frame = frame.rename(rename)
    columns = frame.columns
    if len(columns) >= 3:
        frame = frame.select(
            [columns[0], columns[2], columns[1]] + columns[3:]
        )
    return frame


def _workbook_bytes(
    frame: pl.DataFrame,
    *,
    highlight_player_ids: frozenset[int] = frozenset(),
) -> bytes:
    output = BytesIO()
    with xlsxwriter.Workbook(output, {"in_memory": True}) as workbook:
        title_format = workbook.add_format(
            {
                "font_name": "Calibri",
                "font_size": 14,
                "bold": True,
                "font_color": "#0072B2",
            }
        )
        highlight_format = workbook.add_format(
            {"bg_color": "#FFFF00", "font_name": "Calibri"}
        )
        worksheet = workbook.add_worksheet("Ladies Standings")
        worksheet.write(0, 1, "Flickornas Ställning", title_format)
        frame.write_excel(
            workbook=workbook,
            worksheet="Ladies Standings",
            position=(1, 0),
            table_style="Table Style Light 9",
            autofit=not highlight_player_ids,
            float_precision=2,
            dtype_formats={
                pl.Int64: "General",
                pl.Int32: "General",
                pl.Float64: "General",
                pl.Float32: "General",
            },
        )
        if highlight_player_ids and "contenderId" in frame.columns:
            for row_index, row in enumerate(frame.to_dicts(), start=2):
                if row["contenderId"] not in highlight_player_ids:
                    continue
                for column_index, value in enumerate(row.values()):
                    worksheet.write(
                        row_index,
                        column_index,
                        value,
                        highlight_format,
                    )
    return output.getvalue()


def _polars_to_typst(
    frame: pl.DataFrame,
    tournament_count: int,
    *,
    layout: str = "portrait",
    side_margin_cm: float = 0.8,
    finals_separators: Sequence[int] = (),
) -> str:
    cleaned = frame.fill_null("")
    for column in cleaned.columns:
        if cleaned[column].dtype == pl.Float64:
            cleaned = cleaned.with_columns(
                pl.when(
                    pl.col(column).is_finite()
                    & (pl.col(column) == pl.col(column).round())
                )
                .then(pl.col(column).cast(pl.Int64))
                .otherwise(pl.col(column))
                .alias(column)
            )
    typst_columns = [
        column for column in cleaned.columns if column != "played"
    ]
    lines = []
    page_orientation = (
        '\npaper: "a4", flipped: true,'
        if layout == "landscape"
        else ""
    )
    formatted_margin = f"{side_margin_cm:g}"
    initial_indent = "    "
    start = f"""{initial_indent}
#import "lib.typ": stylish_table, standings_heading
#set document(title: [Flickornas Ställning],
author: "Stockholms Schackförbunds UngdomsUtskott"
)
#set text(8pt, font: "Roboto")
#set page(numbering: "1 / 1",{page_orientation}
margin: (top: 0.8cm, bottom: 0.8cm, x: {formatted_margin}cm),
)
#standings_heading([Flickornas Ställning])
#stylish_table()[
      #table(
            """
    lines.append(start)
    columns = ["auto"] * len(typst_columns)
    columns[2] = "1fr"
    if any(
        max(
            len(str(row.get("Namn", ""))),
            len(str(row.get("Klubb", ""))),
        )
        > 48
        for row in cleaned.to_dicts()
    ):
        columns[1] = "1fr"
        columns[3] = "1fr"
    lines.append(f"columns: ({', '.join(columns)}),")
    alignment = (
        ["right + horizon"]
        + ["left + horizon"] * 3
        + ["right + horizon"] * (len(typst_columns) - 4)
    )
    lines.append(f"align: ({', '.join(alignment)}),")
    lines.append("rows: 1.8em,")
    lines.append(
        "table.header("
        + ", ".join(f"[*{column}*]" for column in typst_columns)
        + "),"
    )
    separator_rows = set(finals_separators)
    for row_number, row in enumerate(
        cleaned.select(typst_columns + ["played"]).to_dicts(),
        start=1,
    ):
        values = []
        for column in typst_columns:
            value = row[column]
            if 4 < tournament_count == row.get("played") and column == "Namn":
                value = f"#highlight[{_typst_content(value)}]"
            else:
                value = "" if value is None else _typst_content(value)
            values.append(f"[{value}]")
        lines.append("  " + ", ".join(values) + ",")
        if row_number in separator_rows:
            lines.append("  table.hline(stroke: 1pt + black),")
    lines.append(")]")
    return "\n".join(lines)


def _tournament_info_to_typst(tournament_names: Sequence[str]) -> str:
    halfway = len(tournament_names) // 2
    left = [f"+ {_typst_content(name)}" for name in tournament_names[:halfway]]
    right = [
        f"{index + 1}. {_typst_content(name)}"
        for index, name in enumerate(
            tournament_names[halfway:],
            start=halfway,
        )
    ]
    return "\n".join(
        [
            '#set text(9pt, font: "Roboto", weight: "medium")',
            "#columns(2)[",
            *left,
            "#colbreak()",
            *right,
            "]",
        ]
    )


def _typst_content(value: Any) -> str:
    text = str(value)
    for character in ("\\", "#", "[", "]", "*", "_", "`", "$", "@"):
        text = text.replace(character, f"\\{character}")
    return text


def _typst_string(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _public_standings_rows(
    standings: CollatedStandings,
) -> list[dict[str, Any]]:
    rows = []
    member_ids = standings.validation_rows.filter(
        ~pl.col("contenderId").is_in(standings.non_local_player_ids)
    )["contenderId"]
    for row in standings.published_rows.with_columns(member_ids).to_dicts():
        tournament_points = {
            tournament_id: row[str(index)]
            for index, tournament_id in enumerate(
                standings.tournament_ids,
                start=1,
            )
            if row.get(str(index)) is not None
        }
        rows.append(
            {
                "placement": row["Placering"],
                "member_id": row["contenderId"],
                "name": row["Namn"],
                "birth_year": row["Född"],
                "club": row["Klubb"],
                "tournaments": tournament_points,
                "total_points": row["Σ"],
            }
        )
    return rows


def _derive_diagnostics(
    tournaments: Sequence[TournamentInput],
    player_list: Mapping[str, Mapping[str, Any]],
    tournament_stats: Mapping[str, Mapping[str, Any]],
    supplied: GenerationDiagnostics,
    unmatched_player_ids: set[int],
) -> GenerationDiagnostics:
    dropouts = {
        key: list(values) for key, values in supplied.dropouts.items()
    }
    for tournament in tournaments:
        tournament_name = str(tournament_stats[tournament.identifier]["name"])
        existing = dropouts.setdefault(tournament_name, [])
        for record in tournament.records:
            if record["points"] >= 0:
                continue
            player_id = int(record["contenderId"])
            player_name = player_list.get(str(player_id), {}).get(
                "name",
                f"{record['playerInfo']['firstName']} "
                f"{record['playerInfo']['lastName']}",
            )
            finding = f"{player_name} ({player_id})"
            if finding not in existing:
                existing.append(finding)
    return GenerationDiagnostics(
        walkovers=supplied.walkovers,
        no_matches_played=supplied.no_matches_played,
        dropouts=dropouts,
        unmatched_player_ids=tuple(
            sorted(set(supplied.unmatched_player_ids) | unmatched_player_ids)
        ),
        round_count_mismatches=tuple(supplied.round_count_mismatches),
    )


def _diagnostic_reports(
    diagnostics: GenerationDiagnostics,
) -> dict[str, str]:
    reports = {
        "walkovers.txt": _grouped_report(diagnostics.walkovers),
        "no_matches_played.txt": _grouped_report(
            diagnostics.no_matches_played
        ),
        "dropouts.txt": _grouped_report(diagnostics.dropouts),
        "unmatched_player_ids.txt": _list_report(
            str(player_id) for player_id in diagnostics.unmatched_player_ids
        ),
        "round_count_mismatches.txt": _list_report(
            diagnostics.round_count_mismatches
        ),
    }
    if tuple(reports) != DIAGNOSTIC_FILENAMES:
        raise AssertionError("diagnostic report set is incomplete")
    return reports


def _grouped_report(values: Mapping[str, Sequence[str]]) -> str:
    if not values:
        return "(none)\n"
    lines = []
    for group, findings in values.items():
        lines.append(f"{group}:")
        lines.extend(f"\t{finding}" for finding in findings)
        lines.append("")
    return "\n".join(lines)


def _list_report(values: Iterable[str]) -> str:
    findings = tuple(values)
    return "\n".join(findings) + "\n" if findings else "(none)\n"
