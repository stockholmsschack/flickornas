import { html, render } from "./lit-html.js";
import { translate } from "./locale.js";
import {
    playerFullName,
    PlayerOverrideEditorState,
} from "./player-override-editor-state.js";

function playerDisplayName(player) {
    return playerFullName(player) ?? translate(
        "player_overrides.player_id",
        { id: player.player_id },
    );
}

function overrideTemplate(override, requestRemoval, operation) {
    const player = override.player;
    const disabled = operation !== null;
    const disabledReason = disabled
        ? translate("player_overrides.saving")
        : "";
    return html`
        <li
            class="list-group-item d-flex align-items-center gap-3"
            data-player-override-id=${player.player_id}
        >
            <span class="flex-grow-1">
                <span class="fw-semibold">${playerDisplayName(player)}</span>
                <span class="text-body-secondary ms-2">
                    ${override.club.name}
                </span>
            </span>
            <button
                class="btn btn-outline-danger btn-sm"
                type="button"
                aria-label=${translate("player_overrides.remove_label", {
                    name: playerDisplayName(player),
                })}
                ?disabled=${disabled}
                title=${disabledReason}
                @click=${function handleRemovalRequest() {
                    requestRemoval(override);
                }}
            >
                ${translate("player_overrides.remove")}
            </button>
        </li>
    `;
}

async function saveOverrides(
    endpoint,
    revision,
    knownLocalPlayers,
    knownLocalPlayerNames,
) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            revision,
            known_local_players: knownLocalPlayers,
            known_local_player_names: knownLocalPlayerNames,
        }),
    });
    const payload = await response.json();
    if (!response.ok) {
        const error = new Error("Player override configuration save failed");
        error.messageKey = payload.error?.message_key;
        throw error;
    }
    return payload.data;
}

function showToast(elements, outcome) {
    let messageKey = "errors.player_overrides.invalid_selection";
    let parameters = {};
    if (outcome.status === "added") {
        messageKey = "player_overrides.added";
        parameters = {
            name: playerFullName(outcome.override.player),
            club: outcome.override.club.name,
        };
    } else if (outcome.status === "replaced") {
        messageKey = "player_overrides.replaced";
        parameters = {
            name: playerFullName(outcome.override.player),
            club: outcome.override.club.name,
        };
    } else if (outcome.status === "removed") {
        messageKey = "player_overrides.removed";
        parameters = {
            name: playerDisplayName(outcome.overrides[0].player),
        };
    } else if (outcome.status === "removed_all") {
        messageKey = "player_overrides.removed_all";
    } else if (outcome.status === "unchanged") {
        messageKey = "player_overrides.unchanged";
        parameters = {
            name: playerFullName(outcome.override.player),
            club: outcome.override.club.name,
        };
    }
    elements.toastMessage.textContent = translate(messageKey, parameters);
    elements.toast.show();
}

