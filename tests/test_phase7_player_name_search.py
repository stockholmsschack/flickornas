from __future__ import annotations

from pathlib import Path

import pytest


JAVASCRIPT = Path(__file__).resolve().parents[1] / "flickornas_standings" / "web" / "static" / "js"


def test_configuration_mounts_localized_player_name_selector(client):
    body = client.get("/configuration?lang=en").get_data(as_text=True)

    assert "Find players" in body
    assert "data-player-name-selector" in body
    assert 'data-search-endpoint="/api/v1/players/search"' in body
    assert "/api/v1/players/__player_id__" not in body
    assert "data-reference-date" not in body
    assert 'src="/static/js/player-name-selector.js"' in body

    swedish = client.get("/configuration?lang=sv").get_data(as_text=True)
    assert "Hitta spelare" in swedish


def test_browser_state_machine(run_browser_script):
    run_browser_script("player-name-search.mjs")


@pytest.mark.parametrize(
    "path",
    [
        "/static/js/player-name-search-state.js",
        "/static/js/player-name-selector.js",
    ],
)
def test_selector_scripts_are_served_locally(assert_served, path):
    assert_served(path)


def test_selector_uses_lit_html_without_manual_dom_replacement():
    source = (JAVASCRIPT / "player-name-selector.js").read_text(encoding="utf-8")

    assert 'import { html, nothing, render } from "./lit-html.js";' in source
    assert "document.createElement" not in source
    assert "replaceChildren" not in source
    assert "setTimeout" not in source
    assert "debounce" not in source.lower()


def test_selector_emits_the_explicitly_selected_search_result():
    source = (JAVASCRIPT / "player-name-selector.js").read_text(encoding="utf-8")

    assert '"flickornas:player-selection-changed"' in source
    assert "this.selectedPlayer = player" in source
    assert "data-selected-player-id" in source
    assert "PlayerVerificationState" not in source
    assert "resolvePlayer" not in source
