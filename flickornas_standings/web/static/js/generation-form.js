import { html, render } from "./lit-html.js";
import { translate } from "./locale.js";
import { problemList } from "./klass-naming.js";
import {
    LAST_GENERATION_OPERATION_KEY,
    rememberGenerationOperation,
    shouldShowRecoveredOperation,
} from "./generation-operation-memory.js";
import { generationInputsMatch } from "./generation-input-state.js";
import { followOperation } from "./operation-stream.js";
import { mountTournamentSearch } from "./tournament-search.js";

const root = document.querySelector("[data-generation-form]");
const openButton = document.querySelector("[data-generation-open]");

if (openButton) {
    let rolloverActive = openButton.dataset.rolloverActive === "true";
    let hasSelectedTournaments =
        openButton.dataset.hasSelectedTournaments === "true";
    let tournamentPersistencePending = false;

    function updateOpenButton() {
        openButton.disabled = Boolean(
            rolloverActive
            || !hasSelectedTournaments
            || tournamentPersistencePending,
        );
    }

    globalThis.addEventListener(
        "flickornas:tournament-selection-changed",
        function updateConfiguredTournamentSelection(event) {
            if (event.detail.source.dataset.tournamentConsumer === "run") {
                return;
            }
            hasSelectedTournaments = event.detail.tournaments.length > 0;
            updateOpenButton();
        },
    );
    globalThis.addEventListener(
        "flickornas:tournament-persistence-changed",
        function updateTournamentPersistence(event) {
            if (event.detail.source.dataset.tournamentConsumer === "run") {
                return;
            }
            tournamentPersistencePending = event.detail.pending;
            updateOpenButton();
        },
    );
    globalThis.addEventListener(
        "flickornas:calendar-rollover-completed",
        function enableCompletedRollover() {
            rolloverActive = false;
            updateOpenButton();
        },
    );
    updateOpenButton();
}

function errorMessage(error) {
    return translate(error?.messageKey ?? "errors.internal");
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {}),
        },
        ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Generation input request failed");
        error.messageKey = payload.error?.message_key ?? "errors.internal";
        error.code = payload.error?.code ?? "internal";
        error.details = payload.error?.details ?? {};
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
    return payload.data;
}

