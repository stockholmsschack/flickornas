import { translate } from "./locale.js";

const root = document.querySelector("[data-rules-file-editor]");
if (root) {
    const form = root.querySelector("[data-rules-file-form]");
    const input = root.querySelector("[data-rules-file-input]");
    const uploadButton = root.querySelector("[data-upload-rules-file]");
    const restoreButton = root.querySelector("[data-restore-rules-file]");
    const status = root.querySelector("[data-rules-file-status]");
    let hasCustomRules = root.dataset.hasCustomRules === "true";
    let operation = null;
    let outcomeMessageKey = null;

    function selectedFile() {
        return input.files[0] ?? null;
    }

    function renderState() {
        const hasFile = selectedFile() !== null;
        input.disabled = operation !== null;
        uploadButton.disabled = operation !== null || !hasFile;
        restoreButton.disabled = operation !== null || !hasCustomRules;
        if (operation === "uploading") {
            status.textContent = translate("rules_file.uploading");
        } else if (operation === "restoring") {
            status.textContent = translate("rules_file.restoring");
        } else if (outcomeMessageKey !== null) {
            status.textContent = translate(outcomeMessageKey);
        } else if (hasFile) {
            status.textContent = "";
        } else if (hasCustomRules) {
            status.textContent = translate("rules_file.custom_active");
        } else {
            status.textContent = translate("rules_file.original_active");
        }
        uploadButton.title = uploadButton.disabled
            ? translate(
                operation === null
                    ? "rules_file.select"
                    : `rules_file.${operation}`,
            )
            : "";
        restoreButton.title = restoreButton.disabled
            ? status.textContent
            : "";
    }

    input.addEventListener("change", function handleFileSelection() {
        outcomeMessageKey = null;
        renderState();
    });

    form.addEventListener("submit", async function handleUpload(event) {
        event.preventDefault();
        if (operation !== null || selectedFile() === null) {
            renderState();
            return;
        }
        operation = "uploading";
        renderState();
        const body = new FormData();
        body.append("rules", selectedFile());
        try {
            const response = await fetch(root.dataset.uploadEndpoint, {
                method: "POST",
                body,
            });
            const payload = await response.json();
            if (!response.ok) {
                const error = new Error("Rules file upload failed");
                error.messageKey = payload.error?.message_key;
                throw error;
            }
            input.value = "";
            hasCustomRules = true;
            outcomeMessageKey = "rules_file.uploaded";
        } catch (error) {
            outcomeMessageKey = error?.messageKey ?? "errors.internal";
        } finally {
            operation = null;
            renderState();
        }
    });

    restoreButton.addEventListener("click", async function handleRestore() {
        if (operation !== null || !hasCustomRules) {
            renderState();
            return;
        }
        operation = "restoring";
        outcomeMessageKey = null;
        renderState();
        try {
            const response = await fetch(root.dataset.uploadEndpoint, {
                method: "DELETE",
            });
            const payload = await response.json();
            if (!response.ok) {
                const error = new Error("Rules file restore failed");
                error.messageKey = payload.error?.message_key;
                throw error;
            }
            hasCustomRules = false;
            outcomeMessageKey = "rules_file.restored";
        } catch (error) {
            outcomeMessageKey = error?.messageKey ?? "errors.internal";
        } finally {
            operation = null;
            renderState();
        }
    });

    renderState();
}
