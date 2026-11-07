import { translate } from "./locale.js";

async function saveContributor(endpoint, revision, contributor) {
    const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision, ...contributor }),
    });
    const payload = await response.json();
    if (!response.ok) {
        const error = new Error("Contributor configuration save failed");
        error.messageKey = payload.error?.message_key;
        throw error;
    }
    return payload.data;
}

const root = document.querySelector("[data-contributor-editor]");
if (root) {
    const form = root.querySelector("[data-contributor-form]");
    const nameInput = root.querySelector("[data-contributor-name]");
    const emailInput = root.querySelector("[data-contributor-email]");
    const clearNameButton = root.querySelector(
        "[data-clear-contributor-name]",
    );
    const clearEmailButton = root.querySelector(
        "[data-clear-contributor-email]",
    );
    const saveButton = root.querySelector("[data-save-contributor]");
    const status = root.querySelector("[data-contributor-save-status]");
    const summary = document.querySelector(
        "[data-configuration-contributor-summary]",
    );
    const defaults = {
        name: root.dataset.defaultName,
        email: root.dataset.defaultEmail,
    };
    let configurationRevision = Number(root.dataset.configurationRevision);
    let savedContributor = effectiveContributor();
    let saving = false;
    let outcomeMessageKey = null;

    function effectiveContributor() {
        return {
            name: nameInput.value.trim() || defaults.name,
            email: emailInput.value.trim() || defaults.email,
        };
    }

    function hasChanges(contributor) {
        return (
            contributor.name !== savedContributor.name
            || contributor.email !== savedContributor.email
        );
    }

    function clearButtonTitle(input) {
        if (saving) {
            return translate("contributor.saving");
        }
        return input.value === ""
            ? translate("contributor.already_clear")
            : "";
    }

    function renderState() {
        const valid = form.checkValidity();
        const changed = hasChanges(effectiveContributor());
        saveButton.disabled = saving || !valid || !changed;
        clearNameButton.disabled = saving || nameInput.value === "";
        clearEmailButton.disabled = saving || emailInput.value === "";
        if (saving) {
            status.textContent = translate("contributor.saving");
        } else if (!valid) {
            status.textContent = translate("contributor.invalid_email");
        } else if (outcomeMessageKey !== null) {
            status.textContent = translate(outcomeMessageKey);
        } else if (!changed) {
            status.textContent = translate("contributor.unchanged");
        } else {
            status.textContent = "";
        }
        saveButton.title = saveButton.disabled ? status.textContent : "";
        clearNameButton.title = clearButtonTitle(nameInput);
        clearEmailButton.title = clearButtonTitle(emailInput);
    }

    function clearInput(input) {
        input.value = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
    }

    form.addEventListener("input", function handleInput() {
        outcomeMessageKey = null;
        form.classList.toggle("was-validated", !form.checkValidity());
        renderState();
    });
    clearNameButton.addEventListener("click", function clearName() {
        clearInput(nameInput);
    });
    clearEmailButton.addEventListener("click", function clearEmail() {
        clearInput(emailInput);
    });
    form.addEventListener("submit", async function handleSubmit(event) {
        event.preventDefault();
        if (saving || !form.checkValidity()) {
            form.classList.add("was-validated");
            renderState();
            return;
        }
        const contributor = effectiveContributor();
        if (!hasChanges(contributor)) {
            renderState();
            return;
        }
        saving = true;
        renderState();
        try {
            const saved = await saveContributor(
                root.dataset.saveEndpoint,
                configurationRevision,
                contributor,
            );
            configurationRevision = saved.revision;
            root.dataset.configurationRevision = String(saved.revision);
            savedContributor = saved.contributor;
            outcomeMessageKey = "contributor.saved";
            if (summary) {
                summary.textContent = (
                    `${saved.contributor.name} <${saved.contributor.email}>`
                );
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
    renderState();
}
