"""Flickornas registered into a host's own Flask application, under the manifest's prefix."""

from __future__ import annotations

from datetime import UTC, date, datetime
import io
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from flask import Blueprint, Flask, abort, g, request
from typer.testing import CliRunner
from werkzeug.exceptions import HTTPException

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    load_configuration,
    save_configuration,
)
from flickornas_standings.member_system_client import (
    CanonicalClub,
    CanonicalTournament,
    ClubId,
    PlayerId,
    PlayerInfo,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentGroupSearchHit,
    TournamentId,
)
from flickornas_standings.web import MANIFEST, create_app, register
from flickornas_standings.web.mercure import DisabledOperationPublisher
from tests.test_cli import FixtureRenderer, _generation_app, _write_configuration
from tests.test_generation_orchestrator import FixtureClient
from tests.test_phase7_generation_operations import DeferredExecutor, ImmediateExecutor, RecordingRunner
from tests.test_phase7_mercure import FailingPublisher


PREFIX = MANIFEST["url_prefix"]
HOST_SHELL = """<html lang="{{ locale }}"><head><title>{% block title %}{% endblock %}</title>
{% block head %}<link href="/host/bootstrap.css" rel="stylesheet">{% endblock %}</head>
<body><nav>Host navbar</nav>{% block content %}{% endblock %}
{% block scripts %}<script src="/host/bootstrap.bundle.js"></script>{% endblock %}</body></html>"""
HOST_USER = "X-Host-User"
# The configured 2026 tournament is still current, so a default generation runs.
IN_SEASON = {"CLOCK": lambda: datetime(2026, 12, 1, 12, tzinfo=UTC)}
START = "/api/v1/generation/operations"
DEFAULT_RUN = {"year": None, "tournament_ids": None, "layout": "auto"}


def CLOCK() -> datetime:
    # The 2026 season is over, so a rollover can start.
    return datetime(2027, 1, 10, 12, tzinfo=UTC)


def _tournament(tournament_id: int, name: str, start_date: date) -> CanonicalTournament:
    return CanonicalTournament(
        tournament_id=TournamentId(tournament_id),
        name=name,
        start_date=start_date,
        end_date=start_date,
        processable_groups=(
            ProcessableTournamentGroup(
                group_id=TournamentGroupId(1000 + tournament_id),
                name="Flickor",
                klass="F",
            ),
        ),
    )


class HostMemberClient:
    tournaments = {
        100: _tournament(100, "Saved 2026 tournament", date(2026, 10, 1)),
        200: _tournament(200, "January 2027 tournament", date(2027, 1, 9)),
    }

    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        return self.tournaments[tournament_id]

    def tournament_group_search(self, search_text: str) -> list[TournamentGroupSearchHit]:
        return [
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(1200),
                tournament_id=TournamentId(200),
                matching_group_name="Flickor",
                tournament_name="January 2027 tournament",
            )
        ]

    def player_name_search(self, first_name: str, last_name: str) -> list[PlayerInfo]:
        return [
            PlayerInfo(
                player_id=PlayerId(84),
                first_name=first_name,
                last_name=last_name,
                birth_year=2014,
                current_club_id=ClubId(10),
                current_club_name="Wasa SK",
                country="SWE",
                fide_id=None,
            )
        ]

    def district_clubs(self, district_id: int) -> list[CanonicalClub]:
        return [CanonicalClub(ClubId(10), "Wasa SK")]


def _draft_tournament(tournament_id: int) -> dict:
    tournament = HostMemberClient.tournaments[tournament_id]
    return {
        "tournament_id": tournament_id,
        "name": tournament.name,
        "start_date": tournament.start_date.isoformat(),
        "end_date": tournament.end_date.isoformat(),
    }


DRAFT_OVERRIDE = {
    "player_id": 84, "first_name": "My", "last_name": "Ek", "club_id": 10, "club_name": "Wasa SK",
}


def _snapshot(state_directory: Path) -> list[tuple[str, bytes]]:
    return sorted(
        (str(path.relative_to(state_directory)), path.read_bytes())
        for path in state_directory.rglob("*")
        if path.is_file()
    )


class HostedFlickornasTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.templates = self.root / "host-templates"
        self.templates.mkdir()
        (self.templates / "host_shell.jinja2").write_text(HOST_SHELL)
        self.state_directory = self.root / "state"
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={"name": "Test Contributor", "email": "test@example.com"},
            ),
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _host(self, **settings):
        """A host with its own `pages` Blueprint that lets only a signed-in user reach the mount."""
        host = Flask("host", template_folder=self.templates)
        host.config["SECRET_KEY"] = "host"
        host_pages = Blueprint("pages", "host")

        @host_pages.get("/")
        def landing():
            return "Host landing"

        host.register_blueprint(host_pages)

        @host.before_request
        def guard_the_mount():
            if request.path.startswith(PREFIX) and HOST_USER not in request.headers:
                abort(401)

        register(host, {
            "STATE_DIRECTORY": self.state_directory,
            "OUTPUT_DIRECTORY": self.root / "output",
            "MEMBER_SYSTEM_CLIENT": HostMemberClient(),
            "FILES_PUBLIC_ORIGIN": "https://files.example",
            "CLOCK": CLOCK,
            **settings,
        })
        client = host.test_client()
        client.environ_base[f"HTTP_{HOST_USER.upper().replace('-', '_')}"] = "admin@example.com"
        return client

    def test_the_landing_and_configuration_pages_load_under_the_prefix(self):
        for shell in (None, "host_shell.jinja2"):
            for lang, heading in (("sv", "Konfiguration"), ("en", "Configuration")):
                with self.subTest(shell=shell, lang=lang):
                    client = self._host(LOCALE=lambda: lang, **({"BASE_TEMPLATE": shell} if shell else {}))
                    for page in ("/", "/configuration"):
                        response = client.get(f"{PREFIX}{page}")
                        self.assertEqual(response.status_code, 200, page)
                        body = response.get_data(as_text=True)
                        self.assertIn(f'<html lang="{lang}">', body)
                        self.assertEqual("Host navbar" in body, bool(shell))
                        if shell:
                            # Flickornas' dialogs need the shell's Bootstrap, loaded before Flickornas' own scripts.
                            self.assertIn('<link href="/host/bootstrap.css"', body)
                            self.assertLess(
                                body.index('src="/host/bootstrap.bundle.js"'), body.index('id="locale-catalogue"')
                            )
                        self.assertIn(
                            f'id="group-names-help" rel="help" href="{PREFIX}/help/group-names"', body
                        )
                        assets = re.findall(r'(?:href|src)="(/[^"]*/static/[^"]+)"', body)
                        self.assertTrue(assets)
                        for asset in assets:
                            self.assertTrue(asset.startswith(f"{PREFIX}/static/"), asset)
                            with client.get(asset) as served:
                                self.assertEqual(served.status_code, 200, asset)
                        # Flickornas URLs include the mount prefix; the host supplies the hub URL.
                        self.assertNotRegex(body, r'(?:href|src|data-(?!mercure-hub)[a-z-]+)="/(?!tools/flickornas/|host/)')
                    self.assertIn(heading, body)

    def test_every_configuration_tab_saves_under_the_prefix_as_it_does_standalone(self):
        standalone_state = shutil.copytree(self.state_directory, self.root / "standalone-state")
        standalone = create_app({
            "TESTING": True,
            "STATE_DIRECTORY": standalone_state,
            "OUTPUT_DIRECTORY": self.root / "standalone-output",
            "MEMBER_SYSTEM_CLIENT": HostMemberClient(),
            "CLOCK": CLOCK,
        }).test_client()
        hosted = self._host()
        contributor = {"name": "X", "email": "x@example.com"}

        requests = [
            ("get", "/api/v1/tournaments/search?q=Flickor", lambda revision: {}),
            ("put", "/api/v1/configuration/tournaments/draft",
             lambda revision: {"json": {"revision": revision, "tournaments": [_draft_tournament(100)]}}),
            ("post", "/api/v1/configuration/tournaments/rollover", lambda revision: {"json": {"revision": revision}}),
            ("delete", "/api/v1/configuration/tournaments/rollover", lambda revision: {"json": {"revision": revision}}),
            ("post", "/api/v1/configuration/tournaments/rollover", lambda revision: {"json": {"revision": revision}}),
            ("put", "/api/v1/configuration/tournaments/draft",
             lambda revision: {"json": {"revision": revision, "tournaments": [_draft_tournament(200)]}}),
            ("post", "/api/v1/configuration/tournaments",
             lambda revision: {"json": {"revision": revision, "tournament_ids": [200]}}),
            ("get", "/api/v1/players/search?first_name=My&last_name=Ek", lambda revision: {}),
            ("put", "/api/v1/configuration/player-overrides/draft",
             lambda revision: {"json": {"revision": revision, "overrides": [DRAFT_OVERRIDE]}}),
            ("post", "/api/v1/configuration/player-overrides",
             lambda revision: {"json": {"revision": revision, "known_local_players": {"84": "Wasa SK"}}}),
            ("post", "/api/v1/configuration/finals",
             lambda revision: {"json": {"revision": revision, "finals_separators": [8]}}),
            ("post", "/api/v1/configuration/club-display-names",
             lambda revision: {"json": {
                 "revision": revision, "action": "upsert", "canonical_name": "Wasa SK", "display_name": "Wasa",
             }}),
            ("post", "/api/v1/configuration/contributor",
             lambda revision: {"json": {"revision": revision - 1, **contributor}}),
            ("post", "/api/v1/configuration/contributor", lambda revision: {"json": {"revision": revision, **contributor}}),
            ("post", "/api/v1/configuration/rules",
             lambda revision: {"data": {"rules": (io.BytesIO(b"= X\n"), "rules.typ")}}),
            ("delete", "/api/v1/configuration/rules", lambda revision: {}),
        ]

        def responses(client, prefix):
            revision, results = self.saved.revision, []
            for method, path, options in requests:
                response = getattr(client, method)(f"{prefix}{path}", **options(revision))
                revision = (response.get_json().get("data") or {}).get("revision", revision)
                results.append((response.status_code, response.get_json()))
            return results

        expected = responses(standalone, "")
        # Every request but the deliberately stale contributor save succeeds.
        self.assertEqual([status for status, _ in expected], [200] * 12 + [409] + [200] * 3)
        self.assertEqual(responses(hosted, PREFIX), expected)
        saved = load_configuration(self.state_directory)
        self.assertEqual(saved, load_configuration(standalone_state))
        self.assertEqual(saved.default_tournament_ids, (200,))
        self.assertEqual(dict(saved.known_local_players), {"84": "Wasa SK"})
        self.assertEqual(saved.finals_separators, (8,))
        self.assertEqual(dict(saved.club_display_names), {"Wasa SK": "Wasa"})
        self.assertEqual(saved.contributor, contributor)

    def test_both_drafts_coexist_with_host_session_data_of_the_same_names(self):
        client = self._host()
        host_keys = (
            "tournament_draft", "player_override_draft",
            "configuration_tournament_draft", "configuration_player_override_draft",
        )
        with client.session_transaction() as host_session:
            for key in host_keys:
                host_session[key] = "host"
        revision = self.saved.revision

        drafts = (
            client.put(f"{PREFIX}/api/v1/configuration/tournaments/draft",
                       json={"revision": revision, "tournaments": [_draft_tournament(200)]}),
            client.put(f"{PREFIX}/api/v1/configuration/player-overrides/draft",
                       json={"revision": revision, "overrides": [DRAFT_OVERRIDE]}),
        )

        self.assertEqual([draft.status_code for draft in drafts], [200, 200])
        page = client.get(f"{PREFIX}/configuration?lang=en").get_data(as_text=True)
        self.assertIn("January 2027 tournament", page)
        self.assertIn('"first_name": "My"', page)
        with client.session_transaction() as host_session:
            self.assertEqual({key: host_session[key] for key in host_keys}, dict.fromkeys(host_keys, "host"))
        self.assertEqual(load_configuration(self.state_directory), self.saved)

    def test_a_rejected_mutation_changes_neither_the_configuration_nor_the_rules_file(self):
        client = self._host(MUTATION_PROTECTION=lambda: False)
        (self.state_directory / "typst").mkdir()
        (self.state_directory / "typst" / "rules.typ").write_bytes(b"= Uploaded\n")
        before = _snapshot(self.state_directory)
        revision = {"revision": self.saved.revision}
        api = f"{PREFIX}/api/v1"

        rejected = [
            client.put(f"{api}/configuration/tournaments/draft", json={**revision, "tournaments": []}),
            client.post(f"{api}/configuration/tournaments", json={**revision, "tournament_ids": [200]}),
            client.post(f"{api}/configuration/tournaments/rollover", json=revision),
            client.delete(f"{api}/configuration/tournaments/rollover", json=revision),
            client.put(f"{api}/configuration/player-overrides/draft", json={**revision, "overrides": []}),
            client.post(f"{api}/configuration/player-overrides", json={**revision, "known_local_players": {}}),
            client.post(f"{api}/configuration/contributor", json={**revision, "name": "X", "email": "x@example.com"}),
            client.post(f"{api}/configuration/finals", json={**revision, "finals_separators": [8]}),
            client.post(f"{api}/configuration/club-display-names",
                        json={**revision, "action": "remove", "canonical_name": "Wasa SK"}),
            client.post(f"{api}/configuration/rules", data={"rules": (io.BytesIO(b"= X\n"), "rules.typ")}),
            client.delete(f"{api}/configuration/rules"),
            client.post(f"{api}/generation/inputs", json={"year": None, "tournament_ids": None, "layout": "auto"}),
            client.post(f"{api}/generation/operations", json={"year": None, "tournament_ids": None, "layout": "auto"}),
            client.post(f"{api}/downloads/clear"),
        ]

        self.assertEqual([response.status_code for response in rejected], [403] * len(rejected))
        self.assertTrue(all(response.get_json()["error"]["code"] == "http_403" for response in rejected))
        self.assertEqual(_snapshot(self.state_directory), before)
        self.assertEqual(client.get(f"{PREFIX}/configuration").status_code, 200)

    def test_the_host_guard_keeps_a_signed_out_user_from_the_mount(self):
        client = self._host()
        client.environ_base.clear()
        before = _snapshot(self.state_directory)

        self.assertEqual(client.get(f"{PREFIX}/configuration").status_code, 401)
        self.assertEqual(client.get(f"{PREFIX}/api/v1/generation/defaults").status_code, 401)
        self.assertEqual(
            client.post(f"{PREFIX}/api/v1/configuration/contributor", json={"name": "X"}).status_code, 401
        )
        self.assertEqual(_snapshot(self.state_directory), before)

    def test_the_host_keeps_its_own_pages_templates_api_errors_locale_and_hooks(self):
        (self.templates / "configuration.jinja2").write_text("Host configuration")
        (self.templates / "base.jinja2").write_text("Host base")
        client = self._host(MUTATION_PROTECTION=lambda: False)
        host = client.application

        @host.post("/api/v1/host")
        def host_api():
            self.assertNotIn("locale", g)
            abort(403)

        host.register_error_handler(HTTPException, lambda error: ({"host": error.code}, error.code))

        response = client.post("/api/v1/host?lang=en")
        self.assertEqual((response.status_code, response.get_json()), (403, {"host": 403}))
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(client.get("/").get_data(as_text=True), "Host landing")
        self.assertEqual(client.get("/static/js/locale.js").status_code, 404)
        flickornas = client.post(f"{PREFIX}/api/v1/configuration/contributor?lang=en", json={})
        self.assertEqual((flickornas.status_code, flickornas.get_json()["error"]["code"]), (403, "http_403"))
        page = client.get(f"{PREFIX}/configuration").get_data(as_text=True)
        self.assertNotIn("Host configuration", page)
        self.assertNotIn("Host base", page)

    def test_registration_fails_without_a_required_capability(self):
        for capability in ("STATE_DIRECTORY", "OUTPUT_DIRECTORY", "MEMBER_SYSTEM_CLIENT", "FILES_PUBLIC_ORIGIN"):
            with self.subTest(capability=capability):
                host = Flask("host")
                settings = {
                    "STATE_DIRECTORY": self.state_directory, "OUTPUT_DIRECTORY": self.root / "output",
                    "MEMBER_SYSTEM_CLIENT": HostMemberClient(), "FILES_PUBLIC_ORIGIN": "https://files.example",
                }
                del settings[capability]

                with self.assertRaisesRegex(KeyError, capability):
                    register(host, settings)
                self.assertNotIn("flickornas", host.extensions)
                self.assertEqual(host.blueprints, {})

    def test_a_localhost_host_header_cannot_enable_hosted_tournament_selection(self):
        for settings in ({}, {"GENERATION_TOURNAMENT_SELECTION_AUTHORIZER": lambda: False}):
            with self.subTest(callback=bool(settings)):
                client = self._host(**settings)

                page = client.get(f"{PREFIX}/configuration?lang=en", base_url="http://localhost")
                response = client.post(
                    f"{PREFIX}/api/v1/generation/inputs",
                    json={"year": 2026, "tournament_ids": [100], "layout": "auto"},
                    base_url="http://localhost",
                )

                self.assertNotIn('id="generation-explicit-tournaments"', page.get_data(as_text=True))
                self.assertEqual(
                    response.get_json()["error"]["code"], "generation_tournament_selection_forbidden"
                )

        administrator = self._host(GENERATION_TOURNAMENT_SELECTION_AUTHORIZER=lambda: True)
        page = administrator.get(f"{PREFIX}/configuration?lang=en", base_url="https://portal.example")
        self.assertIn('id="generation-explicit-tournaments"', page.get_data(as_text=True))

    def test_status_busy_and_reloaded_operation_links_keep_the_prefix(self):
        executor = DeferredExecutor()
        client = self._host(
            GENERATION_EXECUTOR=executor, GENERATION_RUNNER=RecordingRunner(), ACTOR=lambda: "admin@example.com",
            **IN_SEASON,
        )

        accepted = client.post(f"{PREFIX}{START}", json=DEFAULT_RUN).get_json()["data"]
        busy = client.post(f"{PREFIX}{START}", json=DEFAULT_RUN).get_json()["error"]["details"]
        status_url = f"{PREFIX}{START}/{accepted['operation_id']}"
        self.assertEqual(accepted["status_url"], status_url)
        self.assertEqual(busy["status_url"], status_url)
        executor.run_next()
        completed = client.get(status_url).get_json()["data"]
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["links"]["files"], f"{PREFIX}/downloads")

        record = self.state_directory / "operations" / f"{accepted['operation_id']}.json"
        record.write_text(record.read_text().replace(PREFIX, ""))  # a record from before the mount
        reloaded = self._host(**IN_SEASON).get(status_url).get_json()["data"]
        self.assertEqual(reloaded["status_url"], status_url)
        self.assertEqual(reloaded["links"]["files"], f"{PREFIX}/downloads")
        self.assertEqual(reloaded["actor"], "admin@example.com")

    def test_generation_and_status_work_without_a_working_publisher(self):
        # Credentials alone give a hosted registration no publisher; only `create_app` builds one.
        for publisher in ({"MERCURE_JWT_SECRET": "secret"}, {"MERCURE_PUBLISHER": FailingPublisher()}):
            with self.subTest(publisher=next(iter(publisher))):
                client = self._host(
                    MERCURE_PUBLIC_URL="https://hub.example/.well-known/mercure",
                    GENERATION_EXECUTOR=ImmediateExecutor(), GENERATION_RUNNER=RecordingRunner(), **publisher, **IN_SEASON,
                    FILES_PUBLIC_ORIGIN="https://files.example/tools/flickornas/",
                )
                self.assertIsInstance(
                    client.application.extensions["flickornas"]["mercure_publisher"],
                    FailingPublisher if "MERCURE_PUBLISHER" in publisher else DisabledOperationPublisher,
                )

                page = client.get(f"{PREFIX}/configuration").get_data(as_text=True)
                self.assertIn('data-mercure-hub="https://hub.example/.well-known/mercure"', page)
                status_url = client.post(f"{PREFIX}{START}", json=DEFAULT_RUN).get_json()["data"]["status_url"]
                status = client.get(status_url).get_json()["data"]
                self.assertEqual(status["state"], "completed")
                self.assertTrue(status["links"]["pdf"].startswith("https://files.example/tools/flickornas/downloads/"))
                self.assertEqual(status["links"]["files"], f"{PREFIX}/downloads")

    def test_the_command_the_standalone_and_the_hosted_application_produce_the_same_standings(self):
        def contract(output: Path) -> tuple[bytes, bytes]:
            (source,) = output.glob("runs/*/standings.typ")
            return source.read_bytes(), (output / "public-standings.json").read_bytes()

        _write_configuration(self.root / "cli-state")
        result = CliRunner().invoke(_generation_app(FixtureClient()), [
            "--state-directory", str(self.root / "cli-state"),
            "--output-directory", str(self.root / "cli-output"),
            "generate",
        ])
        self.assertEqual(result.exit_code, 0, result.output)

        for name, prefix in (("web", ""), ("hosted", PREFIX)):
            with self.subTest(name):
                _write_configuration(self.root / f"{name}-state")
                settings = {
                    "STATE_DIRECTORY": self.root / f"{name}-state",
                    "OUTPUT_DIRECTORY": self.root / f"{name}-output",
                    "MEMBER_SYSTEM_CLIENT": FixtureClient(),
                    "FILES_PUBLIC_ORIGIN": "https://files.example",
                    **IN_SEASON,
                    "GENERATION_EXECUTOR": ImmediateExecutor(),
                    "GENERATION_RENDERER": FixtureRenderer(),
                }
                if prefix:
                    app = Flask("host")
                    register(app, settings)
                else:
                    app = create_app(settings)
                client = app.test_client()

                status_url = client.post(f"{prefix}{START}", json=DEFAULT_RUN).get_json()["data"]["status_url"]
                self.assertTrue(status_url.startswith(f"{prefix}/api/"))
                self.assertEqual(client.get(status_url).get_json()["data"]["state"], "completed")
                self.assertEqual(contract(self.root / "cli-output"), contract(self.root / f"{name}-output"))


if __name__ == "__main__":
    unittest.main()
