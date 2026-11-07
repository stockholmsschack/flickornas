function validPlayer(player) {
    return (
        player !== null
        && typeof player === "object"
        && Number.isInteger(player.player_id)
        && player.player_id > 0
        && typeof player.first_name === "string"
        && player.first_name.trim() !== ""
        && typeof player.last_name === "string"
        && player.last_name.trim() !== ""
    );
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

function canonicalPlayer(player) {
    return {
        ...player,
        first_name: player.first_name.trim(),
        last_name: player.last_name.trim(),
    };
}

function canonicalClub(club) {
    return {
        club_id: club.club_id,
        name: club.name.trim(),
    };
}

function canonicalOverrides(values) {
    return values.map(function initialOverride(value) {
        return {
            player: {
                player_id: value.player_id,
                first_name: value.first_name ?? null,
                last_name: value.last_name ?? null,
                display_name: value.display_name ?? null,
            },
            club: {
                club_id: value.club_id ?? null,
                name: value.club_name,
            },
        };
    });
}

export function playerFullName(player) {
    if (
        typeof player.display_name === "string"
        && player.display_name.trim() !== ""
    ) {
        return player.display_name.trim();
    }
    if (
        typeof player.first_name !== "string"
        || typeof player.last_name !== "string"
    ) {
        return null;
    }
    return `${player.first_name} ${player.last_name}`;
}

export class PlayerOverrideEditorState {
    constructor({ initialOverrides = [], onChange = () => {} } = {}) {
        this.onChange = onChange;
        this.state = {
            selectedPlayer: null,
            selectedClub: null,
            overrides: canonicalOverrides(initialOverrides),
        };
    }

    selectPlayer(player) {
        if (!validPlayer(player)) {
            return false;
        }
        this.#transition({
            ...this.state,
            selectedPlayer: canonicalPlayer(player),
        });
        return true;
    }

    clearPlayerSelection() {
        this.#transition({
            ...this.state,
            selectedPlayer: null,
        });
    }

    selectClub(club) {
        if (!validClub(club)) {
            return false;
        }
        this.#transition({
            ...this.state,
            selectedClub: canonicalClub(club),
        });
        return true;
    }

    clearClubSelection() {
        this.#transition({
            ...this.state,
            selectedClub: null,
        });
    }

    addOverride() {
        const player = this.state.selectedPlayer;
        const club = this.state.selectedClub;
        if (player === null || club === null) {
            return { status: "failure" };
        }

        const existingIndex = this.state.overrides.findIndex(
            function matchingPlayer(override) {
                return override.player.player_id === player.player_id;
            },
        );
        if (existingIndex === -1) {
            const override = { player, club };
            this.#transition({
                ...this.state,
                overrides: [...this.state.overrides, override],
            });
            return { status: "added", override };
        }

        const existing = this.state.overrides[existingIndex];
        if (existing.club.club_id === club.club_id) {
            return { status: "unchanged", override: existing };
        }

        const replacement = { player, club };
        const overrides = this.state.overrides.slice();
        overrides[existingIndex] = replacement;
        this.#transition({ ...this.state, overrides });
        return {
            status: "replaced",
            override: replacement,
            previousClub: existing.club,
        };
    }

    removeOverride(playerId) {
        const existing = this.state.overrides.find(
            function matchingPlayer(override) {
                return override.player.player_id === playerId;
            },
        );
        if (existing === undefined) {
            return { status: "failure" };
        }
        this.#transition({
            ...this.state,
            overrides: this.state.overrides.filter(
                function otherPlayer(override) {
                    return override.player.player_id !== playerId;
                },
            ),
        });
        return { status: "removed", overrides: [existing] };
    }

    removeAllOverrides() {
        if (this.state.overrides.length === 0) {
            return { status: "failure" };
        }
        const removed = this.state.overrides;
        this.#transition({ ...this.state, overrides: [] });
        return { status: "removed_all", overrides: removed };
    }

    replaceOverrides(overrides) {
        this.#transition({
            ...this.state,
            overrides: canonicalOverrides(overrides),
        });
    }

    value() {
        return Object.fromEntries(
            this.state.overrides.map(function overrideEntry(override) {
                return [
                    String(override.player.player_id),
                    override.club.name,
                ];
            }),
        );
    }

    names() {
        return Object.fromEntries(
            this.state.overrides.flatMap(function playerNameEntry(override) {
                const name = playerFullName(override.player);
                return name === null
                    ? []
                    : [[String(override.player.player_id), name]];
            }),
        );
    }

    draftValue() {
        return this.state.overrides.map(function draftOverride(override) {
            return {
                player_id: override.player.player_id,
                first_name: override.player.first_name,
                last_name: override.player.last_name,
                display_name: override.player.display_name ?? null,
                club_id: override.club.club_id,
                club_name: override.club.name,
            };
        });
    }

    #transition(state) {
        this.state = state;
        this.onChange(this.state);
    }
}
