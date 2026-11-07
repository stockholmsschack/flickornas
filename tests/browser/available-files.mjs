import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

globalThis.document = { querySelector: () => null };

const localeSource = `
export function translate(key) {
    return {
        "available_files.clear.success": "All downloads were cleared.",
        "errors.downloads.clear_failed": "Downloads could not be cleared.",
        "errors.downloads.operation_busy": "Another operation is running.",
    }[key] ?? key;
}`;
const localeUrl = `data:text/javascript;base64,${Buffer.from(localeSource).toString("base64")}`;
const source = (
    await readFile(
        new URL(
            "../../flickornas_standings/web/static/js/available-files.js",
            import.meta.url,
        ),
        "utf8",
    )
).replace('"./locale.js"', `"${localeUrl}"`);

class ClassList {
    constructor(classes = []) {
        this.classes = new Set(classes);
    }

    add(name) {
        this.classes.add(name);
    }

    remove(name) {
        this.classes.delete(name);
    }

    contains(name) {
        return this.classes.has(name);
    }
}

function element(classes = []) {
    return {
        classList: new ClassList(classes),
        className: "",
        dataset: {},
        disabled: false,
        textContent: "",
        attributes: {},
        listeners: {},
        addEventListener(kind, listener) {
            this.listeners[kind] = listener;
        },
        setAttribute(name, value) {
            this.attributes[name] = value;
        },
        focus() {
            this.focused = true;
        },
    };
}

function fixture() {
    const confirm = element();
    confirm.dataset.idleLabel = "Clear downloads";
    confirm.dataset.busyLabel = "Clearing downloads…";
    confirm.textContent = confirm.dataset.idleLabel;
    const elements = {
        "[data-clear-confirm]": confirm,
        "[data-clear-dialog]": element(),
        "[data-clear-outcome]": element(["d-none"]),
        "[data-file-list]": element(),
        "[data-file-empty]": element(["d-none"]),
    };
    return {
        elements,
        root: {
            dataset: { clearEndpoint: "/api/v1/downloads/clear" },
            querySelector(selector) {
                return elements[selector] ?? null;
            },
        },
    };
}

const dialogs = [];
globalThis.bootstrap = {
    Modal: {
        getOrCreateInstance() {
            const dialog = { hidden: 0, hide() { this.hidden += 1; } };
            dialogs.push(dialog);
            return dialog;
        },
    },
};

const { mountAvailableFiles } = await import(
    `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const successful = fixture();
let releaseRequest;
let requestCount = 0;
const pendingResponse = new Promise((resolve) => {
    releaseRequest = resolve;
});
const controller = mountAvailableFiles(successful.root, async (url, options) => {
    requestCount += 1;
    assert.equal(url, "/api/v1/downloads/clear");
    assert.equal(options.method, "POST");
    return pendingResponse;
});

const first = controller.clearDownloads();
const duplicate = controller.clearDownloads();
assert.equal(requestCount, 1);
assert.equal(successful.elements["[data-clear-confirm]"].disabled, true);
releaseRequest({ ok: true, json: async () => ({ data: { cleared: true } }) });
await Promise.all([first, duplicate]);
assert.equal(successful.elements["[data-file-list]"].classList.contains("d-none"), true);
assert.equal(successful.elements["[data-file-empty]"].classList.contains("d-none"), false);
assert.equal(successful.elements["[data-clear-outcome]"].textContent, "All downloads were cleared.");
assert.equal(successful.elements["[data-clear-confirm]"].disabled, false);
assert.equal(dialogs[0].hidden, 1);

const failed = fixture();
const failedController = mountAvailableFiles(failed.root, async () => ({
    ok: false,
    json: async () => ({
        error: { message_key: "errors.downloads.operation_busy", details: {} },
    }),
}));
await failedController.clearDownloads();
assert.equal(failed.elements["[data-file-list]"].classList.contains("d-none"), false);
assert.equal(failed.elements["[data-file-empty]"].classList.contains("d-none"), true);
assert.equal(failed.elements["[data-clear-outcome]"].textContent, "Another operation is running.");
assert.equal(failed.elements["[data-clear-outcome]"].attributes.role, "alert");
assert.equal(failed.elements["[data-clear-confirm]"].disabled, false);
assert.equal(dialogs[1].hidden, 1);
