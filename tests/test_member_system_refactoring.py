from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import polars as pl

from flickornas_standings import run_state
from flickornas_standings.atomic_write import atomic_create_text, atomic_replace_text
from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.web import create_app
from flickornas_standings.generation_core import GenerationDiagnostics
from flickornas_standings.member_system_client import MemberSystemClient, UpstreamDataError
from flickornas_standings.numeric_validation import (
    is_non_negative_finite_number,
    is_non_negative_integer,
    is_positive_finite_number,
    is_positive_integer,
)
from flickornas_standings.points import (
    assign_standings_point_by_player_rank,
    standings_points_by_player_rank,
)

from tests.test_member_system_client import FakeResponse, fixture


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class ClientCacheTests(unittest.TestCase):
    def make_client(self, effects, clock: MutableClock):
        session = Mock()
        session.get.side_effect = effects
        return (
            MemberSystemClient(
                session=session,
                max_attempts=1,
                backoff_seconds=0,
                clock=clock,
                short_cache_ttl=10,
                reference_cache_ttl=60,
            ),
            session,
        )

    def test_canonical_tournament_refreshes_after_short_ttl(self):
        clock = MutableClock()
        first = fixture("tournament-6336.json")
        second = deepcopy(first)
        second["name"] = "Renamed tournament"
        client, session = self.make_client(
            [FakeResponse(payload=first), FakeResponse(payload=second)],
            clock,
        )

        self.assertEqual(client.canonical_tournament(6336).name, first["name"])
        self.assertEqual(client.canonical_tournament(6336).name, first["name"])
        clock.value = 10
        self.assertEqual(
            client.canonical_tournament(6336).name,
            "Renamed tournament",
        )
        self.assertEqual(session.get.call_count, 2)

    def test_mutating_a_result_does_not_change_the_cached_value(self):
        clock = MutableClock()
        client, session = self.make_client(
            [FakeResponse(payload=fixture("group-table.json"))],
            clock,
        )

        first = client.group_table(7001)
        first[0]["playerInfo"]["firstName"] = "Changed"

        second = client.group_table(7001)
        self.assertNotEqual(second[0]["playerInfo"]["firstName"], "Changed")
        self.assertEqual(session.get.call_count, 1)

    def test_contract_failure_is_not_cached(self):
        clock = MutableClock()
        client, session = self.make_client(
            [
                FakeResponse(payload=[{"id": 10}]),
                FakeResponse(payload=fixture("clubs.json")),
            ],
            clock,
        )

        with self.assertRaises(UpstreamDataError):
            client.district_clubs(5821)

        self.assertEqual(client.district_clubs(5821)[0].name, "Stockholms SK")
        self.assertEqual(session.get.call_count, 2)

    def test_district_club_rename_appears_after_reference_ttl(self):
        clock = MutableClock()
        first = fixture("clubs.json")
        second = deepcopy(first)
        second[0]["name"] = "Renamed club"
        client, session = self.make_client(
            [FakeResponse(payload=first), FakeResponse(payload=second)],
            clock,
        )

        self.assertEqual(client.district_clubs(5821)[0].name, "Stockholms SK")
        clock.value = 60
        self.assertEqual(client.district_clubs(5821)[0].name, "Renamed club")
        self.assertEqual(session.get.call_count, 2)

    def test_cached_reads_proceed_while_another_fetch_is_in_flight(self):
        clock = MutableClock()
        cached_name: list[str] = []
        responses = [
            FakeResponse(payload=fixture("clubs.json")),
            FakeResponse(payload=fixture("tournament-6336.json")),
        ]

        def respond(*_args, **_kwargs):
            response = responses.pop(0)
            if responses:
                return response
            reader = threading.Thread(
                target=lambda: cached_name.append(
                    client.district_clubs(5821)[0].name
                )
            )
            reader.start()
            reader.join(timeout=5)
            self.assertFalse(reader.is_alive())
            return response

        client, _session = self.make_client(respond, clock)

        client.district_clubs(5821)
        client.canonical_tournament(6336)

        self.assertEqual(cached_name, ["Stockholms SK"])


class AtomicWriteTests(unittest.TestCase):
    def test_create_only_write_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_create_text(path, "first")

            with self.assertRaises(FileExistsError):
                atomic_create_text(path, "second")

            self.assertEqual(path.read_text(), "first")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_failed_replacement_preserves_existing_content_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("first")

            with (
                patch("flickornas_standings.atomic_write.os.replace", side_effect=OSError("failed")),
                self.assertRaisesRegex(OSError, "failed"),
            ):
                atomic_replace_text(path, "second")

            self.assertEqual(path.read_text(), "first")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_successful_write_fsyncs_file_and_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch("flickornas_standings.atomic_write.os.fsync", wraps=__import__("os").fsync) as fsync:
                atomic_replace_text(path, "content")

            self.assertGreaterEqual(fsync.call_count, 2)

    def test_directory_fsync_failure_leaves_committed_file_and_no_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with (
                patch(
                    "flickornas_standings.atomic_write._fsync_directory",
                    side_effect=OSError("directory fsync failed"),
                ),
                self.assertRaisesRegex(OSError, "directory fsync failed"),
            ):
                atomic_replace_text(path, "content")

            self.assertEqual(path.read_text(), "content")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_serialization_failure_creates_no_state_file_or_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with (
                patch("flickornas_standings.run_state.json.dumps", side_effect=TypeError("bad value")),
                self.assertRaisesRegex(TypeError, "bad value"),
            ):
                run_state._atomic_create_json(path, {"bad": object()})

            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])


