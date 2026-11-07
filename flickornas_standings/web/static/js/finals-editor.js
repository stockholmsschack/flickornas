import { translate } from "./locale.js";

const DEFAULT_FIELD_COUNT = 3;

async function saveFinalsSeparators(endpoint, revision, separators) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision, finals_separators: separators }),
    });
    const payload = await response.json();
    if (!response.ok) {
        const error = new Error("Finals separator save failed");
        error.messageKey = payload.error?.message_key;
        throw error;
    }
    return payload.data;
}

function sameSeparators(left, right) {
    return (
        left.length === right.length
        && left.every((value, index) => value === right[index])
    );
}

const root = document.querySelector("[data-finals-editor]");
if (root) {
    const form = root.querySelector("[data-finals-form]");
    const list = root.querySelector("[data-finals-separator-list]");
    const addButton = root.querySelector("[data-add-finals-separator]");
    const clearAllButton = root.querySelector(
        "[data-clear-all-finals-separators]",
    );
    const saveButton = root.querySelector("[data-save-finals]");
    const status = root.querySelector("[data-finals-save-status]");
    const summary = document.querySelector(
        "[data-configuration-finals-summary]",
    );
    const dataElement = document.getElementById("finals-separators-data");
    let savedSeparators = dataElement
        ? JSON.parse(dataElement.textContent)
        : [];
    let configurationRevision = Number(root.dataset.configurationRevision);
    let saving = false;
    let outcomeMessageKey = null;
    let nextFieldId = 0;

    function inputs() {
        return [...list.querySelectorAll("[data-finals-separator]")];
    }

    function addField(value = "") {
        nextFieldId += 1;
        const id = `finals-separator-${nextFieldId}`;
        const row = document.createElement("div");
        row.className = "input-group";
        row.dataset.finalsSeparatorRow = "";

        const label = document.createElement("label");
        label.className = "input-group-text";
        label.htmlFor = id;
        label.textContent = translate("finals.row");

        const input = document.createElement("input");
        input.className = "form-control";
        input.id = id;
        input.type = "number";
        input.min = "1";
        input.step = "1";
        input.inputMode = "numeric";
        input.value = String(value);
        input.dataset.finalsSeparator = "";

        const clearButton = document.createElement("button");
        clearButton.className = "btn btn-outline-secondary";
        clearButton.type = "button";
        clearButton.textContent = translate("finals.clear");
        clearButton.setAttribute("aria-label", translate("finals.clear_row"));
        clearButton.dataset.clearFinalsSeparator = "";

        const removeButton = document.createElement("button");
        removeButton.className = "btn btn-outline-secondary";
        removeButton.type = "button";
        removeButton.textContent = "×";
        removeButton.setAttribute("aria-label", translate("finals.remove"));
        removeButton.title = translate("finals.remove");
        removeButton.dataset.removeFinalsSeparator = "";

        row.append(label, input, clearButton, removeButton);
        list.append(row);
        return input;
    }

    // Returns the sorted separators, or null when any field is invalid.
    function enteredSeparators() {
        const values = [];
        let valid = true;
        for (const input of inputs()) {
            const text = input.value.trim();
            const value = Number(text);
            const fieldValid = (
                input.validity.valid
                && (
                    text === ""
                    || (Number.isInteger(value) && value >= 1
                        && !values.includes(value))
                )
            );
            input.classList.toggle("is-invalid", !fieldValid);
            valid &&= fieldValid;
            if (fieldValid && text !== "") {
                values.push(value);
            }
        }
        return valid ? values.sort((left, right) => left - right) : null;
    }

    function renderState() {
        const separators = enteredSeparators();
        const changed = (
            separators !== null
            && !sameSeparators(separators, savedSeparators)
        );
        const allClear = inputs().every((input) => input.value === "");
        saveButton.disabled = saving || !changed;
        addButton.disabled = saving;
        clearAllButton.disabled = saving || allClear;
        clearAllButton.title = saving
            ? translate("finals.saving")
            : allClear ? translate("finals.all_clear") : "";
        for (const control of list.querySelectorAll("input, button")) {
            control.disabled = saving;
        }
        for (const input of inputs()) {
            const clearButton = input.parentElement.querySelector(
                "[data-clear-finals-separator]",
            );
            clearButton.disabled = saving || input.value === "";
            clearButton.title = saving
                ? translate("finals.saving")
                : input.value === "" ? translate("finals.already_clear") : "";
        }
        if (saving) {
            status.textContent = translate("finals.saving");
        } else if (separators === null) {
            status.textContent = translate("finals.invalid");
        } else if (outcomeMessageKey !== null) {
            status.textContent = translate(outcomeMessageKey);
        } else if (!changed) {
            status.textContent = translate("finals.unchanged");
        } else {
            status.textContent = "";
        }
        saveButton.title = saveButton.disabled ? status.textContent : "";
    }

    function renderFields(separators) {
        list.replaceChildren();
        for (const value of separators) {
            addField(value);
        }
        for (let count = separators.length; count < DEFAULT_FIELD_COUNT; count += 1) {
            addField();
        }
    }

    form.addEventListener("input", function handleInput() {
        outcomeMessageKey = null;
        renderState();
    });
    list.addEventListener("click", function clearOrRemoveSeparator(event) {
        const clearButton = event.target.closest(
            "[data-clear-finals-separator]",
        );
        if (clearButton && !saving) {
            const input = clearButton.parentElement.querySelector(
                "[data-finals-separator]",
            );
            input.value = "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
            return;
        }
        const button = event.target.closest("[data-remove-finals-separator]");
        if (!button || saving) {
            return;
        }
        button.closest("[data-finals-separator-row]").remove();
        outcomeMessageKey = null;
        renderState();
        (inputs().at(-1) ?? addButton).focus();
    });
    addButton.addEventListener("click", function addSeparator() {
        addField().focus();
        outcomeMessageKey = null;
        renderState();
    });
    clearAllButton.addEventListener("click", function clearAllSeparators() {
        if (saving) {
            return;
        }
        renderFields([]);
        outcomeMessageKey = null;
        renderState();
        inputs()[0]?.focus();
    });
    form.addEventListener("submit", async function handleSubmit(event) {
        event.preventDefault();
        const separators = enteredSeparators();
        if (
            saving
            || separators === null
            || sameSeparators(separators, savedSeparators)
        ) {
            renderState();
            return;
        }
        saving = true;
        renderState();
        try {
            const saved = await saveFinalsSeparators(
                root.dataset.saveEndpoint,
                configurationRevision,
                separators,
            );
            configurationRevision = saved.revision;
            root.dataset.configurationRevision = String(saved.revision);
            savedSeparators = saved.finals_separators;
            renderFields(savedSeparators);
            outcomeMessageKey = "finals.saved";
            if (summary) {
                summary.textContent = savedSeparators.length
                    ? savedSeparators.join(", ")
                    : translate("configuration.none");
            }
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
            outcomeMessageKey = error?.messageKey ?? "errors.internal";
        } finally {
            saving = false;
            renderState();
        }
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
    globalThis.addEventListener(
        "flickornas:calendar-rollover-completed",
        function adoptRolloverReset() {
            savedSeparators = [];
            renderFields(savedSeparators);
            outcomeMessageKey = null;
            if (summary) {
                summary.textContent = translate("configuration.none");
            }
            renderState();
        },
    );
    renderFields(savedSeparators);
    renderState();
}
