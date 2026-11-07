export function parsePlayerName(value) {
    const nameText = typeof value === "string" ? value : "";
    const normalizedName = nameText.trim().replace(/\s+/gu, " ");
    const words = normalizedName === "" ? [] : normalizedName.split(" ");
    const valid = (
        words.length >= 2
        && words.every(function hasAtLeastTwoCharacters(word) {
            return Array.from(word).length >= 2;
        })
    );

    if (!valid) {
        return {
            valid: false,
            normalizedName,
            firstName: null,
            lastName: null,
        };
    }

    return {
        valid: true,
        normalizedName,
        firstName: words[0],
        lastName: words.slice(1).join(" "),
    };
}

export function playerNameSearchUrl(endpoint, firstName, lastName) {
    return (
        `${endpoint}?first_name=${encodeURIComponent(firstName)}`
        + `&last_name=${encodeURIComponent(lastName)}`
    );
}

export function playerNameSearchPresentation(state) {
    switch (state.status) {
        case "idle":
            return {
                messageKey: "player_search.idle",
                parameters: {},
                tone: "quiet",
            };
        case "invalid":
            return {
                messageKey: "player_search.invalid",
                parameters: {},
                tone: "failure",
            };
        case "loading":
            return {
                messageKey: "player_search.loading",
                parameters: {},
                tone: "quiet",
            };
        case "empty":
            return {
                messageKey: "player_search.empty",
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
                messageKey: "player_search.results",
                parameters: { count: state.players.length },
                tone: "quiet",
            };
        default:
            throw new Error(`Unknown player search state: ${state.status}`);
    }
}

export class PlayerNameSearchState {
    constructor({
        search,
        onChange = () => {},
        onCandidateSelected = () => {},
    }) {
        this.search = search;
        this.onChange = onChange;
        this.onCandidateSelected = onCandidateSelected;
        this.requestVersion = 0;
        this.state = {
            status: "idle",
            normalizedName: "",
            firstName: null,
            lastName: null,
            players: [],
            errorMessageKey: null,
        };
    }

    async submit(nameText) {
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        const parsedName = parsePlayerName(nameText);
        if (!parsedName.valid) {
            this.#transition("invalid", parsedName);
            return;
        }

        this.#transition("loading", parsedName, this.state.players);
        try {
            const response = await this.search({
                firstName: parsedName.firstName,
                lastName: parsedName.lastName,
            });
            if (requestVersion !== this.requestVersion) {
                return;
            }
            if (!Array.isArray(response?.players)) {
                throw new Error("Invalid player search response");
            }

            this.#transition(
                response.players.length > 0 ? "results" : "empty",
                parsedName,
                response.players,
            );
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                parsedName,
                [],
                error?.messageKey ?? "errors.member_system.unavailable",
            );
        }
    }

    reset() {
        this.requestVersion += 1;
        this.#transition("idle", parsePlayerName(""));
    }

    selectCandidate(playerId) {
        const player = this.state.players.find(
            (candidate) => candidate.player_id === playerId,
        );
        if (player === undefined) {
            return false;
        }

        this.onCandidateSelected(player);
        return true;
    }

    #transition(
        status,
        parsedName,
        players = [],
        errorMessageKey = null,
    ) {
        this.state = {
            status,
            normalizedName: parsedName.normalizedName,
            firstName: parsedName.firstName,
            lastName: parsedName.lastName,
            players,
            errorMessageKey,
        };
        this.onChange(this.state);
    }
}
