import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function importBrowserModule(relativePath, replacements = new Map()) {
    let source = await readFile(
        new URL(relativePath, import.meta.url),
        "utf8",
    );
    for (const [specifier, replacement] of replacements) {
        source = source.replace(specifier, replacement);
    }
    return import(
        `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
    );
}

const stateSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/tournament-search-state.js",
        import.meta.url,
    ),
    "utf8",
);
const stateModuleUrl = (
    `data:text/javascript;base64,${Buffer.from(stateSource).toString("base64")}`
);
const {
    configurationTournamentConsumer,
    runTournamentConsumer,
    TournamentPicker,
} = await importBrowserModule(
    "../../flickornas_standings/web/static/js/tournament-picker.js",
    new Map([
        [
            '"./tournament-search-state.js"',
            JSON.stringify(stateModuleUrl),
        ],
    ]),
);

const tournaments = new Map([
    [300, {
        tournament_id: 300,
        name: "March later ID",
        start_date: "2026-03-01",
        end_date: "2026-03-02",
        processable_groups: [
            { group_id: 3, name: "Flickor C", klass: "C" },
        ],
    }],
    [200, {
        tournament_id: 200,
        name: "January",
        start_date: "2026-01-10",
        end_date: "2026-01-11",
        processable_groups: [
            { group_id: 2, name: "Flickor B", klass: "B" },
        ],
    }],
    [100, {
        tournament_id: 100,
        name: "March earlier ID",
        start_date: "2026-03-01",
        end_date: "2026-03-02",
        processable_groups: [
            { group_id: 1, name: "Flickor A", klass: "A" },
        ],
    }],
]);

function lookup(tournamentId) {
    return Promise.resolve({ tournament: tournaments.get(tournamentId) });
}

async function addTournaments(picker, tournamentIds) {
    for (const tournamentId of tournamentIds) {
        await picker.verifyTournamentId(tournamentId);
    }
}

const configurationDrafts = [];
const configurationCommits = [];
const configurationPicker = new TournamentPicker({
    lookup,
    consumer: configurationTournamentConsumer({
        initialTournaments: [tournaments.get(200)],
        selectionChanged(value) {
            configurationDrafts.push([...value.tournamentIds]);
        },
        commit(value) {
            configurationCommits.push([...value.tournamentIds]);
            return value;
        },
    }),
});
await addTournaments(configurationPicker, [300, 100]);
const configurationValue = configurationPicker.commit();

const runChanges = [];
const runPicker = new TournamentPicker({
    lookup,
    consumer: runTournamentConsumer({
        initialTournaments: [tournaments.get(200)],
        selectionChanged(value) {
            runChanges.push([...value.tournamentIds]);
        },
    }),
});
await addTournaments(runPicker, [100, 300]);
const runValue = runPicker.commit();

assert.deepEqual(configurationValue.tournamentIds, [200, 100, 300]);
assert.deepEqual(runValue.tournamentIds, [200, 100, 300]);
assert.deepEqual(configurationPicker.value, runPicker.value);
assert.deepEqual(configurationCommits, [[200, 100, 300]]);
assert.deepEqual(configurationDrafts.at(-1), [200, 100, 300]);
assert.deepEqual(runChanges.at(-1), [200, 100, 300]);

configurationPicker.replaceTournaments([tournaments.get(200)]);
assert.deepEqual(configurationPicker.value.tournamentIds, [200]);
assert.deepEqual(configurationDrafts.at(-1), [200]);

assert.equal(configurationPicker.removeAllTournaments(), true);
assert.deepEqual(configurationPicker.value.tournamentIds, []);
assert.deepEqual(configurationDrafts.at(-1), []);
assert.equal(configurationPicker.removeAllTournaments(), false);

console.log("tournament picker consumer contract tests passed");
