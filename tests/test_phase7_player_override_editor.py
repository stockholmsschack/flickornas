from __future__ import annotations

from pathlib import Path

import pytest


JAVASCRIPT = Path(__file__).resolve().parents[1] / "flickornas_standings" / "web" / "static" / "js"


def test_configuration_composes_independent_selectors(client):
    body = client.get("/configuration?lang=en").get_data(as_text=True)

    assert "data-player-override-editor" in body
    assert 'id="player-addition-tab"' in body
    assert 'aria-selected="false"' in body
    assert 'id="player-addition-panel"' in body
    assert 'class="tab-pane card-body"' in body
    assert "data-player-name-selector" in body
    assert "data-club-selector" in body
    assert "data-save-player-override" in body
    assert 'class="d-flex justify-content-end mt-3"' in body
    assert "data-player-overrides" in body
    assert "data-remove-all-player-overrides" in body
    assert "data-player-override-removal-dialog" in body
    assert "data-player-override-toast" in body
    assert "data-draft-endpoint" not in body
    assert "/api/v1/configuration/player-overrides" in body
    assert "selected-player-overrides-data" in body
    assert 'src="/static/js/player-override-editor.js"' in body


def test_collection_behavior(run_browser_script):
    run_browser_script("player-override-editor.mjs")


def test_editor_uses_selector_events_and_bootstrap_protections():
    source = (JAVASCRIPT / "player-override-editor.js").read_text(encoding="utf-8")

    assert '"flickornas:player-selection-changed"' in source
    assert '"flickornas:club-selection-changed"' in source
    assert '"flickornas:player-selector-reset"' in source
    assert '"flickornas:club-selector-reset"' in source
    assert 'outcome.status === "failure"' in source
    assert "new globalThis.bootstrap.Modal" in source
    assert "new globalThis.bootstrap.Toast" in source
    assert "playerDisplayName(override.player)" in source
    assert "fetch(" in source
    assert "editor.replaceOverrides(previousOverrides)" in source
    assert "editor.names()" in source
    assert "saveReason(editor.state)" in source
    assert '"flickornas:before-navigation"' not in source
    assert "persistDraft" not in source
    assert 'from "./player-name-selector.js"' not in source
    assert 'from "./club-selector.js"' not in source


@pytest.mark.parametrize(
    ("filename", "mount", "selection_event", "state_event"),
    [
        (
            "player-name-selector.js",
            "mountPlayerNameSelector",
            "flickornas:player-selection-changed",
            "flickornas:player-selector-state-changed",
        ),
        (
            "club-selector.js",
            "mountClubSelector",
            "flickornas:club-selection-changed",
            "flickornas:club-selector-state-changed",
        ),
    ],
)
def test_selectors_expose_independent_mounting_contracts(
    filename, mount, selection_event, state_event
):
    source = (JAVASCRIPT / filename).read_text(encoding="utf-8")

    assert f"export function {mount}(options)" in source
    assert "renderTarget" in source
    assert "initialValue" in source
    assert "lookup" in source
    assert "translations" in source
    assert selection_event in source
    assert state_event in source
    assert "detail: { value" in source
    assert "detail: { state }" in source


def test_selectors_do_not_reference_each_other():
    player_source = (JAVASCRIPT / "player-name-selector.js").read_text(encoding="utf-8")
    club_source = (JAVASCRIPT / "club-selector.js").read_text(encoding="utf-8")

    assert "club-selector" not in player_source
    assert "player-name-selector" not in club_source
    assert "player_selection.clear" in player_source


@pytest.mark.parametrize(
    "path",
    [
        "/static/js/player-override-editor-state.js",
        "/static/js/player-override-editor.js",
    ],
)
def test_editor_scripts_are_served_locally(assert_served, path):
    assert_served(path)
