import { html, nothing, render } from "./lit-html.js";
import { translate } from "./locale.js";
import {
    playerNameSearchPresentation,
    PlayerNameSearchState,
    playerNameSearchUrl,
} from "./player-name-search-state.js";

let selectorInstance = 0;

function resultDetail(translations, labelKey, value) {
    if (value === null || value === undefined || value === "") {
        return nothing;
    }
    return html`
        <span>
            <span class="fw-semibold">${translations(labelKey)}:</span>
            ${value}
        </span>
    `;
}

function currentClubDescription(currentClub) {
    if (!currentClub) {
        return null;
    }
    if (currentClub.name && currentClub.club_id) {
        return `${currentClub.name} (#${currentClub.club_id})`;
    }
    if (currentClub.name) {
        return currentClub.name;
    }
    if (currentClub.club_id) {
        return `#${currentClub.club_id}`;
    }
    return null;
}

function playerResultTemplate(translations, player, selectCandidate) {
    const currentClub = currentClubDescription(player.current_club);
    return html`
        <li class="list-group-item">
            <div class="fw-semibold">
                ${player.first_name} ${player.last_name}
                <span class="badge text-bg-secondary ms-2">
                    #${player.player_id}
                </span>
            </div>
            <div class="small text-body-secondary d-flex flex-wrap gap-3 mt-1">
                ${resultDetail(
                    translations,
                    "player_search.birth_year",
                    player.birth_year,
                )}
                ${resultDetail(
                    translations,
                    "player_search.current_club",
                    currentClub,
                )}
                ${resultDetail(
                    translations,
                    "player_search.country",
                    player.country,
                )}
                ${resultDetail(
                    translations,
                    "player_search.fide_id",
                    player.fide_id,
                )}
            </div>
            <button
                class="btn btn-outline-primary btn-sm mt-2"
                type="button"
                @click=${function handlePlayerSelection() {
                    selectCandidate(player.player_id);
                }}
            >
                ${translations("player_search.select")}
            </button>
        </li>
    `;
}

