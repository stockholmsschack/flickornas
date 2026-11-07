import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

function moduleUrl(source) {
    return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}

const root = new URL("../../", import.meta.url);
const script = (name) => readFile(new URL(`flickornas_standings/web/static/js/${name}`, root), "utf8");
const catalogue = JSON.parse(await readFile(new URL("flickornas_standings/web/locales/en.json", root), "utf8"));
// html() constructs the bundled renderer's real TemplateResults. Importing it
// needs a tree walker; template construction itself does not need a browser DOM.
globalThis.document = {
    createTreeWalker: () => ({}),
    getElementById: (id) => id === "group-names-help" && { getAttribute: () => "/tools/flickornas/help/group-names" },
};
const litUrl = moduleUrl(await script("lit-html.js"));
const localeUrl = moduleUrl(`
const catalogue = ${JSON.stringify(catalogue)};
export function translate(key, params = {}) {
    return (catalogue[key] ?? key).replace(/\\{([^{}]+)\\}/g, (match, name) =>
        Object.hasOwn(params, name) ? params[name] : match);
}`);
const source = (await script("klass-naming.js"))
    .replace('"./lit-html.js"', `"${litUrl}"`)
    .replace('"./locale.js"', `"${localeUrl}"`);
const { problemList } = await import(moduleUrl(source));

