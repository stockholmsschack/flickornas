import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/tournament-search-state.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    chronologicalTournaments,
    MINIMUM_TOURNAMENT_SEARCH_LENGTH,
    tournamentLookupUrl,
    tournamentSearchPresentation,
    TournamentSelectionState,
    TournamentSearchState,
    tournamentSearchUrl,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

function controlledScheduler() {
    const pending = new Map();
    let nextId = 0;
    return {
        schedule(callback) {
            nextId += 1;
            pending.set(nextId, callback);
            return nextId;
        },
        cancel(id) {
            pending.delete(id);
        },
        runAll() {
            const callbacks = [...pending.values()];
            pending.clear();
            callbacks.forEach((callback) => callback());
        },
        get size() {
            return pending.size;
        },
    };
}

function deferred() {
    let resolve;
    const promise = new Promise((resolvePromise) => {
        resolve = resolvePromise;
    });
    return { promise, resolve };
}

async function settle() {
    await Promise.resolve();
    await Promise.resolve();
}

assert.equal(MINIMUM_TOURNAMENT_SEARCH_LENGTH, 3);
assert.deepEqual(
    chronologicalTournaments([
        { tournament_id: 30, start_date: "2026-03-01" },
        { tournament_id: 20, start_date: "2026-01-01" },
        { tournament_id: 10, start_date: "2026-03-01" },
    ]).map((tournament) => tournament.tournament_id),
    [20, 10, 30],
);
assert.equal(
    tournamentLookupUrl(
        6336,
        "/api/v1/tournaments/__tournament_id__",
    ),
    "/api/v1/tournaments/6336",
);

{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        initialTournaments: [
            {
                tournament_id: 300,
                name: "Later",
                start_date: "2026-03-01",
                end_date: "2026-03-02",
            },
            {
                tournament_id: 200,
                name: "Earlier",
                start_date: "2026-01-01",
                end_date: "2026-01-02",
            },
        ],
    });
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [200, 300],
    );
}
assert.equal(
    tournamentSearchUrl(
        "Flick DM/Öppen & final",
        "/api/v1/tournaments/search",
    ),
    "/api/v1/tournaments/search?q=Flick%20DM%2F%C3%96ppen%20%26%20final",
);
assert.deepEqual(
    [
        { status: "idle", query: "", tournaments: [] },
        { status: "idle", query: "ab", tournaments: [] },
        { status: "loading", query: "abc", tournaments: [] },
        { status: "empty", query: "abc", tournaments: [] },
        {
            status: "failure",
            query: "abc",
            tournaments: [],
            errorMessageKey: "errors.member_system.unavailable",
        },
        { status: "results", query: "abc", tournaments: [{}, {}] },
    ].map((state) => tournamentSearchPresentation(state)),
    [
        {
            messageKey: "tournament_search.idle",
            parameters: {},
            tone: "quiet",
        },
        {
            messageKey: "tournament_search.minimum",
            parameters: {},
            tone: "quiet",
        },
        {
            messageKey: "tournament_search.loading",
            parameters: {},
            tone: "quiet",
        },
        {
            messageKey: "tournament_search.empty",
            parameters: {},
            tone: "empty",
        },
        {
            messageKey: "errors.member_system.unavailable",
            parameters: {},
            tone: "failure",
        },
        {
            messageKey: "tournament_search.results",
            parameters: { count: 2 },
            tone: "quiet",
        },
    ],
);

{
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    let scheduledCallback;
    let scheduledDelay;

    globalThis.setTimeout = function browserSetTimeout(callback, delay) {
        assert.equal(this, globalThis);
        scheduledCallback = callback;
        scheduledDelay = delay;
        return 1;
    };
    globalThis.clearTimeout = function browserClearTimeout() {
        assert.equal(this, globalThis);
    };

    try {
        const machine = new TournamentSearchState({
            search: async () => ({ tournaments: [] }),
        });

        machine.setSearchText("was");
        assert.equal(scheduledDelay, 300);
        scheduledCallback();
        await settle();
        assert.equal(machine.state.status, "empty");
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        globalThis.clearTimeout = originalClearTimeout;
    }
}