const root = document.querySelector("[data-player-override-editor]");
if (root) {
    const collection = root.querySelector("[data-player-overrides]");
    const playerSelector = root.querySelector("[data-player-name-selector]");
    const clubSelector = root.querySelector("[data-club-selector]");
    const saveButton = root.querySelector("[data-save-player-override]");
    const saveStatus = root.querySelector(
        "[data-player-override-save-status]",
    );
    const removeAllButton = root.querySelector(
        "[data-remove-all-player-overrides]",
    );
    const countSummary = document.querySelector(
        "[data-configuration-known-player-count]",
    );
    const removalDialogElement = root.querySelector(
        "[data-player-override-removal-dialog]",
    );
    const removalHeading = root.querySelector(
        "[data-player-override-removal-heading]",
    );
    const removalDescription = root.querySelector(
        "[data-player-override-removal-description]",
    );
    const removalNames = root.querySelector(
        "[data-player-override-removal-names]",
    );
    const confirmRemovalButton = root.querySelector(
        "[data-confirm-player-override-removal]",
    );
    const toastElement = root.querySelector("[data-player-override-toast]");
    const toastMessage = root.querySelector(
        "[data-player-override-toast-message]",
    );
    const initialData = document.getElementById(
        "selected-player-overrides-data",
    );
    const initialOverrides = initialData
        ? JSON.parse(initialData.textContent)
        : [];
    let configurationRevision = Number(root.dataset.configurationRevision);
    const removalDialog = new globalThis.bootstrap.Modal(removalDialogElement);
    const toast = new globalThis.bootstrap.Toast(toastElement, { delay: 8000 });
    const toastElements = { toastElement, toastMessage, toast };
    let pendingRemoval = null;
    let operation = null;
    let outcomeMessageKey = null;
    let resettingSelectors = false;

    function saveReason(state) {
        if (operation !== null) {
            return "player_overrides.saving";
        }
        if (state.selectedPlayer === null) {
            return "player_overrides.select_player";
        }
        if (state.selectedClub === null) {
            return "player_overrides.select_club";
        }
        return null;
    }

    function renderState(state) {
        const reason = saveReason(state);
        saveButton.disabled = reason !== null;
        saveButton.title = reason ? translate(reason) : "";
        const statusKeys = [outcomeMessageKey, reason].filter(
            (key, index, keys) => key !== null && keys.indexOf(key) === index,
        );
        saveStatus.textContent = statusKeys
            .map(function translateStatus(key) {
                return translate(key);
            })
            .join(" ");
        saveStatus.dataset.saveState = operation === null ? "idle" : "saving";
        removeAllButton.disabled = (
            state.overrides.length === 0 || operation !== null
        );
        removeAllButton.title = operation === null
            ? ""
            : translate("player_overrides.saving");
        confirmRemovalButton.disabled = operation !== null;
        collection.dataset.overrideCount = String(state.overrides.length);
        render(
            state.overrides.length === 0
                ? html`<div class="alert alert-secondary mb-0">
                    ${translate("player_overrides.empty")}
                </div>`
                : html`<ul class="list-group">
                    ${state.overrides.map(function renderOverride(override) {
                        return overrideTemplate(
                            override,
                            requestOneRemoval,
                            operation,
                        );
                    })}
                </ul>`,
            collection,
        );
        if (countSummary) {
            countSummary.textContent = state.overrides.length === 0
                ? translate("configuration.none")
                : String(state.overrides.length);
        }
    }

    const editor = new PlayerOverrideEditorState({
        initialOverrides,
        onChange: renderState,
    });

    function requestOneRemoval(override) {
        if (operation !== null) {
            return;
        }
        pendingRemoval = {
            kind: "one",
            playerId: override.player.player_id,
        };
        removalHeading.textContent = translate(
            "player_overrides.remove_heading",
        );
        removalDescription.textContent = translate(
            "player_overrides.remove_confirmation",
        );
        removalNames.textContent = playerDisplayName(override.player);
        confirmRemovalButton.textContent = translate(
            "player_overrides.remove",
        );
        removalDialog.show();
    }

    function requestAllRemoval() {
        if (editor.state.overrides.length === 0 || operation !== null) {
            return;
        }
        pendingRemoval = { kind: "all" };
        removalHeading.textContent = translate(
            "player_overrides.remove_all_heading",
        );
        removalDescription.textContent = translate(
            "player_overrides.remove_all_confirmation",
        );
        removalNames.textContent = editor.state.overrides
            .map(function overridePlayerName(override) {
                return playerDisplayName(override.player);
            })
            .join(", ");
        confirmRemovalButton.textContent = translate(
            "player_overrides.remove_all",
        );
        removalDialog.show();
    }

    function resetSelectors() {
        resettingSelectors = true;
        playerSelector.dispatchEvent(
            new CustomEvent("flickornas:player-selector-reset"),
        );
        clubSelector.dispatchEvent(
            new CustomEvent("flickornas:club-selector-reset"),
        );
        resettingSelectors = false;
    }

    async function persistMutation(mutate, resetAfterSave = false) {
        if (operation !== null) {
            return;
        }
        const previousOverrides = editor.draftValue();
        operation = "saving";
        outcomeMessageKey = "player_overrides.saving";
        const outcome = mutate();
        if (outcome.status === "failure") {
            operation = null;
            outcomeMessageKey = null;
            renderState(editor.state);
            return;
        }
        renderState(editor.state);
        try {
            const saved = await saveOverrides(
                root.dataset.saveEndpoint,
                configurationRevision,
                editor.value(),
                editor.names(),
            );
            configurationRevision = saved.revision;
            root.dataset.configurationRevision = String(saved.revision);
            if (resetAfterSave) {
                outcomeMessageKey = "player_overrides.saved";
                resetSelectors();
            } else {
                outcomeMessageKey = null;
            }
            showToast(toastElements, outcome);
            globalThis.dispatchEvent(new CustomEvent(
                "flickornas:configuration-revision-changed",
                {
                    detail: {
                        revision: saved.revision,
                        source: root,
                    },
                },
            ));
        } catch (error) {
            editor.replaceOverrides(previousOverrides);
            outcomeMessageKey = error?.messageKey ?? "errors.internal";
        } finally {
            operation = null;
            renderState(editor.state);
        }
    }

    root.addEventListener(
        "flickornas:player-selection-changed",
        function selectPlayer(event) {
            if (!resettingSelectors) {
                outcomeMessageKey = null;
            }
            if (event.detail.value === null) {
                editor.clearPlayerSelection();
                return;
            }
            editor.selectPlayer(event.detail.value);
            clubSelector.querySelector("input")?.focus();
        },
    );
    root.addEventListener(
        "flickornas:club-selection-changed",
        function selectClub(event) {
            if (!resettingSelectors) {
                outcomeMessageKey = null;
            }
            if (event.detail.value === null) {
                editor.clearClubSelection();
                return;
            }
            editor.selectClub(event.detail.value);
            saveButton.focus();
        },
    );
    saveButton.addEventListener("click", function savePlayer() {
        if (saveReason(editor.state) !== null) {
            renderState(editor.state);
            return;
        }
        persistMutation(() => editor.addOverride(), true);
    });
    removeAllButton.addEventListener("click", requestAllRemoval);
    confirmRemovalButton.addEventListener(
        "click",
        function confirmRemoval() {
            if (pendingRemoval === null || operation !== null) {
                return;
            }
            const removal = pendingRemoval;
            pendingRemoval = null;
            removalDialog.hide();
            persistMutation(
                () => removal.kind === "all"
                    ? editor.removeAllOverrides()
                    : editor.removeOverride(removal.playerId),
            );
        },
    );
    removalDialogElement.addEventListener(
        "hidden.bs.modal",
        function clearPendingRemoval() {
            pendingRemoval = null;
            removalNames.textContent = "";
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
    renderState(editor.state);
}
