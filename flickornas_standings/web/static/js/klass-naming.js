import { html, nothing } from "./lit-html.js";
import { translate } from "./locale.js";

function isNamingProblem(problem) {
    return problem?.message_key?.startsWith("errors.klass_naming.") ?? false;
}

function problemMessage(problem) {
    if (typeof problem === "string") {
        return problem;
    }
    const parameters = problem.parameters ?? {};
    if (!isNamingProblem(problem)) {
        return translate(problem.message_key ?? "errors.generation.invalid_input", parameters);
    }
    // Leave the group placeholder intact so lit-html can render the exact name
    // as escaped code, without interpreting upstream text as HTML.
    const { group_name: groupName, ...otherParameters } = parameters;
    const parts = translate(problem.message_key, otherParameters)
        .split("{group_name}");
    return html`${parts.map(function messagePart(part, index) {
        return html`${index > 0 ? html`<code>${groupName}</code>` : nothing}${part}`;
    })}`;
}

export function problemList(problems = []) {
    if (problems.length === 0) {
        return nothing;
    }
    const hasNamingProblems = problems.some(isNamingProblem);
    return html`
        ${hasNamingProblems
            ? html`<div class="fw-semibold">${translate("errors.klass_naming.heading")}</div>`
            : nothing}
        <ul class="mb-0">
            ${problems.map(function problemItem(problem) {
                return html`<li>${problemMessage(problem)}</li>`;
            })}
        </ul>
        ${hasNamingProblems
            ? html`
                <p class="mt-2 mb-1">${translate("klass_naming.retry")}</p>
                <a class="alert-link" href="${document.getElementById("group-names-help")?.getAttribute("href")}" target="_blank" rel="noopener noreferrer">
                    ${translate("klass_naming.help_link")}
                </a>
            `
            : nothing}
    `;
}
