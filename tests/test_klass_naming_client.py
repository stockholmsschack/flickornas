import unittest
from unittest.mock import Mock

from flickornas_standings.member_system_client import (
    TournamentKlassNamingError, UpstreamDataError, resolve_canonical_tournaments,
)
from tests import test_member_system_client as client_tests
from tests.klass_naming_examples import bad_names


class KlassClientTests(unittest.TestCase):
    make_client = client_tests.MemberSystemClientContractTests.make_client

    def test_client_collects_all_refused_groups_in_order(self):
        payload = client_tests.fixture('tournament-6336.json')
        original = payload['rootClasses'][0]['groups'][0]
        names = ['Klass Minior', 'Klass A', 'Minior Nybörjare', 'Klass a', 'Final']
        payload['rootClasses'][0]['groups'] = [
            dict(original, id=8000 + index, name=name)
            for index, name in enumerate(names)
        ]
        client, session = self.make_client(payload)
        with self.assertRaises(TournamentKlassNamingError) as caught:
            client.canonical_tournament(6336)
        self.assertEqual([p.group_name for p in caught.exception.klass_problems],
                         ['Klass Minior', 'Minior Nybörjare', 'Klass a'])
        self.assertEqual([p.group_id for p in caught.exception.klass_problems], [8000, 8002, 8003])
        self.assertTrue(all(p.tournament_id == 6336 for p in caught.exception.klass_problems))
        self.assertEqual(session.get.call_count, 1)
        # A refused response must not be cached after the operator renames it.
        session.get.return_value = client_tests.FakeResponse(payload=client_tests.fixture('tournament-6336.json'))
        self.assertEqual(client.canonical_tournament(6336).processable_groups[0].klass, 'a')
        self.assertEqual(session.get.call_count, 2)

    def test_secondary_root_names_are_ignored_but_structure_is_validated(self):
        payload = client_tests.fixture('tournament-6336.json')
        payload['rootClasses'].append({'groups': [
            dict(payload['rootClasses'][0]['groups'][0], name='Minior Junior Klass a')
        ]})
        client, _ = self.make_client(payload)
        self.assertEqual(len(client.canonical_tournament(6336).processable_groups), 1)
        del payload['rootClasses'][1]['groups'][0]['name']
        client, _ = self.make_client(payload)
        with self.assertRaises(UpstreamDataError):
            client.canonical_tournament(6336)

    def test_real_6336_response_resolves_as_recorded(self):
        client, session = self.make_client(client_tests.fixture('tournament-6336-live.json'))
        tournament = client.canonical_tournament(6336)
        self.assertEqual([(g.name, g.klass) for g in tournament.processable_groups],
                         [('Öppen klass', 'y'), ('Nybörjarklass', 'z')])
        self.assertEqual(session.get.call_count, 1)

    def test_collection_preserves_naming_problems(self):
        client = Mock()
        client.canonical_tournament.side_effect = TournamentKlassNamingError(100, bad_names())
        result = resolve_canonical_tournaments(client, (100,), collect_problems=True)
        self.assertEqual(result.problems[0].klass_problems, bad_names())
        with self.assertRaises(TournamentKlassNamingError) as caught:
            result.require_all()
        self.assertEqual(caught.exception.klass_problems, bad_names())