{
    const scheduler = controlledScheduler();
    const searches = [];
    const states = [];
    const machine = new TournamentSearchState({
        search: async (query) => {
            searches.push(query);
            return { tournaments: [] };
        },
        onChange: (state) => states.push(state.status),
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText(" ab ");
    assert.equal(scheduler.size, 0);
    assert.equal(machine.state.status, "idle");
    machine.setSearchText(" abc ");
    machine.setSearchText(" abcd ");
    assert.equal(scheduler.size, 1);
    assert.deepEqual(searches, []);
    assert.equal(machine.state.status, "loading");
    scheduler.runAll();
    await settle();
    assert.deepEqual(searches, ["abcd"]);
    assert.equal(machine.state.status, "empty");
    assert.deepEqual(states, ["idle", "loading", "loading", "empty"]);

    machine.setSearchText("another");
    assert.equal(scheduler.size, 1);
    machine.clear();
    assert.equal(scheduler.size, 0);
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.searchText, "");
    assert.deepEqual(machine.state.tournaments, []);
}

{
    const scheduler = controlledScheduler();
    const first = deferred();
    const second = deferred();
    const responses = new Map([
        ["first", first.promise],
        ["second", second.promise],
    ]);
    const machine = new TournamentSearchState({
        search: (query) => responses.get(query),
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("first");
    scheduler.runAll();
    machine.setSearchText("second");
    scheduler.runAll();
    second.resolve({
        tournaments: [{ tournament_id: 2, name: "New result" }],
    });
    await settle();
    assert.equal(machine.state.status, "results");
    assert.equal(machine.state.tournaments[0].tournament_id, 2);

    first.resolve({
        tournaments: [{ tournament_id: 1, name: "Stale result" }],
    });
    await settle();
    assert.equal(machine.state.tournaments[0].tournament_id, 2);
    assert.equal(machine.state.searchText, "second");
}

{
    const scheduler = controlledScheduler();
    const nextResults = deferred();
    let searchCount = 0;
    const previousTournaments = [
        { tournament_id: 1, name: "Previous result" },
    ];
    const machine = new TournamentSearchState({
        search: async () => {
            searchCount += 1;
            if (searchCount === 1) {
                return { tournaments: previousTournaments };
            }
            return nextResults.promise;
        },
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("first");
    scheduler.runAll();
    await settle();
    assert.equal(machine.state.status, "results");

    machine.setSearchText("second");
    assert.equal(machine.state.status, "loading");
    assert.equal(machine.state.tournaments, previousTournaments);

    scheduler.runAll();
    assert.equal(machine.state.status, "loading");
    assert.equal(machine.state.tournaments, previousTournaments);

    nextResults.resolve({ tournaments: [] });
    await settle();
    assert.equal(machine.state.status, "empty");
    assert.deepEqual(machine.state.tournaments, []);
}

{
    const scheduler = controlledScheduler();
    const machine = new TournamentSearchState({
        search: async () => {
            const error = new Error("unavailable");
            error.messageKey = "errors.member_system.unavailable";
            throw error;
        },
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("failure");
    scheduler.runAll();
    await settle();
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.member_system.unavailable",
    );
}

{
    const lookupResponse = deferred();
    const lookupIds = [];
    const states = [];
    const machine = new TournamentSelectionState({
        lookup(tournamentId) {
            lookupIds.push(tournamentId);
            return lookupResponse.promise;
        },
        onChange: (state) => states.push(state.status),
    });

    const selection = machine.selectSearchResult({
        tournament_id: 6336,
        name: "Unverified search name",
        matching_groups: [
            { group_id: 8101, name: "Unverified search group" },
        ],
    });

    assert.deepEqual(lookupIds, [6336]);
    assert.equal(machine.state.status, "verifying");
    assert.equal(machine.state.verifiedTournament, null);

    lookupResponse.resolve({
        tournament: {
            tournament_id: 6336,
            name: "Canonical tournament name",
            start_date: "2026-03-07",
            end_date: "2026-03-08",
            processable_groups: [
                {
                    group_id: 8102,
                    name: "Canonical group",
                    klass: "2014",
                },
            ],
        },
    });
    await selection;

    assert.deepEqual(states, ["verifying", "verified"]);
    assert.deepEqual(machine.state.verifiedTournament, {
        tournament_id: 6336,
        name: "Canonical tournament name",
        start_date: "2026-03-07",
        end_date: "2026-03-08",
        processable_groups: [
            {
                group_id: 8102,
                name: "Canonical group",
                klass: "2014",
            },
        ],
    });
    assert.deepEqual(
        machine.state.selectedTournaments,
        [machine.state.verifiedTournament],
    );
}

{
    const lookupIds = [];
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => {
            lookupIds.push(tournamentId);
            return {
                tournament: {
                    tournament_id: tournamentId,
                    name: "Verified pasted tournament",
                    start_date: "2026-04-01",
                    end_date: "2026-04-02",
                    processable_groups: [
                        { group_id: 4, name: "Flickor", klass: "F" },
                    ],
                },
            };
        },
    });

    await machine.verifyTournamentId(" 7447 ");
    assert.deepEqual(lookupIds, [7447]);
    assert.equal(machine.state.status, "verified");
    assert.equal(machine.state.verifiedTournament.tournament_id, 7447);
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [7447],
    );
}

{
    let lookupCount = 0;
    const machine = new TournamentSelectionState({
        lookup: async () => {
            lookupCount += 1;
            return {};
        },
    });

    await machine.verifyTournamentId("not-an-id");
    assert.equal(lookupCount, 0);
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.verifiedTournament, null);
    assert.equal(
        machine.state.errorMessageKey,
        "errors.tournament_lookup.invalid_input",
    );

    await machine.selectSearchResult({
        group_id: 8101,
        name: "Group-only search result",
    });
    assert.equal(lookupCount, 0);
    assert.equal(machine.state.verifiedTournament, null);
}

{
    const machine = new TournamentSelectionState({
        lookup: async () => ({
            tournament: {
                tournament_id: 9999,
                name: "Mismatched tournament",
                start_date: "2026-04-01",
                end_date: "2026-04-02",
                processable_groups: [
                    { group_id: 4, name: "Flickor", klass: "F" },
                ],
            },
        }),
    });

    await machine.verifyTournamentId(6336);
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.verifiedTournament, null);
}

{
    const machine = new TournamentSelectionState({
        lookup: async () => {
            const error = new Error("unresolvable");
            error.messageKey = "errors.tournament_lookup.unresolvable";
            throw error;
        },
    });

    await machine.verifyTournamentId(6336);
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.verifiedTournament, null);
    assert.equal(
        machine.state.errorMessageKey,
        "errors.tournament_lookup.unresolvable",
    );
}

