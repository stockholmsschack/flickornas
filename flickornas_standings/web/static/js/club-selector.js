import { html, nothing, render } from "./lit-html.js";
import {
    ClubSelectorState,
    clubSelectorPresentation,
} from "./club-selector-state.js";
import { translate } from "./locale.js";

let selectorInstance = 0;
const clubLoads = new Map();

function statusClassName(tone) {
    if (tone === "failure") {
        return "club-search-status alert alert-danger py-2";
    }
    if (tone === "empty") {
        return "club-search-status alert alert-secondary py-2";
    }
    return "club-search-status form-text";
}

function clubResultTemplate(translations, club, selectClub) {
    return html`
        <li class="list-group-item d-flex align-items-center gap-2">
            <span class="flex-grow-1">
                <span class="fw-semibold">${club.name}</span>
                <span class="badge text-bg-secondary ms-2">
                    #${club.club_id}
                </span>
            </span>
            <button
                class="btn btn-outline-primary btn-sm"
                type="button"
                @click=${() => selectClub(club.club_id)}
            >
                ${translations("club_search.select")}
            </button>
        </li>
    `;
}

function selectedClubTemplate(translations, inputId, club, clearClub) {
    return html`
        <label class="form-label" for=${inputId}>
            ${translations("club_search.label")}
        </label>
        <div class="input-group">
            <input
                class="form-control"
                id=${inputId}
                type="text"
                readonly
                .value=${club.name}
                data-selected-club-id=${club.club_id}
            >
            <button
                class="btn btn-outline-secondary"
                type="button"
                aria-label=${translations(
                    "club_selection.clear_label",
                    { name: club.name },
                )}
                @click=${clearClub}
            >
                ${translations("club_selection.clear")}
            </button>
        </div>
    `;
}

export class ClubSelector {
    constructor({
        renderTarget,
        initialValue = null,
        lookup,
        translations,
    }) {
        if (renderTarget?.nodeType !== 1) {
            throw new TypeError("Club selector renderTarget must be an Element");
        }
        if (
            typeof lookup !== "function"
            || typeof translations !== "function"
        ) {
            throw new TypeError(
                "Club selector requires lookup and translations functions",
            );
        }

        selectorInstance += 1;
        this.root = renderTarget;
        this.translations = translations;
        this.inputId = `club-search-${selectorInstance}`;
        this.state = new ClubSelectorState({
            load: lookup,
            initialValue,
            onChange: (state) => {
                this.render(state);
                this.root.dispatchEvent(
                    new CustomEvent(
                        "flickornas:club-selector-state-changed",
                        {
                            bubbles: true,
                            detail: { state },
                        },
                    ),
                );
            },
            onSelectionChange: (club) => {
                this.root.dispatchEvent(
                    new CustomEvent(
                        "flickornas:club-selection-changed",
                        {
                            bubbles: true,
                            detail: { value: club },
                        },
                    ),
                );
            },
        });
        this.root.addEventListener(
            "flickornas:club-selector-reset",
            () => this.state.reset(),
        );
        this.render(this.state.state);
        this.state.load();
    }

    render(state) {
        const presentation = clubSelectorPresentation(state);
        const searchStatus = presentation === null
            ? nothing
            : html`
                <div
                    class=${statusClassName(presentation.tone)}
                    role=${presentation.tone === "failure"
                        ? "alert"
                        : "status"}
                    aria-live=${presentation.tone === "failure"
                        ? "assertive"
                        : "polite"}
                    data-club-search-state=${state.status}
                >
                    ${state.status === "loading"
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
            `;
        const searchResults = state.filteredClubs.length === 0
            ? nothing
            : html`
                <ul
                    class="club-search-results list-group mt-2"
                    aria-label=${this.translations(
                        "club_search.results_label",
                    )}
                >
                    ${state.filteredClubs.map(
                        (club) => clubResultTemplate(
                            this.translations,
                            club,
                            (clubId) => this.state.selectClub(clubId),
                        ),
                    )}
                </ul>
            `;
        render(
            html`
                ${state.verifiedClub === null
                    ? html`
                        <label class="form-label" for=${this.inputId}>
                            ${this.translations("club_search.label")}
                        </label>
                        <input
                            class="form-control"
                            id=${this.inputId}
                            type="search"
                            autocomplete="off"
                            placeholder=${this.translations(
                                "club_search.placeholder",
                            )}
                            .value=${state.searchText}
                            @input=${(event) => {
                                this.state.setSearchText(
                                    event.currentTarget.value,
                                );
                            }}
                        >
                        ${searchStatus}
                        ${searchResults}
                    `
                    : selectedClubTemplate(
                        this.translations,
                        this.inputId,
                        state.verifiedClub,
                        () => this.state.reset(),
                    )}
            `,
            this.root,
        );
    }
}

export function mountClubSelector(options) {
    return new ClubSelector(options);
}

export function loadClubs(endpoint) {
    if (clubLoads.has(endpoint)) {
        return clubLoads.get(endpoint);
    }
    const request = fetch(
        endpoint,
        { headers: { Accept: "application/json" } },
    ).then(async function readClubResponse(response) {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error("Club list lookup failed");
            error.messageKey = payload.error?.message_key
                ?? "errors.member_system.unavailable";
            throw error;
        }
        return payload.data;
    }).catch(function discardFailedClubLoad(error) {
        clubLoads.delete(endpoint);
        throw error;
    });
    clubLoads.set(endpoint, request);
    return request;
}

const root = document.querySelector("[data-club-selector]");
if (root) {
    mountClubSelector({
        renderTarget: root,
        initialValue: null,
        lookup() {
            return loadClubs(root.dataset.clubsEndpoint);
        },
        translations: translate,
    });
}
