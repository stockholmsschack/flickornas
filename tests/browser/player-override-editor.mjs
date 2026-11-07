import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/player-override-editor-state.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    playerFullName,
    PlayerOverrideEditorState,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

const player = {
    player_id: 42,
    first_name: " My ",
    last_name: " Ek ",
};
const firstClub = { club_id: 10, name: " Stockholms SK " };
const secondClub = { club_id: 20, name: "Wasa SK" };
const states = [];
const editor = new PlayerOverrideEditorState({
    initialOverrides: [
        {
            player_id: 7,
            first_name: null,
            last_name: null,
            club_id: null,
            club_name: "Saved Club",
        },
    ],
    onChange(state) {
        states.push(state);
    },
});

assert.equal(editor.addOverride().status, "failure");
assert.equal(editor.state.overrides.length, 1);
assert.equal(playerFullName(editor.state.overrides[0].player), null);
assert.deepEqual(editor.value(), { 7: "Saved Club" });
assert.deepEqual(editor.draftValue(), [
    {
        player_id: 7,
        first_name: null,
        last_name: null,
        display_name: null,
        club_id: null,
        club_name: "Saved Club",
    },
]);
assert.equal(editor.removeOverride(7).status, "removed");
assert.equal(editor.selectPlayer({ player_id: "42", first_name: "My" }), false);
assert.equal(editor.selectClub({ club_id: null, name: "Free text" }), false);
assert.equal(editor.selectPlayer(player), true);
assert.equal(editor.addOverride().status, "failure");
assert.equal(editor.selectClub(firstClub), true);

const added = editor.addOverride();
assert.equal(added.status, "added");
editor.clearPlayerSelection();
editor.clearClubSelection();
assert.equal(editor.state.selectedPlayer, null);
assert.equal(editor.state.selectedClub, null);
assert.equal(editor.state.overrides.length, 1);
assert.equal(playerFullName(added.override.player), "My Ek");
assert.deepEqual(editor.value(), { 42: "Stockholms SK" });
assert.deepEqual(editor.names(), { 42: "My Ek" });

assert.equal(editor.selectPlayer(player), true);
assert.equal(editor.selectClub(firstClub), true);
const unchanged = editor.addOverride();
assert.equal(unchanged.status, "unchanged");
assert.equal(editor.state.overrides.length, 1);

assert.equal(editor.selectClub(secondClub), true);
const replaced = editor.addOverride();
assert.equal(replaced.status, "replaced");
assert.equal(replaced.previousClub.name, "Stockholms SK");
assert.equal(editor.state.overrides.length, 1);
assert.deepEqual(editor.value(), { 42: "Wasa SK" });

const otherPlayer = {
    player_id: 84,
    first_name: "Bo",
    last_name: "Li",
};
assert.equal(editor.selectPlayer(otherPlayer), true);
assert.equal(editor.addOverride().status, "added");
assert.deepEqual(editor.value(), { 42: "Wasa SK", 84: "Wasa SK" });
assert.deepEqual(editor.names(), { 42: "My Ek", 84: "Bo Li" });

assert.equal(editor.removeOverride(999).status, "failure");
const removed = editor.removeOverride(42);
assert.equal(removed.status, "removed");
assert.equal(playerFullName(removed.overrides[0].player), "My Ek");
assert.deepEqual(editor.value(), { 84: "Wasa SK" });

const savedOverrides = editor.draftValue();
editor.removeAllOverrides();
editor.replaceOverrides(savedOverrides);
assert.deepEqual(editor.value(), { 84: "Wasa SK" });

const removedAll = editor.removeAllOverrides();
assert.equal(removedAll.status, "removed_all");
assert.deepEqual(
    removedAll.overrides.map((override) => playerFullName(override.player)),
    ["Bo Li"],
);
assert.deepEqual(editor.value(), {});
assert.deepEqual(editor.names(), {});
assert.equal(editor.removeAllOverrides().status, "failure");
assert.ok(states.length > 0);

console.log("player override editor browser tests passed");