function escaped(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderedTemplate(value) {
    if (value == null || typeof value === "symbol") {
        return "";
    }
    if (Array.isArray(value)) {
        return value.map(renderedTemplate).join("");
    }
    if (typeof value === "object" && value.strings) {
        return value.strings.map((part, index) => part + (
            index < value.values.length ? renderedTemplate(value.values[index]) : ""
        )).join("");
    }
    return escaped(value);
}

const names = ["Klass Minior", 'Minior Nybörjare <script>"&'];
const problems = names.map((name, index) => ({
    field: "tournaments",
    message_key: `errors.klass_naming.${index ? "several_klasses" : "ambiguous_klass"}`,
    parameters: { tournament_id: 100, tournament_name: "Test tournament", group_id: 101 + index, group_name: name },
}));
const output = renderedTemplate(problemList(problems));
assert.equal((output.match(/<li>/g) ?? []).length, 2);
for (const name of names) {
    assert.ok(output.includes(`<code>${escaped(name)}</code>`));
}
assert.ok(output.includes("Rename these groups"));
assert.ok(output.includes("remove the age description"));
assert.ok(output.includes("member system and try again"));
assert.ok(output.includes('href="/tools/flickornas/help/group-names"'));
assert.ok(!output.includes("<script>"));
assert.equal(renderedTemplate(problemList([])), "");
const mixed = renderedTemplate(problemList([...problems, {
    field: "tournaments", message_key: "errors.generation.tournament_unresolvable",
    parameters: { tournament_id: 123 },
}]));
assert.equal((mixed.match(/<li>/g) ?? []).length, 3);

// Both UI callers use this renderer for request errors; background failures and
// defaults use it too, preserving the same list across the operation lifecycle.
const generation = await script("generation-form.js");
assert.ok(generation.includes("problemList(error.problems)"));
assert.ok(generation.includes("problemList(event.parameters?.problems)"));
const search = await script("tournament-search.js");
assert.ok(search.includes("problemList(state.problems)"));
assert.ok(search.includes("error.problems = payload.error?.details?.problems ?? []"));

const { TournamentSelectionState } = await import(moduleUrl(await script("tournament-search-state.js")));
const selection = new TournamentSelectionState({
    lookup: async () => {
        const error = new Error("Naming refusal");
        error.messageKey = "errors.klass_naming.heading";
        error.problems = problems;
        throw error;
    },
});
await selection.verifyTournamentId("100");
assert.equal(selection.state.status, "failure");
assert.deepEqual(selection.state.problems, problems);
assert.equal(selection.state.selectedTournaments.length, 0);
selection.clear();
assert.deepEqual(selection.state.problems, []);
console.log("Naming problem rendering and selection failure tests passed.");

// Exercise the callers with controlled elements and request responses, using
// their real event handlers and native lit templates without network access.
const rendererUrl = moduleUrl(`
export { html, nothing } from "${litUrl}";
export function render(template, element) { element.template = template; }
`);
const namingUrl = moduleUrl(source);
function element() {
    return {
        dataset: {}, value: "", textContent: "", className: "", disabled: false,
        listeners: {}, attributes: {},
        classList: { toggle() {} },
        addEventListener(name, listener) { this.listeners[name] = listener; },
        setAttribute(name, value) { this.attributes[name] = value; },
        querySelector() { return null; },
        reportValidity() { return true; },
    };
}
function elementRoot() {
    const elements = new Map();
    const rootElement = element();
    rootElement.querySelector = (selector) => {
        if (!elements.has(selector)) elements.set(selector, element());
        return elements.get(selector);
    };
    return { rootElement, elements };
}
function failureResponse() {
    return { ok: false, json: async () => ({ error: {
        message_key: "errors.klass_naming.heading", code: "klass_naming",
        details: { problems },
    } }) };
}
async function settleUi() {
    await new Promise((resolve) => setImmediate(resolve));
}
const globalListeners = {};
globalThis.addEventListener = (name, listener) => { globalListeners[name] = listener; };
globalThis.dispatchEvent = () => {};
globalThis.CustomEvent = class { constructor(name, options) { this.type = name; this.detail = options.detail; } };
globalThis.localStorage = { getItem: () => null, removeItem() {}, setItem() {} };
globalThis.bootstrap = {
    Modal: class { show() {} hide() {} },
    Toast: class { show() {} },
};
const generationFixture = elementRoot();
const generationRoot = generationFixture.rootElement;
const generationElements = generationFixture.elements;
generationRoot.dataset.configurationRevision = "7";
generationRoot.dataset.defaultsEndpoint = "/defaults";
generationRoot.dataset.startEndpoint = "/start";
const selectGenerationElement = generationRoot.querySelector;
generationRoot.querySelector = (selector) => selector === "[data-generation-explicit-tournaments]"
    ? null : selectGenerationElement(selector);
globalThis.document.querySelector = (selector) => selector === "[data-generation-form]" ? generationRoot : null;
globalThis.document.querySelectorAll = () => [];
globalThis.document.getElementById = () => null;
const operationMemoryUrl = moduleUrl(await script("generation-operation-memory.js"));
const inputStateUrl = moduleUrl(await script("generation-input-state.js"));
const followUrl = moduleUrl('export function followOperation() { return { close() {} }; }');
const mountStubUrl = moduleUrl('export function mountTournamentSearch() { throw new Error("Picker should not mount here"); }');
const generationSource = generation
    .replace('"./lit-html.js"', `"${rendererUrl}"`)
    .replace('"./locale.js"', `"${localeUrl}"`)
    .replace('"./klass-naming.js"', `"${namingUrl}"`)
    .replace('"./generation-operation-memory.js"', `"${operationMemoryUrl}"`)
    .replace('"./generation-input-state.js"', `"${inputStateUrl}"`)
    .replace('"./operation-stream.js"', `"${followUrl}"`)
    .replace('"./tournament-search.js"', `"${mountStubUrl}"`);
await import(moduleUrl(generationSource));
let defaultsCalls = 0;
globalThis.fetch = async () => { defaultsCalls += 1; return failureResponse(); };
generationRoot.listeners["show.bs.modal"]();
await settleUi();
const defaultsElement = generationElements.get("[data-generation-defaults-status]");
assert.equal((renderedTemplate(defaultsElement.template).match(/<li>/g) ?? []).length, 2);
assert.equal(generationElements.get("[data-start-generation]").disabled, true);
assert.ok(generationElements.get("[data-generation-submit-hint]").textContent.includes("Rename"));
globalThis.fetch = async () => {
    defaultsCalls += 1;
    return { ok: true, json: async () => ({ data: { current_year: 2026, configuration_revision: 7, tournaments: [] } }) };
};
generationRoot.listeners["show.bs.modal"]();
await settleUi();
assert.equal(defaultsCalls, 2, "reopening retries failed defaults");
assert.equal(generationElements.get("[data-start-generation]").disabled, false);
globalThis.fetch = async () => failureResponse();
generationElements.get("[data-generation-input-form]").listeners.submit({ preventDefault() {} });
await settleUi();
const generationStatus = generationElements.get("[data-generation-status]");
assert.equal((renderedTemplate(generationStatus.template).match(/<li>/g) ?? []).length, 2);
assert.ok(renderedTemplate(generationStatus.template).includes("<code>Klass Minior</code>"));
// A terminal operation loaded from its durable response uses the same list.
globalThis.fetch = async () => ({ ok: true, json: async () => ({ data: {
    operation_id: "abc", state: "failed", terminal: true, latest_event_id: 2,
    status_url: "/operation/abc", failure_stage: "validation", events: [{
        event_id: 2, kind: "failed", message_key: "operations.failed",
        parameters: { stage: "validation", problems }, progress: {},
    }],
} }) });
generationElements.get("[data-generation-input-form]").listeners.submit({ preventDefault() {} });
await settleUi();
assert.ok(renderedTemplate(generationStatus.template).includes("<code>Klass Minior</code>"));
assert.ok(renderedTemplate(generationStatus.template).includes("member system and try again"));

// Saved PDF settings must re-enable generation without changing tournament selections.
const submitButton = generationElements.get("[data-start-generation]");
const completed = {
    operation_id: "done", state: "completed", terminal: true, latest_event_id: 3,
    effective_year: 2026, configuration_revision: 7, tournament_ids: [],
    layout: generationElements.get("[data-generation-layout]").value,
    status_url: "/operation/done", links: { pdf: "/pdf", files: "/files" },
    events: [{ event_id: 3, kind: "completed", message_key: "operations.completed", parameters: {} }],
};
async function submitOperation(operation) {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ data: operation }) });
    generationElements.get("[data-generation-input-form]").listeners.submit({ preventDefault() {} });
    await settleUi();
}
await submitOperation(completed);
assert.equal(submitButton.disabled, true, "same saved inputs stay blocked");
globalListeners["flickornas:configuration-revision-changed"]({ detail: { revision: 8 } });
assert.equal(submitButton.disabled, false, "saved separator or metadata change enables Generate");
assert.equal(generationElements.get("[data-generation-submit-hint]").textContent, "");
await submitOperation({ ...completed, configuration_revision: 8 });
assert.equal(submitButton.disabled, true, "new completed revision stays blocked");
globalListeners["flickornas:configuration-revision-changed"]({ detail: { revision: 8 } });
assert.equal(submitButton.disabled, true, "no-op save stays blocked");
await submitOperation({ ...completed, configuration_revision: 8, state: "running", terminal: false });
globalListeners["flickornas:configuration-revision-changed"]({ detail: { revision: 9 } });
assert.equal(submitButton.disabled, true, "configuration changes cannot bypass an active run");

