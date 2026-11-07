function normalizedSearchText(value) {
    return typeof value === "string"
        ? value.trim().toLocaleLowerCase()
        : "";
}

function validClub(club) {
    return (
        club !== null
        && typeof club === "object"
        && Number.isInteger(club.club_id)
        && club.club_id > 0
        && typeof club.name === "string"
        && club.name.trim() !== ""
    );
}

function canonicalClub(club) {
    const canonical = {
        club_id: club.club_id,
        name: club.name.trim(),
    };
    return canonical;
}

function canonicalInitialClub(initialValue) {
    if (initialValue === null) {
        return null;
    }
    if (!validClub(initialValue)) {
        throw new TypeError(
            "Club selector initialValue must be a canonical club",
        );
    }
    return canonicalClub(initialValue);
}

function resultStatus(clubs) {
    return clubs.length > 0 ? "results" : "empty";
}

function searchResultStatus(clubs, searchText) {
    return normalizedSearchText(searchText) === ""
        ? "idle"
        : resultStatus(clubs);
}

function filteredStatus(currentStatus, clubs, searchText) {
    if (currentStatus === "loading" || currentStatus === "failure") {
        return currentStatus;
    }
    return searchResultStatus(clubs, searchText);
}

export function filterClubs(clubs, searchText) {
    const query = normalizedSearchText(searchText);
    if (query === "") {
        return [];
    }
    return clubs.filter(
        (club) => club.name.toLocaleLowerCase().includes(query),
    );
}

export function clubSelectorPresentation(state) {
    switch (state.status) {
        case "idle":
            return null;
        case "loading":
            return {
                messageKey: "club_search.loading",
                parameters: {},
                tone: "quiet",
            };
        case "results":
            return {
                messageKey: "club_search.results",
                parameters: { count: state.filteredClubs.length },
                tone: "quiet",
            };
        case "empty":
            return {
                messageKey: (
                    state.clubs.length === 0
                        ? "club_search.none_available"
                        : "club_search.empty"
                ),
                parameters: {},
                tone: "empty",
            };
        case "failure":
            return {
                messageKey: state.errorMessageKey,
                parameters: {},
                tone: "failure",
            };
        default:
            throw new Error(`Unknown club selector state: ${state.status}`);
    }
}

export class ClubSelectorState {
    constructor({
        load,
        initialValue = null,
        onChange = () => {},
        onSelectionChange = () => {},
    }) {
        this.loadClubs = load;
        this.onChange = onChange;
        this.onSelectionChange = onSelectionChange;
        this.requestVersion = 0;
        const verifiedClub = canonicalInitialClub(initialValue);
        this.state = {
            status: "loading",
            searchText: verifiedClub?.name ?? "",
            clubs: [],
            filteredClubs: [],
            verifiedClub,
            errorMessageKey: null,
        };
    }

    async load() {
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        this.#transition({
            ...this.state,
            status: "loading",
            errorMessageKey: null,
        });
        try {
            const response = await this.loadClubs();
            if (requestVersion !== this.requestVersion) {
                return;
            }
            if (
                !Array.isArray(response?.clubs)
                || !response.clubs.every(validClub)
            ) {
                throw new Error("Invalid club list response");
            }
            const clubs = response.clubs.map(canonicalClub);
            let status = "idle";
            let filteredClubs = [];
            if (this.state.verifiedClub === null) {
                filteredClubs = filterClubs(clubs, this.state.searchText);
                status = searchResultStatus(
                    filteredClubs,
                    this.state.searchText,
                );
            }
            this.#transition({
                ...this.state,
                status,
                clubs,
                filteredClubs,
                errorMessageKey: null,
            });
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition({
                ...this.state,
                status: "failure",
                clubs: [],
                filteredClubs: [],
                errorMessageKey: (
                    error?.messageKey
                    ?? "errors.member_system.unavailable"
                ),
            });
        }
    }

    setSearchText(searchText) {
        if (this.state.verifiedClub !== null) {
            return;
        }
        const value = typeof searchText === "string" ? searchText : "";
        const filteredClubs = filterClubs(this.state.clubs, value);
        this.#transition({
            ...this.state,
            status: filteredStatus(
                this.state.status,
                filteredClubs,
                value,
            ),
            searchText: value,
            filteredClubs,
        });
    }

    reset() {
        this.#transition({
            ...this.state,
            status: filteredStatus(this.state.status, [], ""),
            searchText: "",
            filteredClubs: [],
            verifiedClub: null,
        });
        this.onSelectionChange(null);
    }

    selectClub(clubId) {
        const club = this.state.filteredClubs.find(
            (candidate) => candidate.club_id === clubId,
        );
        if (club === undefined) {
            return false;
        }
        this.#transition({
            ...this.state,
            status: "idle",
            searchText: club.name,
            filteredClubs: [],
            verifiedClub: club,
        });
        this.onSelectionChange(club);
        return true;
    }

    #transition(state) {
        this.state = state;
        this.onChange(this.state);
    }
}
