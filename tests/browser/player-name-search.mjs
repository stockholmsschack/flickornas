import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/player-name-search-state.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    parsePlayerName,
    playerNameSearchPresentation,
    PlayerNameSearchState,
    playerNameSearchUrl,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

function deferred() {
    let resolve;
    const promise = new Promise((resolvePromise) => {
        resolve = resolvePromise;
    });
    return { promise, resolve };
}

assert.deepEqual(parsePlayerName("  My \t Ek \n Lund  "), {
    valid: true,
    normalizedName: "My Ek Lund",
    firstName: "My",
    lastName: "Ek Lund",
});
assert.deepEqual(parsePlayerName("My Ek"), {
    valid: true,
    normalizedName: "My Ek",
    firstName: "My",
    lastName: "Ek",
});
for (const invalidName of ["", "Madonna", "M Ek", "My E", "My E Lund"]) {
    const parsed = parsePlayerName(invalidName);
    assert.equal(parsed.valid, false, invalidName);
    assert.equal(parsed.firstName, null);
    assert.equal(parsed.lastName, null);
}
assert.equal(
    playerNameSearchUrl(
        "/api/v1/players/search",
        "My/Ann",
        "Ek Lund & Öst",
    ),
    (
        "/api/v1/players/search"
        + "?first_name=My%2FAnn"
        + "&last_name=Ek%20Lund%20%26%20%C3%96st"
    ),
);
assert.deepEqual(
    [
        { status: "idle", players: [] },
        { status: "invalid", players: [] },
        { status: "loading", players: [] },
        { status: "empty", players: [] },
        {
            status: "failure",
            players: [],
            errorMessageKey: "errors.member_system.unavailable",
        },
        { status: "results", players: [{}, {}] },
    ].map((state) => playerNameSearchPresentation(state)),
    [
        {
            messageKey: "player_search.idle",
            parameters: {},
            tone: "quiet",
        },
        {
            messageKey: "player_search.invalid",
            parameters: {},
            tone: "failure",
        },
        {
            messageKey: "player_search.loading",
            parameters: {},
            tone: "quiet",
        },
        {
            messageKey: "player_search.empty",
            parameters: {},
            tone: "empty",
        },
        {
            messageKey: "errors.member_system.unavailable",
            parameters: {},
            tone: "failure",
        },
        {
            messageKey: "player_search.results",
            parameters: { count: 2 },
            tone: "quiet",
        },
    ],
);

{
    const searches = [];
    const states = [];
    const machine = new PlayerNameSearchState({
        search(names) {
            searches.push(names);
            return Promise.resolve({ players: [] });
        },
        onChange(state) {
            states.push(state.status);
        },
    });

    assert.deepEqual(searches, []);
    await Promise.resolve();
    assert.deepEqual(searches, []);

    await machine.submit("oneword");
    assert.deepEqual(searches, []);
    assert.equal(machine.state.status, "invalid");

    await machine.submit("  My   Ek Lund ");
    assert.deepEqual(searches, [
        { firstName: "My", lastName: "Ek Lund" },
    ]);
    assert.deepEqual(states, ["invalid", "loading", "empty"]);
    assert.equal(machine.state.normalizedName, "My Ek Lund");
}

{
    const first = deferred();
    const second = deferred();
    const machine = new PlayerNameSearchState({
        search({ firstName }) {
            return firstName === "My" ? first.promise : second.promise;
        },
    });

    const firstSubmission = machine.submit("My Ek");
    const secondSubmission = machine.submit("Bo Li");
    second.resolve({
        players: [{ player_id: 2, first_name: "Bo", last_name: "Li" }],
    });
    await secondSubmission;
    assert.equal(machine.state.status, "results");
    assert.equal(machine.state.players[0].player_id, 2);

    first.resolve({
        players: [{ player_id: 1, first_name: "My", last_name: "Ek" }],
    });
    await firstSubmission;
    assert.equal(machine.state.players[0].player_id, 2);
    assert.equal(machine.state.normalizedName, "Bo Li");
}

{
    const pending = deferred();
    const machine = new PlayerNameSearchState({
        search: async () => pending.promise,
    });

    const submission = machine.submit("My Ek");
    assert.equal(machine.state.status, "loading");
    machine.reset();
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.normalizedName, "");
    assert.deepEqual(machine.state.players, []);

    pending.resolve({
        players: [{ player_id: 1, first_name: "My", last_name: "Ek" }],
    });
    await submission;
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(machine.state.players, []);
}

{
    const selected = [];
    const players = [
        { player_id: 1, first_name: "My", last_name: "Ek" },
        { player_id: 2, first_name: "My", last_name: "Ek" },
    ];
    const machine = new PlayerNameSearchState({
        search: async () => ({ players }),
        onCandidateSelected(player) {
            selected.push(player);
        },
    });

    await machine.submit("My Ek");
    assert.equal(machine.state.status, "results");
    assert.deepEqual(selected, []);
    assert.equal(machine.selectCandidate(999), false);
    assert.equal(machine.selectCandidate(2), true);
    assert.deepEqual(selected, [players[1]]);
}

{
    const error = new Error("unavailable");
    error.messageKey = "errors.member_system.unavailable";
    const machine = new PlayerNameSearchState({
        search: async () => {
            throw error;
        },
    });

    await machine.submit("My Ek");
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.member_system.unavailable",
    );
}

console.log("player name search browser tests passed");