if (root) {
    const dialog = root;
    const form = root.querySelector("[data-generation-input-form]");
    const yearInput = root.querySelector("[data-generation-year]");
    const layoutInput = root.querySelector("[data-generation-layout]");
    const explicitTournamentsInput = root.querySelector(
        "[data-generation-explicit-tournaments]",
    );
    const pickerContainer = root.querySelector(
        "[data-generation-tournament-picker]",
    );
    const pickerRoot = pickerContainer?.querySelector(
        "[data-tournament-search]",
    ) ?? null;
    const canSelectTournaments = explicitTournamentsInput !== null;
    const defaultsStatus = root.querySelector(
        "[data-generation-defaults-status]",
    );
    const status = root.querySelector("[data-generation-status]");
    const announcement = root.querySelector(
        "[data-generation-announcement]",
    );
    const submitButton = root.querySelector("[data-start-generation]");
    const submitHint = root.querySelector("[data-generation-submit-hint]");
    // Clear the server-rendered loading text before lit renders this region.
    defaultsStatus.textContent = "";
    let picker = null;
    let configuredTournaments = [];
    let selectedTournaments = [];
    let yearWasEdited = false;
    let defaultsPromise = null;
    let defaultsReady = false;
    let defaultsFailureMessageKey = null;
    let operationFollower = null;
    let activeOperation = null;
    let completedOperation = null;
    let configurationRevision = Number(root.dataset.configurationRevision);
    let lastAnnouncedEventId = 0;
    let submitting = false;
    let configuredTournamentPersistencePending = false;

    function currentGenerationInputs() {
        const tournaments = canSelectTournaments
            && explicitTournamentsInput.checked
            ? selectedTournaments
            : configuredTournaments;
        return {
            effectiveYear: Number(yearInput.value),
            configurationRevision,
            layout: layoutInput.value,
            tournamentIds: tournaments.map(
                (tournament) => tournament.tournament_id,
            ),
        };
    }

    function generatedInputsAreCurrent() {
        return completedOperation !== null
            && generationInputsMatch(
                completedOperation,
                currentGenerationInputs(),
            );
    }

    function updateSubmitButton() {
        const generatedInputsCurrent = generatedInputsAreCurrent();
        submitButton.disabled = Boolean(
            !defaultsReady
            || submitting
            || configuredTournamentPersistencePending
            || (activeOperation && !activeOperation.terminal)
            || generatedInputsCurrent,
        );
        let hint = "";
        if (generatedInputsCurrent) {
            hint = translate("generation.inputs_unchanged");
        } else if (!defaultsReady) {
            hint = translate(defaultsFailureMessageKey ?? "generation.loading_defaults");
        }
        submitHint.textContent = hint;
        submitButton.title = hint;
    }

    function stageText(stage) {
        if (!stage) {
            return translate("operations.stage.unknown");
        }
        const metadataMatch = stage.match(
            /^Fetching metadata for tournament (\d+)$/,
        );
        if (metadataMatch) {
            return translate("operations.stage.fetching_metadata", {
                tournament_id: metadataMatch[1],
            });
        }
        const tournamentMatch = stage.match(
            /^Fetching tournament (\d+)\/(\d+): (.+)$/,
        );
        if (tournamentMatch) {
            return translate("operations.stage.fetching_tournament", {
                current: tournamentMatch[1],
                total: tournamentMatch[2],
                name: tournamentMatch[3],
            });
        }
        const key = {
            "Validating configuration": "validating",
            "Fetching tournaments": "fetching_tournaments",
            "Fetching district players and clubs": "fetching_district",
            "Processing results": "processing",
            "Calculating standings": "calculating",
            "Producing output artifacts": "producing_artifacts",
            "Staging artifacts": "staging_artifacts",
            "Rendering PDF": "rendering_pdf",
            "Publishing generation": "publishing",
            validation: "validating",
            scheduling: "scheduling",
            fetching: "fetching",
            calculation: "calculation",
            "artifact production": "artifact_production",
            "artifact staging": "artifact_staging",
            rendering: "rendering",
            committing: "committing",
            starting: "starting",
        }[stage];
        return key
            ? translate(`operations.stage.${key}`)
            : stage;
    }

    function eventText(event) {
        const parameters = { ...(event.parameters ?? {}) };
        if (parameters.stage) {
            parameters.stage = stageText(parameters.stage);
        }
        return translate(event.message_key, parameters);
    }

    function latestEvent(operation) {
        return operation.events?.at(-1) ?? {
            event_id: operation.latest_event_id,
            kind: operation.state,
            message_key: `operations.${operation.state}`,
            parameters: operation.failure_stage
                ? { stage: operation.failure_stage }
                : {},
            progress: {},
        };
    }

    function progressDetails(operation) {
        const progress = latestEvent(operation).progress ?? {};
        const completed = Number(progress.completed);
        const total = Number(progress.total);
        if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
            return {
                determinate: true,
                completed,
                total,
                percentage: Math.min(
                    100,
                    Math.max(0, Math.round((completed / total) * 100)),
                ),
            };
        }
        return { determinate: false, percentage: 100 };
    }

    function operationTone(operation) {
        if (operation.state === "failed") {
            return "danger";
        }
        if (operation.state === "completed") {
            return "success";
        }
        return "info";
    }

    function announceOperation(operation) {
        const event = latestEvent(operation);
        if (
            event.kind === "progress"
            || event.event_id <= lastAnnouncedEventId
        ) {
            return;
        }
        lastAnnouncedEventId = event.event_id;
        announcement.textContent = eventText(event);
    }

    function renderOperation(operation) {
        activeOperation = operation;
        if (operation.state === "completed") {
            completedOperation = operation;
        }
        const event = latestEvent(operation);
        const progress = progressDetails(operation);
        const tone = operationTone(operation);
        const logEvents = (operation.events ?? []).filter(
            (item) => item.kind !== "progress",
        );
        status.className = "mt-3";
        render(html`
            <section class="alert alert-${tone} mb-0" data-operation-progress>
                <div class="d-flex justify-content-between gap-3 mb-2">
                    <strong>${eventText(event)}</strong>
                    ${progress.determinate
                        ? html`<span>${progress.completed}/${progress.total}</span>`
                        : ""}
                </div>
                ${problemList(event.parameters?.problems)}
                ${operation.terminal
                    ? ""
                    : html`
                        <div
                            class="progress"
                            role="progressbar"
                            aria-label=${translate("generation.progress_label")}
                            aria-valuemin="0"
                            aria-valuemax="100"
                            aria-valuenow=${progress.determinate
                                ? String(progress.percentage)
                                : null}
                            aria-valuetext=${progress.determinate
                                ? translate("generation.progress_value", {
                                    completed: progress.completed,
                                    total: progress.total,
                                })
                                : translate("generation.progress_indeterminate")}
                        >
                            <div
                                class="progress-bar ${progress.determinate
                                    ? ""
                                    : "progress-bar-striped progress-bar-animated"}"
                                style=${`width: ${progress.percentage}%`}
                            ></div>
                        </div>
                    `}
                ${operation.state === "completed"
                    ? html`
                        <div class="d-flex flex-wrap gap-2 mt-3">
                            <a
                                class="btn btn-success"
                                href=${operation.links.pdf}
                                @click=${closeDialogAndNavigate}
                            >
                                ${translate("generation.download_pdf")}
                            </a>
                            <a
                                class="btn btn-outline-dark"
                                href=${operation.links.files}
                                @click=${closeDialogAndNavigate}
                            >
                                ${translate("generation.view_files")}
                            </a>
                            <button
                                class="btn btn-primary"
                                type="button"
                                data-generate-again
                                @click=${startGeneration}
                            >
                                ${translate("generation.again")}
                            </button>
                        </div>
                    `
                    : ""}
                <details class="mt-3">
                    <summary>${translate("generation.progress_log")}</summary>
                    <ol class="list-group list-group-numbered mt-2">
                        ${logEvents.map((item) => html`
                            <li class="list-group-item">${eventText(item)}</li>
                        `)}
                    </ol>
                </details>
            </section>
        `, status);
        announceOperation(operation);
        updateSubmitButton();
    }

    function rememberOperation(operation) {
        rememberGenerationOperation(globalThis.localStorage, operation);
    }

    function follow(operation) {
        operationFollower?.close();
        rememberOperation(operation);
        renderOperation(operation);
        if (operation.terminal) {
            operationFollower = null;
            return;
        }
        operationFollower = followOperation({
            hubUrl: root.dataset.mercureHub,
            topic: operation.topic,
            statusUrl: operation.status_url,
            onOperation(updated) {
                renderOperation(updated);
                if (updated.terminal) {
                    operationFollower?.close();
                    operationFollower = null;
                }
            },
            onStatusError() {
                if (!activeOperation?.terminal) {
                    announcement.textContent = translate(
                        "generation.progress_reconnecting",
                    );
                }
            },
        });
    }

    async function recover(statusUrl) {
        const operation = await requestJson(statusUrl);
        follow(operation);
        return operation;
    }

    function renderStatus(tone, content) {
        status.className = `alert alert-${tone} mt-3`;
        render(content, status);
        announcement.textContent = status.textContent.trim();
    }

    function closeDialogAndNavigate(event) {
        event.preventDefault();
        const destination = event.currentTarget.href;
        dialog.addEventListener(
            "hidden.bs.modal",
            function navigateAfterDialogCloses() {
                globalThis.location.assign(destination);
            },
            { once: true },
        );
        globalThis.bootstrap.Modal.getOrCreateInstance(dialog).hide();
    }

    function clearPriorGenerationResult() {
        if (activeOperation?.terminal) {
            activeOperation = null;
            lastAnnouncedEventId = 0;
            status.className = "mt-3";
            render("", status);
            announcement.textContent = "";
        }
        updateSubmitButton();
    }

    async function loadDefaults() {
        defaultsFailureMessageKey = null;
        defaultsStatus.className = "alert alert-secondary";
        render(translate("generation.loading_defaults"), defaultsStatus);
        updateSubmitButton();
        try {
            const defaults = await requestJson(root.dataset.defaultsEndpoint);
            configurationRevision = Math.max(
                configurationRevision, defaults.configuration_revision,
            );
            yearInput.value = String(defaults.current_year);
            yearWasEdited = false;
            configuredTournaments = defaults.tournaments;
            selectedTournaments = defaults.tournaments;
            if (canSelectTournaments) {
                picker = mountTournamentSearch(
                    pickerRoot,
                    defaults.tournaments,
                );
            }
            defaultsStatus.className = "alert alert-info";
            render(translate(
                canSelectTournaments
                    ? "generation.configured_tournaments"
                    : "generation.configured_tournaments.fixed",
                { count: defaults.tournaments.length },
            ), defaultsStatus);
            defaultsReady = true;
            updateSubmitButton();
        } catch (error) {
            defaultsReady = false;
            defaultsFailureMessageKey = error?.messageKey ?? "errors.internal";
            defaultsStatus.className = "alert alert-danger";
            render(html`
                ${error.problems?.length ? "" : errorMessage(error)}
                ${problemList(error.problems)}
            `, defaultsStatus);
            updateSubmitButton();
        }
    }

    dialog.addEventListener("show.bs.modal", function prepareGenerationForm() {
        if (defaultsPromise === null) {
            defaultsPromise = loadDefaults().finally(function allowDefaultsRetry() {
                if (!defaultsReady) {
                    defaultsPromise = null;
                }
            });
        }
    });
    globalThis.addEventListener(
        "flickornas:configuration-revision-changed",
        function adoptConfigurationRevision(event) {
            configurationRevision = event.detail.revision;
            clearPriorGenerationResult();
        },
    );
    yearInput.addEventListener("input", function markYearAsExplicit() {
        yearWasEdited = true;
        clearPriorGenerationResult();
    });
    layoutInput.addEventListener("change", clearPriorGenerationResult);
    if (canSelectTournaments) {
        explicitTournamentsInput.addEventListener(
            "change",
            function toggleTournamentReplacement() {
                pickerContainer.classList.toggle(
                    "d-none",
                    !explicitTournamentsInput.checked,
                );
                clearPriorGenerationResult();
            },
        );
    }
    globalThis.addEventListener(
        "flickornas:tournament-persistence-changed",
        function updateConfiguredTournamentPersistence(event) {
            if (event.detail.source.dataset.tournamentConsumer === "run") {
                return;
            }
            configuredTournamentPersistencePending = event.detail.pending;
            updateSubmitButton();
        },
    );
    globalThis.addEventListener(
        "flickornas:tournament-selection-changed",
        function updateRunTournamentSelection(event) {
            if (event.detail.source === pickerRoot) {
                selectedTournaments = event.detail.tournaments;
                clearPriorGenerationResult();
                return;
            }
            if (event.detail.source.dataset.tournamentConsumer === "run") {
                return;
            }
            configuredTournaments = event.detail.tournaments;
            selectedTournaments = event.detail.tournaments;
            picker?.replaceTournaments(configuredTournaments);
            if (defaultsReady) {
                render(translate(
                    canSelectTournaments
                        ? "generation.configured_tournaments"
                        : "generation.configured_tournaments.fixed",
                    { count: selectedTournaments.length },
                ), defaultsStatus);
            }
            clearPriorGenerationResult();
        },
    );
    async function startGeneration() {
        if (submitting || (activeOperation && !activeOperation.terminal)) {
            return;
        }
        if (
            !form.reportValidity()
            || (canSelectTournaments && picker === null)
        ) {
            return;
        }
        if (
            canSelectTournaments
            && explicitTournamentsInput.checked
            && picker.state.status === "verifying"
        ) {
            renderStatus(
                "danger",
                translate("errors.generation.lookup_pending"),
            );
            return;
        }

        submitting = true;
        submitButton.disabled = true;
        renderStatus(
            "secondary",
            html`
                <span
                    class="spinner-border spinner-border-sm me-2"
                    aria-hidden="true"
                ></span>
                ${translate("generation.checking")}
            `,
        );
        try {
            const operation = await requestJson(root.dataset.startEndpoint, {
                method: "POST",
                body: JSON.stringify({
                    year: yearWasEdited ? Number(yearInput.value) : null,
                    tournament_ids: canSelectTournaments
                        && explicitTournamentsInput.checked
                        ? selectedTournaments.map(
                            (tournament) => tournament.tournament_id,
                        )
                        : null,
                    layout: layoutInput.value,
                }),
            });
            follow(operation);
        } catch (error) {
            if (error.code === "generation_busy" && error.details.status_url) {
                renderStatus(
                    "warning",
                    html`
                        <div class="fw-semibold">${errorMessage(error)}</div>
                        <button
                            class="btn btn-outline-dark btn-sm mt-2"
                            type="button"
                            @click=${async () => {
                                try {
                                    await recover(error.details.status_url);
                                } catch (recoveryError) {
                                    renderStatus(
                                        "danger",
                                        errorMessage(recoveryError),
                                    );
                                }
                            }}
                        >
                            ${translate("generation.follow_active")}
                        </button>
                    `,
                );
                return;
            }
            if (!error.problems?.length) {
                renderStatus("danger", errorMessage(error));
                return;
            }
            renderStatus(
                "danger",
                html`
                    <div class="fw-semibold">
                        ${translate("errors.generation.invalid_input")}
                    </div>
                    ${problemList(error.problems)}
                `,
            );
        } finally {
            submitting = false;
            updateSubmitButton();
        }
    }

    form.addEventListener("submit", function resolveInputs(event) {
        event.preventDefault();
        void startGeneration();
    });

    const savedOperation = globalThis.localStorage.getItem(
        LAST_GENERATION_OPERATION_KEY,
    );
    if (savedOperation) {
        try {
            const descriptor = JSON.parse(savedOperation);
            if (typeof descriptor.statusUrl === "string") {
                void recover(descriptor.statusUrl).then((operation) => {
                    if (shouldShowRecoveredOperation(operation)) {
                        globalThis.bootstrap.Modal
                            .getOrCreateInstance(dialog)
                            .show();
                    }
                }).catch(() => {
                    globalThis.localStorage.removeItem(
                        LAST_GENERATION_OPERATION_KEY,
                    );
                });
            }
        } catch {
            globalThis.localStorage.removeItem(
                LAST_GENERATION_OPERATION_KEY,
            );
        }
    }
}
