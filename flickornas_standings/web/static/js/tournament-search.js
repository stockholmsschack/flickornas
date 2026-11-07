import { html, nothing, render } from "./lit-html.js";
import { translate } from "./locale.js";
import { problemList } from "./klass-naming.js";
import {
    configurationTournamentConsumer,
    runTournamentConsumer,
    TournamentPicker,
} from "./tournament-picker.js";
import {
    tournamentLookupUrl,
    tournamentSearchPresentation,
    TournamentSearchState,
    tournamentSearchUrl,
} from "./tournament-search-state.js";

function renderStatus(statusElement, state) {
    const presentation = tournamentSearchPresentation(state);
    let className = "tournament-search-status";
    if (presentation.tone === "failure") {
        className += " alert alert-danger py-2";
    } else if (presentation.tone === "empty") {
        className += " alert alert-secondary py-2";
    } else {
        className += " form-text";
    }

    statusElement.className = className;
    statusElement.dataset.searchState = state.status;
    render(
        html`
            ${state.status === "loading"
                ? html`
                    <span
                        class="spinner-border spinner-border-sm me-2"
                        aria-hidden="true"
                    ></span>
                `
                : nothing}
            ${state.problems?.length ? "" : translate(presentation.messageKey, presentation.parameters)}
            ${problemList(state.problems)}
        `,
        statusElement,
    );
}

function renderResults(resultsElement, tournaments, selectTournament) {
    render(
        html`
            ${tournaments.map(function tournamentResult(tournament) {
                const groupNames = tournament.matching_groups
                    .map((group) => group.name)
                    .join(", ");
                return html`
                    <li class="list-group-item">
                        <div class="fw-semibold">
                            ${tournament.name}
                            <span class="badge text-bg-secondary ms-2">
                                #${tournament.tournament_id}
                            </span>
                        </div>
                        <div class="small text-body-secondary">
                            ${translate("tournament_search.matching_groups", {
                                groups: groupNames,
                            })}
                        </div>
                        <button
                            class="btn btn-outline-primary btn-sm mt-2"
                            type="button"
                            @click=${function handleTournamentSelection() {
                                selectTournament(tournament);
                            }}
                        >
                            ${translate("tournament_search.select")}
                        </button>
                    </li>
                `;
            })}
        `,
        resultsElement,
    );
}

