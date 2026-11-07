import { translate } from "./locale.js";

function responseMessage(document, fallbackKey) {
    const key = document?.error?.message_key ?? fallbackKey;
    return translate(key, document?.error?.details ?? {});
}

function showOutcome(element, message, successful) {
    element.textContent = message;
    element.className = successful
        ? "alert alert-success"
        : "alert alert-danger";
    element.setAttribute("role", successful ? "status" : "alert");
    element.focus();
}

export function mountAvailableFiles(root, fetchRequest = globalThis.fetch) {
    const confirmButton = root.querySelector("[data-clear-confirm]");
    const dialogElement = root.querySelector("[data-clear-dialog]");
    if (!confirmButton || !dialogElement) {
        return null;
    }

    const outcome = root.querySelector("[data-clear-outcome]");
    const fileList = root.querySelector("[data-file-list]");
    const emptyState = root.querySelector("[data-file-empty]");
    const dialog = globalThis.bootstrap.Modal.getOrCreateInstance(dialogElement);
    let clearing = false;

    async function clearDownloads() {
        if (clearing) {
            return;
        }
        clearing = true;
        confirmButton.disabled = true;
        confirmButton.textContent = confirmButton.dataset.busyLabel;

        try {
            const response = await fetchRequest(root.dataset.clearEndpoint, {
                method: "POST",
                headers: { Accept: "application/json" },
            });
            const document = await response.json();
            if (!response.ok) {
                throw new Error(responseMessage(
                    document,
                    "errors.downloads.clear_failed",
                ));
            }

            fileList.classList.add("d-none");
            emptyState.classList.remove("d-none");
            showOutcome(
                outcome,
                translate("available_files.clear.success"),
                true,
            );
            dialog.hide();
        } catch (error) {
            const message = error instanceof Error
                ? error.message
                : translate("errors.downloads.clear_failed");
            showOutcome(outcome, message, false);
            dialog.hide();
        } finally {
            clearing = false;
            confirmButton.disabled = false;
            confirmButton.textContent = confirmButton.dataset.idleLabel;
        }
    }

    confirmButton.addEventListener("click", clearDownloads);
    return { clearDownloads };
}

const root = document.querySelector("[data-available-files]");
if (root) {
    mountAvailableFiles(root);
}
