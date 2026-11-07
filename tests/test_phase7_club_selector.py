from __future__ import annotations

from pathlib import Path

import pytest


JAVASCRIPT = Path(__file__).resolve().parents[1] / "flickornas_standings" / "web" / "static" / "js"


def test_configuration_mounts_localized_standalone_club_selector(client):
    body = client.get("/configuration?lang=en").get_data(as_text=True)

    assert "Find club" in body
    assert "data-club-selector" in body
    assert 'data-clubs-endpoint="/api/v1/clubs"' in body
    assert 'src="/static/js/club-selector.js"' in body

    swedish = client.get("/configuration?lang=sv").get_data(as_text=True)
    assert "Hitta klubb" in swedish


def test_browser_state_machine(run_browser_script):
    run_browser_script("club-selector.mjs")


def test_selector_is_lit_html_and_independent_of_player_state():
    source = (JAVASCRIPT / "club-selector.js").read_text(encoding="utf-8")

    assert 'import { html, nothing, render } from "./lit-html.js";' in source
    assert '"flickornas:club-selection-changed"' in source
    assert "player" not in source.lower()
    assert "document.createElement" not in source
    assert "replaceChildren" not in source


@pytest.mark.parametrize(
    "path",
    ["/static/js/club-selector-state.js", "/static/js/club-selector.js"],
)
def test_selector_scripts_are_served_locally(assert_served, path):
    assert_served(path)
