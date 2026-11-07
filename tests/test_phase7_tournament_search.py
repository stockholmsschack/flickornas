from __future__ import annotations

from pathlib import Path

import pytest


JAVASCRIPT = Path(__file__).resolve().parents[1] / "flickornas_standings" / "web" / "static" / "js"


def test_configuration_mounts_localized_search_state_control(client):
    body = client.get("/configuration?lang=en").get_data(as_text=True)

    assert "Find tournaments" in body
    assert 'id="tournament-addition-tab"' in body
    assert ">\n                        Tournaments\n" in body
    assert 'class="nav-link active"' in body
    assert 'aria-selected="true"' in body
    assert 'id="tournament-addition-panel"' in body
    assert 'class="tab-pane active card-body"' in body
    assert body.index('id="selected-tournaments-heading"') < body.index(
        'id="tournament-addition-panel"'
    )
    assert "Type at least 3 characters" in body
    assert 'data-search-state="idle"' in body
    assert 'data-search-endpoint="/api/v1/tournaments/search"' in body
    assert (
        'data-lookup-endpoint-template="/api/v1/tournaments/__tournament_id__"'
        in body
    )
    assert "Or paste a tournament ID" in body
    assert "Selected tournaments" in body
    assert "Remove all" in body
    assert "data-remove-all-tournaments" in body
    assert "Remove tournament?" in body
    assert "Remove all tournaments?" in body
    assert "data-tournament-removal-dialog" in body
    assert "data-tournament-removal-name" in body
    assert "data-confirm-tournament-removal" in body
    assert "data-tournament-selection-toast" in body
    assert "Dismiss notification" in body
    assert "Find a tournament and verify it against the member system" not in body
    assert (
        "Tournaments are automatically ordered by start date, oldest first."
        not in body
    )
    assert "No tournaments selected." not in body
    assert "data-selected-tournaments" in body
    assert body.index("data-selected-tournaments") < body.index(
        "data-tournament-search-input"
    )
    assert "Select a search result or verify a pasted tournament ID." not in body
    assert 'data-selection-state="idle"' in body
    assert 'src="/static/js/tournament-search.js"' in body

    swedish = client.get("/configuration?lang=sv").get_data(as_text=True)
    assert "Hitta turneringar" in swedish
    assert "Skriv minst 3 tecken" in swedish
    assert "Eller klistra in ett turnerings-id" in swedish
    assert "Valda turneringar" in swedish
    assert "Ta bort alla" in swedish
    assert "Ta bort alla turneringar?" in swedish
    assert "Ta bort turneringen?" in swedish
    assert "Stäng meddelandet" in swedish
    assert "Är du säker på att du vill ta bort den här turneringen?" in swedish
    assert (
        "Turneringarna ordnas automatiskt efter startdatum, äldst först."
        not in swedish
    )
    assert "Inga turneringar valda." not in swedish
    assert (
        "Välj ett sökresultat eller verifiera ett inklistrat turnerings-id."
        not in swedish
    )


def test_browser_state_machine(run_browser_script):
    run_browser_script("tournament-search-state.mjs")


def test_picker_consumer_contract(run_browser_script):
    run_browser_script("tournament-picker.mjs")


@pytest.mark.parametrize(
    "path",
    [
        "/static/js/tournament-picker.js",
        "/static/js/tournament-search-state.js",
        "/static/js/tournament-search.js",
    ],
)
def test_search_scripts_are_served_locally(assert_served, path):
    assert_served(path)


def test_search_view_uses_the_local_lit_renderer():
    source = (JAVASCRIPT / "tournament-search.js").read_text(encoding="utf-8")

    assert 'import { html, nothing, render } from "./lit-html.js";' in source
    assert (
        "https://member.schack.se/ShowAllTournamentRegistrationsServlet?id="
        in source
    )
    assert 'target="_blank"' in source
    assert 'rel="noopener noreferrer"' in source
    assert 'class="link-body-emphasis ' in source
    assert 'class="badge text-bg-success' not in source
    assert "document.createElement" not in source
    assert "replaceChildren" not in source