class PrimitivePredicateTests(unittest.TestCase):
    def test_integer_predicates_reject_booleans(self):
        self.assertFalse(is_positive_integer(True))
        self.assertFalse(is_non_negative_integer(False))
        self.assertTrue(is_positive_integer(1))
        self.assertTrue(is_non_negative_integer(0))

    def test_number_predicates_require_finite_values(self):
        for value in (True, float("inf"), float("-inf"), float("nan")):
            self.assertFalse(is_positive_finite_number(value))
            self.assertFalse(is_non_negative_finite_number(value))
        self.assertTrue(is_positive_finite_number(0.5))
        self.assertTrue(is_non_negative_finite_number(0))


class PointsCleanupTests(unittest.TestCase):
    def frame(self, points: list[int | None]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "place": list(range(1, len(points) + 1)),
                "scaled_pts": [value or 0 for value in points],
                "points": points,
                "secPoints": [0] * len(points),
                "playerInfo.birthdate": [2010] * len(points),
            }
        )

    def assign(
        self,
        points: list[int | None],
        *,
        klass: str = "a",
        special: bool = False,
    ) -> list[int]:
        result = assign_standings_point_by_player_rank(
            klass,
            self.frame(points),
            "place",
            "scaled_pts",
            "points",
            "secPoints",
            "standings",
            special,
        )
        return result["standings"].to_list()

    def test_rank_curve_handles_zero_one_two_and_several_players(self):
        self.assertEqual(standings_points_by_player_rank(0), [])
        self.assertEqual(standings_points_by_player_rank(1), [5])
        self.assertEqual(standings_points_by_player_rank(2), [25, 5])
        self.assertEqual(len(standings_points_by_player_rank(8)), 8)

    def test_null_and_negative_points_keep_existing_allocation_rules(self):
        self.assertEqual(self.assign([3, -1, None]), [25, 4, 0])

    def test_special_classes_use_the_fixed_top_three_curve(self):
        self.assertEqual(
            self.assign([4, 3, 2, 1], klass="e", special=True),
            [8, 7, 6, 5],
        )


class DiagnosticsBoundaryTests(unittest.TestCase):
    def test_grouped_values_are_tuples_in_read_only_mappings(self):
        diagnostics = GenerationDiagnostics(walkovers={"Tournament": ["A"]})

        self.assertEqual(diagnostics.walkovers["Tournament"], ("A",))
        with self.assertRaises(TypeError):
            diagnostics.walkovers["Other"] = ("B",)


class DeferredExecutor:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, function, *arguments):
        self.submissions.append((function, arguments))
        return SimpleNamespace()


class GenerationRequestCountTests(unittest.TestCase):
    def test_operator_journey_fetches_each_tournament_once(self):
        documents = {}
        template = fixture("tournament-6336.json")
        for tournament_id in (101, 102, 103):
            document = deepcopy(template)
            document["id"] = tournament_id
            document["name"] = f"Tournament {tournament_id}"
            document["rootClasses"][0]["groups"][0]["id"] = (
                tournament_id * 10
            )
            documents[tournament_id] = document

        session = Mock()

        def response(url, **_kwargs):
            tournament_id = int(url.rsplit("/", 1)[-1])
            return FakeResponse(payload=deepcopy(documents[tournament_id]))

        session.get.side_effect = response
        client = MemberSystemClient(
            session=session,
            max_attempts=1,
            backoff_seconds=0,
        )
        executor = DeferredExecutor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_configuration(
                root / "state",
                ActiveConfiguration(
                    default_tournament_ids=(101, 102, 103),
                    contributor={
                        "name": "Test",
                        "email": "test@example.com",
                    },
                ),
            )
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "request-count",
                    "STATE_DIRECTORY": root / "state",
                    "OUTPUT_DIRECTORY": root / "output",
                    "MEMBER_SYSTEM_CLIENT": client,
                    "GENERATION_EXECUTOR": executor,
                }
            )
            web = app.test_client()

            self.assertEqual(web.get("/configuration").status_code, 200)
            self.assertEqual(
                web.get("/api/v1/generation/defaults").status_code,
                200,
            )
            started = web.post(
                "/api/v1/generation/operations",
                json={"year": None, "tournament_ids": None, "layout": "auto"},
            )

        self.assertEqual(started.status_code, 202)
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(len(executor.submissions), 1)


if __name__ == "__main__":
    unittest.main()