function selectedPlayerTemplate(translations, inputId, player, clearPlayer) {
    const name = `${player.first_name} ${player.last_name}`;
    return html`
        <label class="form-label" for=${inputId}>
            ${translations("player_search.label")}
        </label>
        <div class="input-group">
            <input
                class="form-control"
                id=${inputId}
                type="text"
                readonly
                .value=${`${name} (#${player.player_id})`}
                data-selected-player-id=${player.player_id}
            >
            <button
                class="btn btn-outline-secondary"
                type="button"
                aria-label=${translations(
                    "player_selection.clear_label",
                    { name },
                )}
                @click=${clearPlayer}
            >
                ${translations("player_selection.clear")}
            </button>
        </div>
    `;
}

function statusClassName(tone) {
    if (tone === "failure") {
        return "player-name-search-status alert alert-danger py-2";
    }
    if (tone === "empty") {
        return "player-name-search-status alert alert-secondary py-2";
    }
    return "player-name-search-status form-text";
}

function validInitialPlayer(player) {
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

export class PlayerNameSelector {
    constructor({
        renderTarget,
        initialValue = null,
        lookup,
        translations,
    }) {
        if (renderTarget?.nodeType !== 1) {
            throw new TypeError("Player selector renderTarget must be an Element");
        }
        if (
            typeof lookup !== "function"
            || typeof translations !== "function"
        ) {
            throw new TypeError(
                "Player selector requires lookup and translations functions",
            );
        }
        if (initialValue !== null && !validInitialPlayer(initialValue)) {
            throw new TypeError(
                "Player selector initialValue must be a canonical player",
            );
        }

        selectorInstance += 1;
        this.root = renderTarget;
        this.translations = translations;
        this.inputId = `player-name-search-${selectorInstance}`;
        this.nameText = "";
        this.selectedPlayer = initialValue;
        this.searchState = new PlayerNameSearchState({
            search: lookup,
            onChange: (state) => {
                this.render(state);
                this.emitStateChange(state);
            },
            onCandidateSelected: (player) => {
                this.selectedPlayer = player;
                this.render(this.searchState.state);
                this.emitSelectionChange(player);
            },
        });
        this.root.addEventListener(
            "flickornas:player-selector-reset",
            () => this.reset(),
        );
        this.render(this.searchState.state);
    }

    emitSelectionChange(value) {
        this.root.dispatchEvent(
            new CustomEvent(
                "flickornas:player-selection-changed",
                {
                    bubbles: true,
                    detail: { value },
                },
            ),
        );
    }

    emitStateChange(state) {
        this.root.dispatchEvent(
            new CustomEvent(
                "flickornas:player-selector-state-changed",
                {
                    bubbles: true,
                    detail: { state },
                },
            ),
        );
    }

    reset() {
        this.nameText = "";
        this.selectedPlayer = null;
        this.searchState.reset();
        this.emitSelectionChange(null);
    }

    render(searchState) {
        const presentation = playerNameSearchPresentation(searchState);
        render(
            html`
                ${this.selectedPlayer === null
                    ? html`
                        <form @submit=${(event) => this.submit(event)}>
                            <label class="form-label" for=${this.inputId}>
                                ${this.translations("player_search.label")}
                            </label>
                            <div class="input-group">
                                <input
                                    class="form-control"
                                    id=${this.inputId}
                                    type="search"
                                    name="player_name"
                                    autocomplete="name"
                                    placeholder=${this.translations(
                                        "player_search.placeholder",
                                    )}
                                    .value=${this.nameText}
                                    @input=${(event) => {
                                        this.nameText = event.currentTarget.value;
                                    }}
                                >
                                <button
                                    class="btn btn-outline-primary"
                                    type="submit"
                                >
                                    ${this.translations("player_search.submit")}
                                </button>
                            </div>
                        </form>
                        <div
                            class=${statusClassName(presentation.tone)}
                            role=${presentation.tone === "failure"
                                ? "alert"
                                : "status"}
                            aria-live=${presentation.tone === "failure"
                                ? "assertive"
                                : "polite"}
                            data-player-search-state=${searchState.status}
                        >
                            ${searchState.status === "loading"
                                ? html`
                                    <span
                                        class="spinner-border spinner-border-sm me-2"
                                        aria-hidden="true"
                                    ></span>
                                `
                                : nothing}
                            ${this.translations(
                                presentation.messageKey,
                                presentation.parameters,
                            )}
                        </div>
                        <ul
                            class="list-group mt-3"
                            aria-label=${this.translations(
                                "player_search.results_label",
                            )}
                        >
                            ${searchState.players.map(
                                (player) => playerResultTemplate(
                                    this.translations,
                                    player,
                                    (playerId) => this.searchState
                                        .selectCandidate(playerId),
                                ),
                            )}
                        </ul>
                    `
                    : selectedPlayerTemplate(
                        this.translations,
                        this.inputId,
                        this.selectedPlayer,
                        () => this.reset(),
                    )}
            `,
            this.root,
        );
    }

    submit(event) {
        event.preventDefault();
        const input = event.currentTarget.elements.player_name;
        this.nameText = input.value;
        this.searchState.submit(this.nameText);
    }
}

export function mountPlayerNameSelector(options) {
    return new PlayerNameSelector(options);
}

export async function searchPlayers(endpoint, names) {
    const response = await fetch(
        playerNameSearchUrl(endpoint, names.firstName, names.lastName),
        { headers: { Accept: "application/json" } },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Player search failed");
        error.messageKey = payload.error?.message_key
            ?? "errors.member_system.unavailable";
        throw error;
    }
    return payload.data;
}

const root = document.querySelector("[data-player-name-selector]");
if (root) {
    mountPlayerNameSelector({
        renderTarget: root,
        initialValue: null,
        lookup(names) {
            return searchPlayers(root.dataset.searchEndpoint, names);
        },
        translations: translate,
    });
}
