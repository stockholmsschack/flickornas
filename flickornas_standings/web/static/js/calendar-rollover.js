import { html, render } from "./lit-html.js";
import { problemList } from "./klass-naming.js";
import { translate } from "./locale.js";

const root = document.querySelector("[data-calendar-rollover]");

async function changeRollover(endpoint, method, revision) {
    const response = await fetch(endpoint, {
        method,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ revision }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error("Calendar rollover request failed");
        error.messageKey = payload.error?.message_key ?? "errors.internal";
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
}

if (root) {
    const startButton = root.querySelector("[data-start-calendar-rollover]");
    const cancelButton = root.querySelector("[data-cancel-calendar-rollover]");
    const status = root.querySelector("[data-calendar-rollover-status]");
    const revision = Number(root.dataset.configurationRevision);
    const button = startButton ?? cancelButton;

    button?.addEventListener("click", async function handleRollover() {
        button.disabled = true;
        render("", status);
        try {
            await changeRollover(
                startButton
                    ? root.dataset.startEndpoint
                    : root.dataset.cancelEndpoint,
                startButton ? "POST" : "DELETE",
                revision,
            );
            globalThis.location.reload();
        } catch (error) {
            render(html`
                ${error.problems?.length ? "" : translate(error?.messageKey ?? "errors.internal")}
                ${problemList(error.problems)}
            `, status);
            button.disabled = false;
        }
    });

    globalThis.addEventListener(
        "flickornas:calendar-rollover-completed",
        function hideCompletedRollover() {
            root.hidden = true;
        },
    );
}
