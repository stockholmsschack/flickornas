const summary = document.querySelector("[data-configuration-summary]");

if (summary) {
    summary.addEventListener("click", function openConfigurationTab(event) {
        const link = event.target.closest("[data-configuration-tab-link]");
        if (
            !link
            || event.button !== 0
            || event.ctrlKey
            || event.metaKey
            || event.shiftKey
            || event.altKey
        ) {
            return;
        }

        const tab = document.getElementById(link.dataset.configurationTabLink);
        if (!tab) {
            return;
        }

        event.preventDefault();
        tab.click();
        tab.scrollIntoView({ behavior: "smooth", block: "start" });
    });
}
