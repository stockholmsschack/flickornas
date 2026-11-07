export const MINIMUM_TOURNAMENT_SEARCH_LENGTH = 3;
export const TOURNAMENT_SEARCH_DEBOUNCE_MS = 300;
export const TOURNAMENT_ID_URL_TOKEN = "__tournament_id__";

function scheduleWithGlobalTimer(callback, delay) {
    return globalThis.setTimeout(callback, delay);
}

function cancelGlobalTimer(timer) {
    globalThis.clearTimeout(timer);
}

export function tournamentSearchUrl(query, endpoint) {
    return `${endpoint}?q=${encodeURIComponent(query)}`;
}

export function tournamentLookupUrl(tournamentId, endpointTemplate) {
    return endpointTemplate.replace(
        TOURNAMENT_ID_URL_TOKEN,
        encodeURIComponent(tournamentId),
    );
}

export function tournamentSearchPresentation(state) {
    switch (state.status) {
        case "idle":
            return {
                messageKey: state.query.length === 0
                    ? "tournament_search.idle"
                    : "tournament_search.minimum",
                parameters: {},
                tone: "quiet",
            };
        case "loading":
            return {
                messageKey: "tournament_search.loading",
                parameters: {},
                tone: "quiet",
            };
        case "empty":
            return {
                messageKey: "tournament_search.empty",
                parameters: {},
                tone: "empty",
            };
        case "failure":
            return {
                messageKey: state.errorMessageKey,
                parameters: {},
                tone: "failure",
            };
        case "results":
            return {
                messageKey: "tournament_search.results",
                parameters: { count: state.tournaments.length },
                tone: "quiet",
            };
        default:
            throw new Error(`Unknown tournament search state: ${state.status}`);
    }
}

function validPositiveInteger(value) {
    return Number.isSafeInteger(value) && value > 0;
}

function canonicalDate(value) {
    if (
        typeof value !== "string"
        || !/^\d{4}-\d{2}-\d{2}$/.test(value)
    ) {
        throw new Error("Invalid canonical tournament date");
    }

    const parsed = new Date(`${value}T00:00:00Z`);
    if (
        Number.isNaN(parsed.getTime())
        || parsed.toISOString().slice(0, 10) !== value
    ) {
        throw new Error("Invalid canonical tournament date");
    }
    return value;
}

function canonicalTournamentGroup(group) {
    if (
        !group
        || !validPositiveInteger(group.group_id)
        || typeof group.name !== "string"
        || group.name.trim().length === 0
        || typeof group.klass !== "string"
        || group.klass.trim().length === 0
    ) {
        throw new Error("Invalid canonical tournament group");
    }

    return {
        group_id: group.group_id,
        name: group.name,
        klass: group.klass,
    };
}

function canonicalTournament(tournament, expectedTournamentId) {
    if (
        !tournament
        || !validPositiveInteger(tournament.tournament_id)
        || tournament.tournament_id !== expectedTournamentId
        || typeof tournament.name !== "string"
        || tournament.name.trim().length === 0
        || !Array.isArray(tournament.processable_groups)
        || tournament.processable_groups.length === 0
    ) {
        throw new Error("Invalid canonical tournament");
    }

    const startDate = canonicalDate(tournament.start_date);
    const endDate = canonicalDate(tournament.end_date);
    if (endDate < startDate) {
        throw new Error("Invalid canonical tournament date range");
    }

    return {
        tournament_id: tournament.tournament_id,
        name: tournament.name,
        start_date: startDate,
        end_date: endDate,
        processable_groups: tournament.processable_groups.map(
            canonicalTournamentGroup,
        ),
    };
}

export function chronologicalTournaments(tournaments) {
    return [...tournaments].sort(function compareChronologically(left, right) {
        return (
            left.start_date.localeCompare(right.start_date)
            || left.tournament_id - right.tournament_id
        );
    });
}

export class TournamentSearchState {
    constructor({
        search,
        onChange = () => {},
        schedule = scheduleWithGlobalTimer,
        cancel = cancelGlobalTimer,
        debounceMs = TOURNAMENT_SEARCH_DEBOUNCE_MS,
    }) {
        this.search = search;
        this.onChange = onChange;
        this.schedule = schedule;
        this.cancel = cancel;
        this.debounceMs = debounceMs;
        this.timer = null;
        this.requestVersion = 0;
        this.state = {
            status: "idle",
            searchText: "",
            query: "",
            tournaments: [],
            errorMessageKey: null,
            problems: [],
        };
    }

