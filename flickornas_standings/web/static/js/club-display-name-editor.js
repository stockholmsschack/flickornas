import { html, render } from "./lit-html.js";
import { loadClubs, mountClubSelector } from "./club-selector.js";
import { translate } from "./locale.js";

async function saveChange(endpoint, revision, change) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision, ...change }),
    });
    const payload = await response.json();
    if (!response.ok) {
        const error = new Error("Club display name save failed");
        error.messageKey = payload.error?.message_key;
        throw error;
    }
    return payload.data;
}

function sortedAliases(aliases) {
    return Object.entries(aliases).sort(function compareAliases(left, right) {
        return left[0].localeCompare(right[0]);
    });
}

const root = document.querySelector("[data-club-display-name-editor]");
if (root) {
    const list = root.querySelector("[data-club-display-name-list]");
    const listStatus = root.querySelector(
        "[data-club-display-name-list-status]",
    );
    const selector = root.querySelector(
        "[data-club-display-name-selector]",
    );
    const newDisplayName = root.querySelector(
        "[data-new-club-display-name]",
    );
    const addButton = root.querySelector("[data-add-club-display-name]");
    const addStatus = root.querySelector("[data-club-display-name-status]");
    const countSummary = document.querySelector(
        "[data-configuration-club-alias-count]",
    );
    const initialData = document.getElementById("club-display-names-data");
    let aliases = initialData ? JSON.parse(initialData.textContent) : {};
    let selectedClub = null;
    let editingCanonicalName = null;
    let editedDisplayName = "";
    let configurationRevision = Number(root.dataset.configurationRevision);
    let operation = null;
    let outcome = null;

    function editingReason(canonicalName) {
        if (operation !== null) {
            return "club_display_names.saving";
        }
        const value = editedDisplayName.trim();
        if (value === "") {
            return "club_display_names.short_name_required";
        }
        if (value === aliases[canonicalName]) {
            return "club_display_names.unchanged";
        }
        return null;
    }

    function viewAliasTemplate(canonicalName, displayName) {
        const actionsDisabled = (
            operation !== null || editingCanonicalName !== null
        );
        let disabledReason = "";
        if (operation !== null) {
            disabledReason = translate("club_display_names.saving");
        } else if (editingCanonicalName !== null) {
            disabledReason = translate("club_display_names.finish_edit");
        }
        return html`
            <div class="border rounded p-3 mb-3">
                <div class="row g-3 align-items-center">
                    <div class="col-md">
                        <div class="fw-semibold">${canonicalName}</div>
                        <div>${displayName}</div>
                    </div>
                    <div class="col-md-auto">
                        <button
                            class="btn btn-outline-primary"
                            type="button"
                            ?disabled=${actionsDisabled}
                            title=${disabledReason}
                            @click=${function beginEdit() {
                                editingCanonicalName = canonicalName;
                                editedDisplayName = displayName;
                                outcome = null;
                                renderList();
                                list.querySelector(
                                    "[data-edited-club-display-name]",
                                )?.focus();
                            }}
                        >
                            ${translate("club_display_names.edit")}
                        </button>
                        <button
                            class="btn btn-outline-danger ms-2"
                            type="button"
                            ?disabled=${actionsDisabled}
                            title=${disabledReason}
                            @click=${function removeAlias() {
                                persist({
                                    action: "remove",
                                    canonical_name: canonicalName,
                                }, "list");
                            }}
                        >
                            ${translate("club_display_names.remove")}
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    function editAliasTemplate(canonicalName) {
        const reason = editingReason(canonicalName);
        return html`
            <div class="border rounded p-3 mb-3">
                <div class="fw-semibold mb-2">${canonicalName}</div>
                <div class="row g-2 align-items-start">
                    <div class="col-md">
                        <label class="form-label">
                            ${translate("club_display_names.short_name")}
                            <input
                                class="form-control mt-1"
                                type="text"
                                maxlength="200"
                                .value=${editedDisplayName}
                                ?disabled=${operation !== null}
                                data-edited-club-display-name
                                @input=${function updateEditedName(event) {
                                    editedDisplayName = event.currentTarget.value;
                                    outcome = null;
                                    renderList();
                                }}
                            >
                        </label>
                        <div class="form-text">
                            ${reason ? translate(reason) : ""}
                        </div>
                    </div>
                    <div class="col-md-auto pt-md-4">
                        <button
                            class="btn btn-primary"
                            type="button"
                            ?disabled=${reason !== null}
                            title=${reason ? translate(reason) : ""}
                            @click=${function saveAlias() {
                                persist({
                                    action: "upsert",
                                    canonical_name: canonicalName,
                                    display_name: editedDisplayName,
                                }, "list");
                            }}
                        >
                            ${translate("club_display_names.save")}
                        </button>
                        <button
                            class="btn btn-secondary ms-2"
                            type="button"
                            ?disabled=${operation !== null}
                            @click=${function cancelEdit() {
                                editingCanonicalName = null;
                                editedDisplayName = "";
                                outcome = null;
                                renderList();
                            }}
                        >
                            ${translate("club_display_names.cancel")}
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    function renderList() {
        const entries = sortedAliases(aliases);
        render(
            entries.length === 0
                ? html`<div class="alert alert-secondary">
                    ${translate("club_display_names.empty")}
                </div>`
                : html`${entries.map(function renderAlias(entry) {
                    const [canonicalName, displayName] = entry;
                    if (editingCanonicalName === canonicalName) {
                        return editAliasTemplate(canonicalName);
                    }
                    return viewAliasTemplate(canonicalName, displayName);
                })}`,
            list,
        );
        if (countSummary) {
            countSummary.textContent = entries.length === 0
                ? translate("configuration.none")
                : String(entries.length);
        }
        listStatus.textContent = outcome?.scope === "list"
            ? translate(outcome.messageKey)
            : "";
    }

    function addReason() {
        if (operation !== null) {
            return "club_display_names.another_change";
        }
        if (editingCanonicalName !== null) {
            return "club_display_names.finish_edit";
        }
        if (selectedClub === null) {
            return "club_display_names.select_club";
        }
        if (Object.hasOwn(aliases, selectedClub.name)) {
            return "club_display_names.already_configured";
        }
        if (newDisplayName.value.trim() === "") {
            return "club_display_names.short_name_required";
        }
        return null;
    }

    function renderAddState() {
        const reason = addReason();
        addButton.disabled = reason !== null;
        newDisplayName.disabled = operation !== null;
        addButton.title = reason ? translate(reason) : "";
        addStatus.textContent = outcome?.scope === "add"
            ? translate(outcome.messageKey)
            : (reason ? translate(reason) : "");
    }

    async function persist(change, scope) {
        if (operation !== null) {
            return;
        }
        operation = { scope };
        outcome = {
            scope,
            messageKey: "club_display_names.saving",
        };
        renderList();
        renderAddState();
        try {
            const saved = await saveChange(
                root.dataset.saveEndpoint,
                configurationRevision,
                change,
            );
            configurationRevision = saved.revision;
            root.dataset.configurationRevision = String(saved.revision);
            aliases = saved.club_display_names;
            if (scope === "add") {
                selectedClub = null;
                newDisplayName.value = "";
                selector.dispatchEvent(new CustomEvent(
                    "flickornas:club-selector-reset",
                ));
            } else {
                editingCanonicalName = null;
                editedDisplayName = "";
            }
            outcome = {
                scope,
                messageKey: change.action === "remove"
                    ? "club_display_names.removed"
                    : "club_display_names.saved",
            };
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
            outcome = {
                scope,
                messageKey: error?.messageKey ?? "errors.internal",
            };
        } finally {
            operation = null;
            renderList();
            renderAddState();
        }
    }

    root.addEventListener(
        "flickornas:club-selection-changed",
        function selectClub(event) {
            const previousClub = selectedClub;
            selectedClub = event.detail.value;
            if (selectedClub === null && previousClub !== null) {
                newDisplayName.value = "";
            }
            if (operation === null && outcome?.scope === "add") {
                outcome = null;
            }
            renderAddState();
            if (selectedClub !== null) {
                newDisplayName.focus();
            }
        },
    );
    newDisplayName.addEventListener("input", function updateNewName() {
        if (outcome?.scope === "add") {
            outcome = null;
        }
        renderAddState();
    });
    addButton.addEventListener("click", function addAlias() {
        if (addReason() !== null) {
            renderAddState();
            return;
        }
        persist({
            action: "upsert",
            canonical_name: selectedClub.name,
            display_name: newDisplayName.value,
        }, "add");
    });
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

    mountClubSelector({
        renderTarget: selector,
        lookup() {
            return loadClubs(root.dataset.clubsEndpoint);
        },
        translations: translate,
    });
    renderList();
    renderAddState();
}
