const catalogueElement = document.getElementById("locale-catalogue");
const catalogue = catalogueElement
    ? JSON.parse(catalogueElement.textContent)
    : {};

export function translate(key, parameters = {}) {
    const template = catalogue[key] ?? key;
    return template.replace(
        /\{([^{}]+)\}/g,
        function replaceParameter(match, name) {
            return Object.hasOwn(parameters, name) ? parameters[name] : match;
        },
    );
}

const localeForm = document.getElementById("locale-choice")?.form;
if (localeForm) {
    localeForm.addEventListener("submit", async function prepareNavigation(event) {
        event.preventDefault();
        const pending = [];
        globalThis.dispatchEvent(new CustomEvent(
            "flickornas:before-navigation",
            {
                detail: {
                    waitUntil(promise) {
                        pending.push(Promise.resolve(promise));
                    },
                },
            },
        ));
        await Promise.allSettled(pending);
        localeForm.submit();
    });
}