{
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
    const lookupIds = [];
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => {
            lookupIds.push(tournamentId);
            return { tournament: tournaments.get(tournamentId) };
        },
    });

    await machine.verifyTournamentId(300);
    await machine.verifyTournamentId(200);
    await machine.verifyTournamentId(100);
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [200, 100, 300],
    );

    await machine.verifyTournamentId(100);
    assert.deepEqual(lookupIds, [300, 200, 100, 100]);
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.tournament_selection.duplicate",
    );
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [200, 100, 300],
    );

    assert.equal(machine.removeTournament(100), true);
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [200, 300],
    );
    assert.equal(machine.removeTournament(999), false);
    assert.equal(machine.removeAllTournaments(), true);
    assert.deepEqual(machine.state.selectedTournaments, []);
    assert.equal(machine.removeAllTournaments(), false);

    machine.clear();
    assert.deepEqual(
        machine.state.selectedTournaments.map(
            (tournament) => tournament.tournament_id,
        ),
        [],
    );
}

{
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => ({
            tournament: {
                tournament_id: tournamentId,
                name: "Invalid date tournament",
                start_date: "2026-02-30",
                end_date: "2026-03-01",
                processable_groups: [
                    { group_id: 1, name: "Flickor", klass: "F" },
                ],
            },
        }),
    });

    await machine.verifyTournamentId(123);
    assert.equal(machine.state.status, "failure");
    assert.deepEqual(machine.state.selectedTournaments, []);
}

process.stdout.write("tournament search browser state tests passed\n");
