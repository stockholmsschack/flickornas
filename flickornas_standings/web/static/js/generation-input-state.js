export function generationInputsMatch(operation, inputs) {
    if (
        !Number.isInteger(operation.configuration_revision)
        || operation.configuration_revision !== inputs.configurationRevision
        || operation.effective_year !== inputs.effectiveYear
        || operation.layout !== inputs.layout
        || operation.tournament_ids.length !== inputs.tournamentIds.length
    ) {
        return false;
    }
    return operation.tournament_ids.every(
        (tournamentId, index) => tournamentId === inputs.tournamentIds[index],
    );
}
