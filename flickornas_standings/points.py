"""Allocate standings points from tournament placement and class rules."""

from __future__ import annotations

import polars as pl


def assign_standings_point_by_player_rank(
    klass_group: str,
    frame: pl.DataFrame,
    place_column: str,
    scaled_points_column: str,
    points_column: str,
    secondary_points_column: str,
    standings_points_column: str,
    use_special_rules: bool = False,
) -> pl.DataFrame:
    """Sort players by rank and add the standings points column."""
    player_count = frame.filter(pl.col(points_column).is_not_null()).height
    rank_points = standings_points_by_player_rank(player_count)
    ranked = frame.sort(
        [
            place_column,
            (pl.col(scaled_points_column) * 10).cast(pl.Int64),
            secondary_points_column,
            "playerInfo.birthdate",
        ],
        descending=[False, True, True, True],
        nulls_last=True,
        maintain_order=True,
    ).with_columns(
        pl.when(pl.col(points_column).is_not_null())
        .then(pl.int_range(pl.len()) + 1)
        .otherwise(None)
        .alias("_standings_rank")
    )

    if use_special_rules and klass_group.lower() in {"e", "f", "z"}:
        points_expression = (
            pl.when(pl.col(points_column).is_null())
            .then(0)
            .when(pl.col("_standings_rank") == 1)
            .then(8)
            .when(pl.col("_standings_rank") == 2)
            .then(7)
            .when(pl.col("_standings_rank") == 3)
            .then(6)
            .otherwise(5)
        )
    else:
        rank_mapping = {
            rank: value for rank, value in enumerate(rank_points, start=1)
        }
        points_expression = (
            pl.when(pl.col(points_column).is_null())
            .then(0)
            .when(pl.col(points_column) < 0)
            .then(4)
            .when(pl.col("_standings_rank") <= len(rank_points))
            .then(
                pl.col("_standings_rank").replace_strict(
                    rank_mapping,
                    default=None,
                )
            )
            .otherwise(None)
        )

    return ranked.with_columns(
        points_expression.alias(standings_points_column)
    ).drop("_standings_rank")


def standings_points_by_player_rank(player_count: int) -> list[int]:
    """Return points for each rank using the established percentile curve."""
    points = []
    for rank in range(1, player_count + 1):
        percentile = (
            (player_count - rank) / (player_count - 1)
            if player_count > 1
            else 0
        )
        raw_points = (
            11 + 28 * (percentile - 0.5)
            if percentile >= 0.5
            else 5 + 12 * percentile
        )
        points.append(round(raw_points))
    return points
