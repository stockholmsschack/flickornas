import { TournamentSelectionState } from "./tournament-search-state.js";

function selectionValue(tournaments) {
    const selectedTournaments = Object.freeze([...tournaments]);
    return Object.freeze({
        tournaments: selectedTournaments,
        tournamentIds: Object.freeze(
            selectedTournaments.map(
                function tournamentId(tournament) {
                    return tournament.tournament_id;
                },
            ),
        ),
    });
}

function selectionSignature(value) {
    return JSON.stringify(value.tournamentIds);
}

function pickerConsumer({
    initialTournaments,
    selectionChanged,
    commit,
}) {
    if (!Array.isArray(initialTournaments)) {
        throw new TypeError("Picker initial tournaments must be an array");
    }
    if (
        typeof selectionChanged !== "function"
        || typeof commit !== "function"
    ) {
        throw new TypeError("Picker consumer callbacks are required");
    }
    return {
        initialTournaments,
        selectionChanged,
        commit,
    };
}

export function configurationTournamentConsumer({
    initialTournaments,
    selectionChanged,
    commit,
}) {
    return pickerConsumer({
        initialTournaments,
        selectionChanged,
        commit,
    });
}

export function runTournamentConsumer({
    initialTournaments,
    selectionChanged = function selectionChanged() {},
}) {
    return pickerConsumer({
        initialTournaments,
        selectionChanged,
        commit(value) {
            return value;
        },
    });
}

export class TournamentPicker {
    constructor({
        lookup,
        consumer,
        onChange = () => {},
    }) {
        this.consumer = consumer;
        this.onChange = onChange;
        this.selectionState = new TournamentSelectionState({
            lookup,
            initialTournaments: consumer.initialTournaments,
            onChange: this.#selectionChanged.bind(this),
        });
        this.value = selectionValue(
            this.selectionState.state.selectedTournaments,
        );
        this.valueSignature = selectionSignature(this.value);
    }

    selectSearchResult(searchResult) {
        return this.selectionState.selectSearchResult(searchResult);
    }

    verifyTournamentId(value) {
        return this.selectionState.verifyTournamentId(value);
    }

    clearStatus() {
        this.selectionState.clear();
    }

    removeTournament(tournamentId) {
        return this.selectionState.removeTournament(tournamentId);
    }

    removeAllTournaments() {
        return this.selectionState.removeAllTournaments();
    }

    replaceTournaments(tournaments) {
        this.selectionState.replaceTournaments(tournaments);
    }

    commit() {
        return this.consumer.commit(this.value);
    }

    dispose() {
        this.selectionState.dispose();
    }

    get state() {
        return this.selectionState.state;
    }

    #selectionChanged(state) {
        const value = selectionValue(state.selectedTournaments);
        const nextSignature = selectionSignature(value);
        this.value = value;
        if (nextSignature !== this.valueSignature) {
            this.valueSignature = nextSignature;
            this.consumer.selectionChanged(value);
        }
        this.onChange(state, value);
    }
}
