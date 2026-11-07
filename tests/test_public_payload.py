import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from flickornas_standings.generation_core import serialize_standings_json
from flickornas_standings.generation_orchestrator import GenerationInputs, run_generation
from tests.test_generation_core import _eligibility_result
from tests.test_generation_orchestrator import FixtureClient, _configuration, _metadata


def test_last_updated_records_generation_time_in_utc():
    before = datetime.now(UTC).replace(microsecond=0)
    snapshot = json.loads(serialize_standings_json([], tournament_ids=[]))
    after = datetime.now(UTC)

    last_updated = datetime.fromisoformat(snapshot['last_updated'])
    assert last_updated.utcoffset() == timedelta(0)
    assert before <= last_updated <= after


def test_member_ids_match_ranked_players_after_nonlocals_are_removed():
    snapshot = json.loads(_eligibility_result().artifacts.standings_json)
    assert snapshot['tournament_ids'] == [42]
    assert [(row['member_id'], row['name']) for row in snapshot['standings']] == [
        (100, 'Local One Player'), (101, 'Local Two Player'),
    ]


@pytest.mark.parametrize('same_date', [False, True])
def test_tournament_ids_follow_table_order_for_reversed_selection(same_date):
    client = FixtureClient()
    if same_date:
        client.metadata[22] = _metadata(22, start='2026-02-01', end='2026-02-02')
    result = run_generation(
        _configuration(), GenerationInputs(effective_year=2026, tournament_ids=(22, 11)), client,
    )
    snapshot = json.loads(result.artifacts.standings_json)
    assert snapshot['tournament_ids'] == [11, 22]
    assert result.standings.tournament_ids == ('11', '22')
    for row in snapshot['standings']:
        assert list(row['tournaments']) == ['11', '22']
        assert row['member_id'] == 100
        assert row['tournaments'] == {'11': 25, '22': 25}


@pytest.mark.parametrize('member_id', [True, 0, -1, None, '100', 100.5])
def test_invalid_member_ids_are_refused(member_id):
    row = json.loads(_eligibility_result().artifacts.standings_json)['standings'][0]
    row['member_id'] = member_id
    with pytest.raises(ValueError, match='member_id must be a positive integer'):
        serialize_standings_json([row], tournament_ids=[42])


@pytest.mark.parametrize('ids, message', [
    ([True], 'positive integers'),
    ([0], 'positive integers'),
    (['42'], 'positive integers'),
    ([42, 42], 'unique'),
])
def test_invalid_tournament_ids_are_refused(ids, message):
    with pytest.raises(ValueError, match=message):
        serialize_standings_json([], tournament_ids=ids)


def test_standalone_payload_returns_404_before_publication(client):
    assert client.get('/api/v1/standings/flickornas').status_code == 404


def test_standalone_payload_reads_latest_published_snapshot(app, client):
    output = Path(app.config['OUTPUT_DIRECTORY'])
    run = output / 'runs' / 'test'
    run.mkdir(parents=True)
    payload = run / 'standings.json'
    (output / 'public-standings.json').symlink_to('runs/test/standings.json')
    for body in (
        b'{"tournament_ids": [11], "standings": []}',
        b'{"tournament_ids": [11, 22], "standings": []}',
    ):
        payload.write_bytes(body)
        response = client.get('/api/v1/standings/flickornas')
        assert response.status_code == 200
        assert response.mimetype == 'application/json'
        assert response.headers['Cache-Control'] == 'no-cache'
        assert response.data == body
    payload.unlink()
    assert client.get('/api/v1/standings/flickornas').status_code == 404