const stateUrl = moduleUrl(await script("tournament-search-state.js"));
const pickerSource = (await script("tournament-picker.js"))
    .replace('"./tournament-search-state.js"', `"${stateUrl}"`);
const pickerUrl = moduleUrl(pickerSource);
const searchSource = search
    .replace('"./lit-html.js"', `"${rendererUrl}"`)
    .replace('"./locale.js"', `"${localeUrl}"`)
    .replace('"./klass-naming.js"', `"${namingUrl}"`)
    .replace('"./tournament-picker.js"', `"${pickerUrl}"`)
    .replace('"./tournament-search-state.js"', `"${stateUrl}"`);
const { mountTournamentSearch } = await import(moduleUrl(searchSource));
const searchFixture = elementRoot();
searchFixture.rootElement.dataset.tournamentConsumer = "run";
searchFixture.rootElement.dataset.lookupEndpointTemplate = "/lookup/__tournament_id__";
searchFixture.rootElement.querySelector("[data-tournament-id-form]").tagName = "FORM";
const searchPicker = mountTournamentSearch(searchFixture.rootElement, []);
globalThis.fetch = async () => failureResponse();
await searchPicker.verifyTournamentId("100");
assert.equal(searchPicker.value.tournaments.length, 0);
for (const selector of ["[data-tournament-selection]", "[data-tournament-selection-toast-message]"]) {
    const rendered = renderedTemplate(searchFixture.elements.get(selector).template);
    assert.equal((rendered.match(/<li>/g) ?? []).length, 2);
    assert.ok(rendered.includes("<code>Klass Minior</code>"));
    assert.ok(rendered.includes("remove the age description"));
}
console.log("Generation defaults, submission, failed operations and lookup UI tests passed.");