function renderSelectedTournaments(
    selectedElement,
    tournaments,
    requestTournamentRemoval,
    allowEmptySelection,
) {
    const canRemoveTournament = allowEmptySelection || tournaments.length > 1;
    selectedElement.dataset.selectedCount = String(tournaments.length);
    render(
        tournaments.length === 0
            ? nothing
            : html`
                <ul class="list-group">
                    ${tournaments.map((tournament) => html`
                        <li
                            class="list-group-item d-flex gap-3 align-items-center"
                            data-selected-tournament-id=${tournament.tournament_id}
                        >
                            <div class="fw-semibold flex-grow-1">
                                <a
                                    class="link-body-emphasis link-underline-opacity-25 link-underline-opacity-75-hover"
                                    href=${`https://member.schack.se/ShowAllTournamentRegistrationsServlet?id=${tournament.tournament_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    ${tournament.name}
                                    (${tournament.tournament_id})
                                </a>
                            </div>
                            <button
                                class="btn btn-outline-danger btn-sm"
                                type="button"
                                aria-label=${translate(
                                    "tournament_selection.remove_label",
                                    { name: tournament.name },
                                )}
                                ?disabled=${!canRemoveTournament}
                                title=${canRemoveTournament
                                    ? ""
                                    : translate(
                                        "tournament_selection.keep_one",
                                    )}
                                @click=${function handleRemoval() {
                                    requestTournamentRemoval(tournament);
                                }}
                            >
                                ${translate("tournament_selection.remove")}
                            </button>
                        </li>
                    `)}
                </ul>
                ${canRemoveTournament
                    ? nothing
                    : html`
                        <div class="form-text">
                            ${translate("tournament_selection.keep_one")}
                        </div>
                    `}
            `,
        selectedElement,
    );
}

function renderVerificationStatus(selectionElement, state) {
    selectionElement.dataset.selectionState = state.status;

    if (state.status === "failure" && state.problems?.length) {
        selectionElement.className = "alert alert-danger mt-3";
        selectionElement.setAttribute("role", "alert");
        render(problemList(state.problems), selectionElement);
        return;
    }
    selectionElement.setAttribute("role", "status");
    if (state.status !== "verifying") {
        selectionElement.className = "";
        render(nothing, selectionElement);
        return;
    }

    selectionElement.className = "alert alert-secondary mt-3";
    render(
        html`
            <span
                class="spinner-border spinner-border-sm me-2"
                aria-hidden="true"
            ></span>
            ${translate("tournament_selection.verifying")}
        `,
        selectionElement,
    );
}

function showSelectionToast(
    toastElement,
    messageElement,
    toast,
    state,
    showVerified,
) {
    if (
        state.status !== "failure"
        && !(showVerified && state.status === "verified")
    ) {
        return;
    }

    const successful = state.status === "verified";
    toastElement.className = successful
        ? "toast border-0 text-bg-success"
        : "toast border-0 text-bg-danger";
    toastElement.setAttribute("role", successful ? "status" : "alert");
    toastElement.setAttribute(
        "aria-live",
        successful ? "polite" : "assertive",
    );
    let message = "";
    if (successful) {
        message = translate("tournament_selection.added", {
            name: state.verifiedTournament.name,
        });
    } else if (!state.problems?.length) {
        message = translate(state.errorMessageKey);
    }
    render(html`${message}${problemList(state.problems)}`, messageElement);
    toast.show();
}

async function searchTournaments(endpoint, query) {
    const response = await fetch(tournamentSearchUrl(query, endpoint), {
        headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Tournament search failed");
        error.messageKey = payload.error?.message_key
            ?? "errors.member_system.unavailable";
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
    return payload.data;
}

async function lookupTournament(endpointTemplate, tournamentId) {
    const response = await fetch(
        tournamentLookupUrl(tournamentId, endpointTemplate),
        { headers: { Accept: "application/json" } },
    );
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Tournament lookup failed");
        error.messageKey = payload.error?.message_key
            ?? "errors.member_system.unavailable";
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
    return payload.data;
}

function tournamentSummaries(tournaments) {
    return tournaments.map((tournament) => ({
        tournament_id: tournament.tournament_id,
        name: tournament.name,
        start_date: tournament.start_date,
        end_date: tournament.end_date,
    }));
}

function latestTournamentEndDate(tournaments) {
    return tournaments.reduce(
        function latestEndDate(latest, tournament) {
            return tournament.end_date > latest
                ? tournament.end_date
                : latest;
        },
        "",
    ) || null;
}

async function saveTournaments(endpoint, revision, tournaments) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            revision,
            tournament_ids: tournaments.map(
                (tournament) => tournament.tournament_id,
            ),
        }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Tournament configuration save failed");
        error.messageKey = payload.error?.message_key
            ?? "errors.internal";
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
    return payload.data;
}

function renderSaveStatus(element, state) {
    element.dataset.saveState = state.status;
    if (state.status === "idle") {
        element.className = "mt-3";
        render(nothing, element);
        return;
    }
    if (state.status === "saving") {
        element.className = "alert alert-secondary mt-3";
        render(
            html`
                <span
                    class="spinner-border spinner-border-sm me-2"
                    aria-hidden="true"
                ></span>
                ${translate("tournament_selection.saving")}
            `,
            element,
        );
        return;
    }
    element.className = state.status === "saved"
        ? "alert alert-success mt-3"
        : "alert alert-danger mt-3";
    const messageKey = state.status === "saved"
        ? "tournament_selection.saved"
        : state.messageKey;
    render(html`
        ${state.problems?.length ? "" : translate(messageKey)}
        ${problemList(state.problems)}
    `, element);
}

export function mountTournamentSearch(root, initialTournaments = null) {
    const input = root.querySelector("[data-tournament-search-input]");
    const status = root.querySelector("[data-tournament-search-status]");
    const results = root.querySelector("[data-tournament-search-results]");
    const pastedIdForm = root.querySelector("[data-tournament-id-form]");
    const pastedIdInput = root.querySelector("[data-tournament-id-input]");
    const selected = root.querySelector("[data-selected-tournaments]");
    const removeAllButton = root.querySelector(
        "[data-remove-all-tournaments]",
    );
    const selection = root.querySelector("[data-tournament-selection]");
    const selectionToastElement = root.querySelector(
        "[data-tournament-selection-toast]",
    );
    const selectionToastMessage = root.querySelector(
        "[data-tournament-selection-toast-message]",
    );
    const saveStatus = root.querySelector("[data-tournament-save-status]");
    const removalDialogElement = root.querySelector(
        "[data-tournament-removal-dialog]",
    );
    const removalHeading = root.querySelector(
        "[data-tournament-removal-heading]",
    );
    const removalDescription = root.querySelector(
        "[data-tournament-removal-description]",
    );
    const removalTournamentName = root.querySelector(
        "[data-tournament-removal-name]",
    );
    const confirmRemovalButton = root.querySelector(
        "[data-confirm-tournament-removal]",
    );
    const initialDataId = root.dataset.initialTournamentsData
        ?? "selected-tournaments-data";
    const initialData = document.getElementById(initialDataId);
    const resolvedInitialTournaments = initialTournaments
        ?? (initialData ? JSON.parse(initialData.textContent) : []);
    const searchEndpoint = root.dataset.searchEndpoint;
    const lookupEndpointTemplate = root.dataset.lookupEndpointTemplate;
    const saveEndpoint = root.dataset.saveEndpoint;
    let configurationRevision = Number(root.dataset.configurationRevision);
    let persistedTournaments = [...resolvedInitialTournaments];
    let savePromise = Promise.resolve();
    let saveVersion = 0;
    let replacingFailedSelection = false;
    let pendingRemoval = null;
    const removalDialog = new globalThis.bootstrap.Modal(removalDialogElement);
    const selectionToast = new globalThis.bootstrap.Toast(
        selectionToastElement,
        { delay: 8000 },
    );
    status.textContent = "";
    selection.textContent = "";

    function requestTournamentRemoval(tournament) {
        if (
            root.dataset.tournamentConsumer !== "run"
            && picker.state.selectedTournaments.length <= 1
        ) {
            return;
        }
        pendingRemoval = {
            kind: "one",
            tournamentId: tournament.tournament_id,
        };
        removalHeading.textContent = translate(
            "tournament_selection.remove_heading",
        );
        removalDescription.textContent = translate(
            "tournament_selection.remove_confirmation",
        );
        removalTournamentName.textContent = tournament.name;
        confirmRemovalButton.textContent = translate(
            "tournament_selection.remove",
        );
        removalDialog.show();
    }

    function requestAllTournamentsRemoval() {
        const tournaments = picker.state.selectedTournaments;
        if (tournaments.length === 0) {
            return;
        }
        pendingRemoval = { kind: "all" };
        removalHeading.textContent = translate(
            "tournament_selection.remove_all_heading",
        );
        removalDescription.textContent = translate(
            "tournament_selection.remove_all_confirmation",
        );
        removalTournamentName.textContent = tournaments
            .map((tournament) => tournament.name)
            .join(", ");
        confirmRemovalButton.textContent = translate(
            "tournament_selection.remove_all",
        );
        removalDialog.show();
    }

    function announcePersistence(pending) {
        globalThis.dispatchEvent(new CustomEvent(
            "flickornas:tournament-persistence-changed",
            { detail: { source: root, pending } },
        ));
    }

    function scheduleSave(tournaments) {
        if (replacingFailedSelection) {
            return;
        }
        const requestedTournaments = [...tournaments];
        const requestedVersion = ++saveVersion;
        renderSaveStatus(saveStatus, { status: "saving" });
        announcePersistence(true);
        savePromise = savePromise
            .then(async function persistTournamentSelection() {
                const saved = await saveTournaments(
                    saveEndpoint,
                    configurationRevision,
                    requestedTournaments,
                );
                configurationRevision = saved.revision;
                persistedTournaments = requestedTournaments;
                root.dataset.configurationRevision = String(saved.revision);
                globalThis.dispatchEvent(new CustomEvent(
                    "flickornas:configuration-revision-changed",
                    {
                        detail: {
                            revision: saved.revision,
                            source: root,
                        },
                    },
                ));
                if (saved.rollover_completed) {
                    globalThis.dispatchEvent(new CustomEvent(
                        "flickornas:calendar-rollover-completed",
                    ));
                }
                if (requestedVersion === saveVersion) {
                    renderSaveStatus(saveStatus, { status: "saved" });
                    announcePersistence(false);
                }
            })
            .catch(function restorePersistedSelection(error) {
                if (requestedVersion !== saveVersion) {
                    return;
                }
                replacingFailedSelection = true;
                picker.replaceTournaments(persistedTournaments);
                replacingFailedSelection = false;
                renderSaveStatus(saveStatus, {
                    status: "failure",
                    messageKey: error?.messageKey ?? "errors.internal",
                    problems: error?.problems ?? [],
                });
                if (error?.problems?.length) {
                    showSelectionToast(selectionToastElement, selectionToastMessage, selectionToast, {
                        status: "failure", problems: error.problems, errorMessageKey: error.messageKey,
                    }, false);
                }
                announcePersistence(false);
            });
    }

    const isRunPicker = root.dataset.tournamentConsumer === "run";
    const consumer = isRunPicker
        ? runTournamentConsumer({
            initialTournaments: resolvedInitialTournaments,
        })
        : configurationTournamentConsumer({
            initialTournaments: resolvedInitialTournaments,
            selectionChanged(value) {
                scheduleSave(value.tournaments);
            },
            commit(value) {
                return value;
            },
        });
    const picker = new TournamentPicker({
        lookup(tournamentId) {
            return lookupTournament(lookupEndpointTemplate, tournamentId);
        },
        consumer,
        onChange(nextState) {
            renderTournamentSelection(nextState);
        },
    });
    function renderTournamentSelection(state) {
        if (removeAllButton) {
            removeAllButton.disabled = state.selectedTournaments.length === 0;
        }
        renderSelectedTournaments(
            selected,
            state.selectedTournaments,
            requestTournamentRemoval,
            isRunPicker,
        );
        renderVerificationStatus(selection, state);
        showSelectionToast(
            selectionToastElement,
            selectionToastMessage,
            selectionToast,
            state,
            isRunPicker,
        );
        globalThis.dispatchEvent(new CustomEvent(
            "flickornas:tournament-selection-changed",
            {
                detail: {
                    source: root,
                    tournaments: tournamentSummaries(
                        state.selectedTournaments,
                    ),
                    referenceDate: latestTournamentEndDate(
                        state.selectedTournaments,
                    ),
                },
            },
        ));
    }
    const searchState = new TournamentSearchState({
        search(query) {
            return searchTournaments(searchEndpoint, query);
        },
        onChange(nextState) {
            renderStatus(status, nextState);
            renderResults(results, nextState.tournaments, selectTournament);
        },
    });

    function clearTournamentSearch() {
        input.value = "";
        searchState.clear();
    }

    async function selectTournament(tournament) {
        await picker.selectSearchResult(tournament);
        const verifiedTournamentId =
            picker.state.verifiedTournament?.tournament_id;
        if (
            picker.state.status === "verified"
            && verifiedTournamentId === tournament.tournament_id
        ) {
            clearTournamentSearch();
        }
    }

    renderStatus(status, searchState.state);
    renderResults(results, searchState.state.tournaments, selectTournament);
    renderTournamentSelection(picker.state);
    if (saveStatus) {
        renderSaveStatus(saveStatus, { status: "idle" });
    }

    input.addEventListener("input", function handleSearchInput() {
        picker.clearStatus();
        searchState.setSearchText(input.value);
    });
    pastedIdInput.addEventListener("input", function handlePastedIdInput() {
        picker.clearStatus();
    });
    function verifyPastedTournamentId() {
        const tournamentId = pastedIdInput.value;
        pastedIdInput.value = "";
        clearTournamentSearch();
        return picker.verifyTournamentId(tournamentId);
    }
    if (pastedIdForm.tagName === "FORM") {
        pastedIdForm.addEventListener(
            "submit",
            function handlePastedId(event) {
                event.preventDefault();
                verifyPastedTournamentId();
            },
        );
    } else {
        root.querySelector("[data-verify-tournament-id]").addEventListener(
            "click",
            verifyPastedTournamentId,
        );
    }
    removeAllButton?.addEventListener(
        "click",
        requestAllTournamentsRemoval,
    );
    confirmRemovalButton.addEventListener(
        "click",
        function confirmTournamentRemoval() {
            if (pendingRemoval === null) {
                return;
            }
            const removal = pendingRemoval;
            pendingRemoval = null;
            if (removal.kind === "all") {
                picker.removeAllTournaments();
            } else {
                picker.removeTournament(removal.tournamentId);
            }
            removalDialog.hide();
        },
    );
    removalDialogElement.addEventListener(
        "hidden.bs.modal",
        function clearTournamentPendingRemoval() {
            pendingRemoval = null;
            removalTournamentName.textContent = "";
        },
    );
    if (!isRunPicker) {
        globalThis.addEventListener(
            "flickornas:before-navigation",
            function persistBeforeNavigation(event) {
                event.detail.waitUntil(savePromise);
            },
        );
        globalThis.addEventListener(
            "flickornas:configuration-revision-changed",
            function adoptConfigurationRevision(event) {
                if (event.detail.source === root) {
                    return;
                }
                configurationRevision = event.detail.revision;
                root.dataset.configurationRevision = String(
                    configurationRevision,
                );
            },
        );
    }
    return picker;
}

for (const root of document.querySelectorAll(
    "[data-tournament-search]:not([data-tournament-manual-mount])",
)) {
    mountTournamentSearch(root);
}
