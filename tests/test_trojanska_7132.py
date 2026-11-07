"""Event mapping against captured metadata and the complete generation path."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from flickornas_standings.generation_orchestrator import (
    GenerationInputs, resolve_generation_request, run_generation,
)
from flickornas_standings.member_system_client import (
    MemberSystemClient, TournamentKlassNamingError, TournamentResolutionError,
    UpstreamDataError,
)
from tests.test_member_system_client import FakeResponse
from tests.test_generation_orchestrator import FixtureClient, _configuration, _table

FIXTURES = Path(__file__).parent / "fixtures/member_system/trojanska-7132"
EXPECTED = {19203: "a", 19204: "b", 19205: "c", 19206: "d", 19207: "y", 19208: "z"}


def document():
    return json.loads((FIXTURES / "tournament.json").read_text())


def client_for(data):
    return MemberSystemClient(session=Mock(get=Mock(return_value=FakeResponse(payload=data))))


def test_captured_mapping_preserves_names_rounds_and_upstream_order():
    data = document()
    tournament = client_for(data).canonical_tournament(7132)
    assert {g.group_id: g.klass for g in tournament.processable_groups} == EXPECTED
    assert [(g.group_id, g.name, g.registered_rounds) for g in tournament.processable_groups] == [
        (g["id"], g["name"], g["nrofrounds"]) for g in data["rootClasses"][0]["groups"]
    ]


@pytest.mark.parametrize("change, message", [
    ("season", "season 2026"),
    ("end_season", "season 2026"),
    ("missing", "missing group 19208"),
    ("unexpected", "unexpected group 99999"),
    ("name", "group 19203.*expected name"),
    ("duplicate", "duplicate group 19203"),
    ("moved", "missing group 19208.*first root"),
])
def test_invalid_event_metadata_fails_with_tournament_and_group(change, message):
    data = document()
    groups = data["rootClasses"][0]["groups"]
    if change == "season":
        data["start"] = data["end"] = "2025-10-24"
    elif change == "end_season":
        data["end"] = "2027-10-24"
    elif change == "missing":
        groups.pop()
    elif change == "unexpected":
        groups.append(dict(groups[0], id=99999))
    elif change == "name":
        groups[0]["name"] = "Klass A"
    elif change == "duplicate":
        groups.append(deepcopy(groups[0]))
    elif change == "moved":
        data["rootClasses"].append({"groups": [groups.pop()]})
    with pytest.raises(TournamentResolutionError, match=message) as caught:
        client_for(data).canonical_tournament(7132)
    assert caught.value.tournament_id == 7132


def test_other_tournaments_still_use_ordinary_parser():
    data = document()
    data["id"] = 7133
    with pytest.raises(TournamentKlassNamingError):
        client_for(data).canonical_tournament(7133)


def test_secondary_roots_remain_structurally_validated_and_not_processed():
    data = document()
    data["rootClasses"].append({"groups": [dict(data["rootClasses"][0]["groups"][0], id=99999)]})
    assert len(client_for(data).canonical_tournament(7132).processable_groups) == 6
    del data["rootClasses"][1]["groups"][0]["pointSystem"]
    with pytest.raises(UpstreamDataError):
        client_for(data).canonical_tournament(7132)


class EventClient(FixtureClient):
    def __init__(self, count=4, empty_group=None, filtered=False):
        super().__init__()
        self.resolver = client_for(document())
        self.count = count
        self.empty_group = empty_group
        self.filtered = filtered

    def canonical_tournament(self, tournament_id):
        self.calls.append(("canonical", tournament_id))
        return self.resolver.canonical_tournament(tournament_id)

    def group_table(self, group_id):
        self.calls.append(("table", group_id))
        rows = []
        for rank in range(1, self.count + 1 + (3 if self.filtered else 0)):
            row = deepcopy(_table(group_id)[0])
            row.update(contenderId=group_id * 10 + rank, place=rank, points=10-rank)
            row["playerInfo"].update(firstName=str(group_id), lastName=str(rank), birthdate="2018")
            if group_id == self.empty_group or (self.filtered and rank == self.count + 1):
                row["playerInfo"]["sex"] = 0
            if self.filtered and rank == self.count + 3:
                row.update(wonGames=0, lostGames=0, drawGames=0)
            rows.append(row)
        return rows

    def group_round_results(self, group_id):
        rounds = next(g["nrofrounds"] for g in document()["rootClasses"][0]["groups"] if g["id"] == group_id)
        games = [{"whiteId": group_id * 10 + rank, "blackId": -100, "result": 1}
                 for rank in range(1, self.count + 1)]
        if self.filtered:
            games.append({"whiteId": group_id * 10 + self.count + 2,
                          "blackId": group_id * 10 + self.count + 1, "result": -2})
        return [{"roundNr": r, "games": games} for r in range(1, rounds + 1)]


@pytest.mark.parametrize("count, empty_group, filtered", [(4, None, False), (1, None, False), (4, 19205, True)])
def test_resolution_and_background_generation_score_each_klass(count, empty_group, filtered):
    client = EventClient(count, empty_group, filtered)
    configuration = replace(_configuration(), default_tournament_ids=(7132,))
    # The worker receives the accepted snapshot, including during historical regeneration.
    request = resolve_generation_request(configuration, GenerationInputs(2026, (7132,), is_partial=True), client)
    result = run_generation(configuration, request, client)
    assert client.calls.count(("canonical", 7132)) == 1
    assert {call[1] for call in client.calls if call[0] == "table"} == set(EXPECTED)
    rows = result.standings.validation_rows.to_dicts()
    for group_id, klass in EXPECTED.items():
        group_rows = sorted((r for r in rows if r["klass"] == klass), key=lambda r: r["contenderId"])
        if group_id == empty_group:
            assert group_rows == []
            continue
        if klass == "z":
            expected = [8] if count == 1 else [8, 7, 6, 5]
        else:
            expected = [5] if count == 1 else [25, 16, 9, 5]
        assert [r["Σ"] for r in group_rows] == expected
        assert all(r["played"] == 1 for r in group_rows)
    if count == 4 and empty_group is None:
        assert [r["klass"] for r in rows if r["Σ"] == 25] == list("abcdy")
    if filtered:
        assert result.standings.diagnostics.walkovers
        assert result.standings.diagnostics.no_matches_played


def test_captured_results_pass_client_contracts_and_preview_generation():
    client = EventClient()
    upstream = client_for(document())
    def response(url, **kwargs):
        if "/organisation/" in url:
            return FakeResponse(payload=json.loads((FIXTURES / "district-clubs.json").read_text()))
        group_id = int(url.rsplit("/", 1)[1])
        suffix = "rounds" if "/roundresults/" in url else "table"
        payload = json.loads((FIXTURES / f"group-{group_id}-{suffix}.json").read_text())
        return FakeResponse(payload=payload)

    upstream.session.get.side_effect = response
    client.group_table = upstream.group_table
    client.group_round_results = upstream.group_round_results
    client.district_clubs = upstream.district_clubs
    result = run_generation(_configuration(), GenerationInputs(2026, (7132,), is_partial=True), client)
    assert "z" in result.standings.validation_rows["klass"].to_list()
    assert result.artifacts.standings_workbook.startswith(b"PK")


def test_walkover_only_transfer_contributes_once_in_destination_klass():
    client = EventClient()
    original_table = client.group_table
    original_rounds = client.group_round_results
    transferred = original_table(19204)[0]

    def table(group_id):
        rows = original_table(group_id)
        if group_id == 19203:
            rows.append(dict(deepcopy(transferred), groupId=19203))
        return rows

    def rounds(group_id):
        results = original_rounds(group_id)
        if group_id == 19203:
            for result in results:
                result["games"].append({"whiteId": transferred["contenderId"],
                                        "blackId": 999999, "result": -2})
        return results

    client.group_table = table
    client.group_round_results = rounds
    result = run_generation(_configuration(), GenerationInputs(2026, (7132,), is_partial=True), client)
    rows = [r for r in result.standings.validation_rows.to_dicts()
            if r["contenderId"] == transferred["contenderId"]]
    assert len(rows) == 1
    assert rows[0]["klass"] == "b"
    assert rows[0]["played"] == 1
    assert rows[0]["Σ"] == 25
