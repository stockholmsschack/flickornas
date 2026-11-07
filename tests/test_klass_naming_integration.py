from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock

from flickornas_standings.generation_orchestrator import GenerationInputs, KlassNamingError, run_generation
from flickornas_standings.member_system_client import TournamentKlassNamingError
from tests.klass_naming_examples import bad_names
from tests import test_phase7_generation_form as form_tests
from tests import test_phase7_generation_operations as operation_tests

ROOT = Path(__file__).resolve().parents[1]


class KlassNamingRouteTests(unittest.TestCase):
    setUp = form_tests.GenerationFormTests.setUp
    tearDown = form_tests.GenerationFormTests.tearDown

    def refuse_tournaments(self):
        self.member_client.canonical_tournament = Mock(
            side_effect=TournamentKlassNamingError(100, bad_names())
        )

    def assert_naming_problems(self, response):
        self.assertEqual(response.status_code, 422, response.get_data(as_text=True))
        problems = response.get_json()['error']['details']['problems']
        self.assertEqual(len(problems), 2)
        for problem, expected in zip(problems, bad_names()):
            self.assertEqual(problem, {
                'field': 'tournaments',
                'message_key': f'errors.klass_naming.{expected.reason}',
                'parameters': {'tournament_id': expected.tournament_id,
                               'tournament_name': expected.tournament_name,
                               'group_id': expected.group_id,
                               'group_name': expected.group_name},
            })

    def test_lookup_returns_every_group_and_reason(self):
        self.refuse_tournaments()
        self.assert_naming_problems(self.client.get('/api/v1/tournaments/100'))

    def test_search_adapter_preserves_naming_failure_without_extra_lookups(self):
        self.member_client.tournament_group_search = Mock(
            side_effect=TournamentKlassNamingError(100, bad_names())
        )
        self.assert_naming_problems(self.client.get('/api/v1/tournaments/search?q=Minior'))
        self.assertEqual(self.member_client.lookup_ids, [])

    def test_defaults_returns_naming_failures(self):
        # One configured tournament keeps the expected problem list to two rows.
        original = self.member_client.canonical_tournament
        def resolve(tournament_id):
            if tournament_id == 200:
                return original(tournament_id)
            raise TournamentKlassNamingError(100, bad_names())
        self.member_client.canonical_tournament = Mock(side_effect=resolve)
        self.assert_naming_problems(self.client.get('/api/v1/generation/defaults'))

    def test_submission_refuses_before_creating_operation_or_lease(self):
        self.refuse_tournaments()
        self.assert_naming_problems(self.client.post('/api/v1/generation/operations', json={
            'year': 2026, 'tournament_ids': [100], 'layout': 'auto',
        }))
        self.assertFalse((self.state_directory / 'operations').exists())

    def test_save_preserves_configuration_after_naming_failure(self):
        self.refuse_tournaments()
        path = self.state_directory / 'active-configuration.toml'
        original = path.read_bytes()
        self.assert_naming_problems(self.client.post('/api/v1/configuration/tournaments', json={
            'revision': self.saved.revision, 'tournament_ids': [100],
        }))
        self.assertEqual(path.read_bytes(), original)

    def test_configuration_page_shows_names_as_escaped_code_with_help(self):
        self.refuse_tournaments()
        response = self.client.get('/configuration?lang=en')
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<code>Klass Minior</code>', body)
        self.assertIn('<code>Minior Nybörjare &lt;script&gt;</code>', body)
        self.assertIn('If the age klass is intended', body)
        self.assertIn('/help/group-names?lang=en', body)
        self.assertNotIn('The member system is unavailable', body.split('<script')[0])

    def test_help_is_localized_and_does_not_request_upstream_data(self):
        for lang, title in [('en', 'Group naming conventions'), ('sv', 'Namnregler för grupper')]:
            body = self.client.get('/help/group-names?lang=' + lang).get_data(as_text=True)
            self.assertIn(title, body)
            self.assertIn('<code>Minior</code>', body)
            self.assertIn('<code>Klass A Minior</code>', body)
            self.assertIn('8/7/6/5', body)
        self.assertEqual(self.member_client.lookup_ids, [])

    def test_direct_generation_has_validation_stage_and_rename_report(self):
        self.refuse_tournaments()
        inputs = GenerationInputs(2026, (100,), is_partial=True)
        with self.assertRaises(KlassNamingError) as caught:
            run_generation(self.saved, inputs, self.member_client)
        self.assertEqual(caught.exception.stage, 'validation')
        self.assertEqual(caught.exception.klass_problems, bad_names())
        self.assertIn('Rename these groups in the member system', caught.exception.report())

    def test_shared_browser_problem_rendering(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is not installed')
        result = subprocess.run([node, 'tests/browser/klass-naming.mjs'], cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class KlassOperationTests(unittest.TestCase):
    setUp = operation_tests.GenerationOperationTests.setUp
    tearDown = operation_tests.GenerationOperationTests.tearDown
    app = operation_tests.GenerationOperationTests.app
    start = operation_tests.GenerationOperationTests.start

    def test_background_failure_persists_problems_and_releases_lease(self):
        runner = operation_tests.RecordingRunner(KlassNamingError(bad_names()))
        executor = operation_tests.DeferredExecutor()
        client = self.app(executor, runner).test_client()
        response = self.start(client)
        self.assertEqual(response.status_code, 202)
        url = response.get_json()['data']['status_url']
        executor.run_next()
        document = client.get(url).get_json()['data']
        self.assertEqual(document['state'], 'failed')
        self.assertEqual(document['failure_stage'], 'validation')
        event = document['events'][-1]
        self.assertEqual(event['parameters']['stage'], 'validation')
        self.assertEqual(len(event['parameters']['problems']), 2)
        self.assertEqual(event['parameters']['problems'][1]['parameters']['group_name'], bad_names()[1].group_name)
        self.assertEqual(client.get(url).get_json()['data'], document)
        self.assertFalse((self.state_directory / 'operations' / 'generation.lease').exists())