    setSearchText(searchText) {
        const query = searchText.trim();
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        this.#cancelPendingSearch();

        if (query.length < MINIMUM_TOURNAMENT_SEARCH_LENGTH) {
            this.#transition("idle", searchText, query);
            return;
        }

        this.#transition(
            "loading",
            searchText,
            query,
            this.state.tournaments,
        );
        this.timer = this.schedule(() => {
            this.timer = null;
            this.#performSearch(query, searchText, requestVersion);
        }, this.debounceMs);
    }

    clear() {
        this.setSearchText("");
    }

    dispose() {
        this.requestVersion += 1;
        this.#cancelPendingSearch();
    }

    #cancelPendingSearch() {
        if (this.timer !== null) {
            this.cancel(this.timer);
            this.timer = null;
        }
    }

    #transition(
        status,
        searchText,
        query,
        tournaments = [],
        errorMessageKey = null,
        problems = [],
    ) {
        this.state = {
            status,
            searchText,
            query,
            tournaments,
            errorMessageKey,
            problems,
        };
        this.onChange(this.state);
    }

    async #performSearch(query, searchText, requestVersion) {
        try {
            const response = await this.search(query);
            if (requestVersion !== this.requestVersion) {
                return;
            }

            const tournaments = response.tournaments ?? [];
            this.#transition(
                tournaments.length > 0 ? "results" : "empty",
                searchText,
                query,
                tournaments,
            );
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                searchText,
                query,
                [],
                error?.messageKey ?? "errors.member_system.unavailable",
                error?.problems ?? [],
            );
        }
    }
}

export class TournamentSelectionState {
    constructor({
        lookup,
        onChange = () => {},
        initialTournaments = [],
    }) {
        this.lookup = lookup;
        this.onChange = onChange;
        this.requestVersion = 0;
        this.state = {
            status: "idle",
            verifiedTournament: null,
            selectedTournaments: chronologicalTournaments(
                initialTournaments.map(function initialTournament(tournament) {
                    const tournamentId = tournament?.tournament_id;
                    if (
                        !validPositiveInteger(tournamentId)
                        || typeof tournament.name !== "string"
                        || tournament.name.trim().length === 0
                    ) {
                        throw new Error("Invalid initial tournament");
                    }
                    return {
                        tournament_id: tournamentId,
                        name: tournament.name,
                        start_date: canonicalDate(tournament.start_date),
                        end_date: canonicalDate(tournament.end_date),
                    };
                }),
            ),
            errorMessageKey: null,
            problems: [],
        };
    }

    selectSearchResult(searchResult) {
        return this.verifyTournamentId(searchResult?.tournament_id);
    }

    async verifyTournamentId(value) {
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        const tournamentId = Number(value);

        if (
            !validPositiveInteger(tournamentId)
            || String(tournamentId) !== String(value).trim()
        ) {
            this.#transition(
                "failure",
                null,
                "errors.tournament_lookup.invalid_input",
            );
            return;
        }

        this.#transition("verifying");
        try {
            const response = await this.lookup(tournamentId);
            if (requestVersion !== this.requestVersion) {
                return;
            }
            const tournament = canonicalTournament(
                response?.tournament,
                tournamentId,
            );
            if (
                this.state.selectedTournaments.some(
                    function hasSameTournamentId(selected) {
                        return (
                            selected.tournament_id
                            === tournament.tournament_id
                        );
                    },
                )
            ) {
                this.#transition(
                    "failure",
                    null,
                    "errors.tournament_selection.duplicate",
                );
                return;
            }

            this.#transition("verified", tournament, null, [
                ...this.state.selectedTournaments,
                tournament,
            ]);
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                null,
                error?.messageKey ?? "errors.member_system.unavailable",
                this.state.selectedTournaments,
                error?.problems ?? [],
            );
        }
    }

    clear() {
        this.requestVersion += 1;
        this.#transition("idle");
    }

    removeTournament(tournamentId) {
        const remaining = this.state.selectedTournaments.filter(
            (tournament) => tournament.tournament_id !== tournamentId,
        );
        if (remaining.length === this.state.selectedTournaments.length) {
            return false;
        }

        this.requestVersion += 1;
        this.#transition("idle", null, null, remaining);
        return true;
    }

    removeAllTournaments() {
        if (this.state.selectedTournaments.length === 0) {
            return false;
        }

        this.requestVersion += 1;
        this.#transition("idle", null, null, []);
        return true;
    }

    replaceTournaments(tournaments) {
        this.requestVersion += 1;
        this.#transition("idle", null, null, tournaments);
    }

    dispose() {
        this.requestVersion += 1;
    }

    #transition(
        status,
        verifiedTournament = null,
        errorMessageKey = null,
        selectedTournaments = this.state.selectedTournaments,
        problems = [],
    ) {
        this.state = {
            status,
            verifiedTournament,
            selectedTournaments: chronologicalTournaments(
                selectedTournaments,
            ),
            errorMessageKey,
            problems,
        };
        this.onChange(this.state);
    }
}
