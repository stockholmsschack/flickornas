import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../flickornas_standings/web/static/js/club-selector-state.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    ClubSelectorState,
    clubSelectorPresentation,
    filterClubs,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

const clubs = [
    { club_id: 10, name: "Stockholms SK" },
    { club_id: 20, name: "Farsta SK" },
    { club_id: 30, name: "Wasa SK" },
];

assert.deepEqual(filterClubs(clubs, ""), []);
assert.deepEqual(filterClubs(clubs, "   "), []);
assert.deepEqual(filterClubs(clubs, "  SK  "), clubs);
assert.deepEqual(filterClubs(clubs, "sta"), [clubs[1]]);
assert.deepEqual(filterClubs(clubs, "WASA"), [clubs[2]]);

assert.deepEqual(
    clubSelectorPresentation({
        status: "idle",
        clubs,
        filteredClubs: [],
    }),
    null,
);
assert.deepEqual(
    clubSelectorPresentation({
        status: "loading",
        clubs: [],
        filteredClubs: [],
    }),
    {
        messageKey: "club_search.loading",
        parameters: {},
        tone: "quiet",
    },
);
assert.deepEqual(
    clubSelectorPresentation({
        status: "results",
        clubs,
        filteredClubs: clubs.slice(0, 2),
    }),
    {
        messageKey: "club_search.results",
        parameters: { count: 2 },
        tone: "quiet",
    },
);
assert.equal(
    clubSelectorPresentation({
        status: "empty",
        clubs,
        filteredClubs: [],
    }).messageKey,
    "club_search.empty",
);
assert.equal(
    clubSelectorPresentation({
        status: "empty",
        clubs: [],
        filteredClubs: [],
    }).messageKey,
    "club_search.none_available",
);
assert.deepEqual(
    clubSelectorPresentation({
        status: "failure",
        errorMessageKey: "errors.member_system.unavailable",
    }),
    {
        messageKey: "errors.member_system.unavailable",
        parameters: {},
        tone: "failure",
    },
);

{
    const selections = [];
    const machine = new ClubSelectorState({
        load: async () => ({ clubs }),
        onSelectionChange(club) {
            selections.push(club);
        },
    });

    assert.equal(machine.state.status, "loading");
    await machine.load();
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(machine.state.filteredClubs, []);
    assert.equal(machine.state.verifiedClub, null);

    machine.setSearchText("was");
    assert.equal(machine.state.status, "results");
    assert.deepEqual(machine.state.filteredClubs, [clubs[2]]);
    assert.equal(machine.state.verifiedClub, null);
    assert.deepEqual(selections, []);

    machine.setSearchText("missing");
    assert.equal(machine.state.status, "empty");
    assert.equal(machine.selectClub(30), false);
    assert.equal(machine.state.verifiedClub, null);

    machine.setSearchText("was");
    assert.equal(machine.selectClub(30), true);
    assert.deepEqual(machine.state.verifiedClub, clubs[2]);
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.searchText, "Wasa SK");
    assert.deepEqual(machine.state.filteredClubs, []);
    assert.deepEqual(selections, [clubs[2]]);

    machine.setSearchText("free text");
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.searchText, "Wasa SK");
    assert.deepEqual(machine.state.verifiedClub, clubs[2]);
    assert.deepEqual(selections, [clubs[2]]);

    machine.reset();
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.searchText, "");
    assert.deepEqual(machine.state.filteredClubs, []);
    assert.equal(machine.state.verifiedClub, null);
    assert.deepEqual(selections, [clubs[2], null]);
}

{
    const initialClub = { club_id: 30, name: " Wasa SK " };
    const machine = new ClubSelectorState({
        initialValue: initialClub,
        load: async () => ({ clubs }),
    });

    assert.deepEqual(machine.state.verifiedClub, clubs[2]);
    assert.equal(machine.state.searchText, "Wasa SK");
    await machine.load();
    assert.deepEqual(machine.state.verifiedClub, clubs[2]);
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(machine.state.filteredClubs, []);
}

assert.throws(
    () => new ClubSelectorState({
        initialValue: { club_id: null, name: "Not canonical" },
        load: async () => ({ clubs }),
    }),
    /canonical club/,
);

{
    const machine = new ClubSelectorState({
        load: async () => ({ clubs: [] }),
    });
    await machine.load();
    assert.equal(machine.state.status, "idle");

    machine.setSearchText("club");
    assert.equal(machine.state.status, "empty");
}

{
    const error = new Error("unavailable");
    error.messageKey = "errors.member_system.unavailable";
    const machine = new ClubSelectorState({
        load: async () => {
            throw error;
        },
    });
    await machine.load();
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.member_system.unavailable",
    );
}

{
    const machine = new ClubSelectorState({
        load: async () => ({
            clubs: [{ club_id: null, name: "Not canonical" }],
        }),
    });
    await machine.load();
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.verifiedClub, null);
}
