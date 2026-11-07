import assert from "node:assert/strict";

const { generationInputsMatch } = await import(
    "../../flickornas_standings/web/static/js/generation-input-state.js"
);

const operation = {
    configuration_revision: 7,
    effective_year: 2026,
    layout: "auto",
    tournament_ids: [6336, 6544],
};

assert.equal(generationInputsMatch(operation, {
    configurationRevision: 7,
    effectiveYear: 2026,
    layout: "auto",
    tournamentIds: [6336, 6544],
}), true);
assert.equal(generationInputsMatch(operation, {
    configurationRevision: 7,
    effectiveYear: 2025,
    layout: "auto",
    tournamentIds: [6336, 6544],
}), false);
assert.equal(generationInputsMatch(operation, {
    configurationRevision: 7,
    effectiveYear: 2026,
    layout: "landscape",
    tournamentIds: [6336, 6544],
}), false);
assert.equal(generationInputsMatch(operation, {
    configurationRevision: 7,
    effectiveYear: 2026,
    layout: "auto",
    tournamentIds: [6544, 6336],
}), false);

// Saved rendering changes invalidate a completed run even with the same selections.
const inputs = {
    configurationRevision: 8,
    effectiveYear: 2026,
    layout: "auto",
    tournamentIds: [6336, 6544],
};
assert.equal(generationInputsMatch(operation, inputs), false);
assert.equal(generationInputsMatch({ ...operation, configuration_revision: 8 }, inputs), true);
// Legacy operation records cannot establish that the configuration is unchanged.
assert.equal(generationInputsMatch({ ...operation, configuration_revision: null }, inputs), false);
assert.equal(generationInputsMatch({ ...operation, configuration_revision: undefined }, inputs), false);
