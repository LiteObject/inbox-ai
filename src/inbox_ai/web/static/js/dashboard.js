import { SpinnerController } from "./modules/spinner.js";
import { ToastManager } from "./modules/toast.js";
import { installScrollRestore } from "./modules/scroll.js";
import { installInsightSearch } from "./modules/search.js";

function installSpinnerForms(spinner, toastManager) {
    const forms = document.querySelectorAll("form[data-spinner]");
    forms.forEach((form) => {
        const submitButton = form.querySelector("button[type='submit'], button:not([type])");
        if (submitButton) {
            spinner.registerButton(submitButton);
        }

        form.addEventListener("submit", async (event) => {
            const confirmMessage = form.dataset.confirm;
            if (confirmMessage && !window.confirm(confirmMessage)) {
                event.preventDefault();
                return;
            }

            if (!window.fetch) {
                return;
            }

            event.preventDefault();
            spinner.show(form.dataset.spinnerLabel);

            try {
                const formData = new FormData(form);
                const method = (form.method || "post").toUpperCase();

                if (form.action.endsWith("/sync")) {
                    const response = await fetch(form.action, {
                        method,
                        body: formData,
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }

                    const reader = response.body?.getReader();
                    if (!reader) {
                        throw new Error("Streaming response not supported");
                    }
                    const decoder = new TextDecoder();
                    let buffer = "";

                    // Stream Server-Sent Events and update spinner messaging.
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) {
                            break;
                        }
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split("\n");
                        buffer = lines.pop() ?? "";
                        for (const line of lines) {
                            if (!line.startsWith("data: ")) {
                                continue;
                            }
                            const data = line.slice(6);
                            if (data.startsWith("redirect:")) {
                                window.location.href = data.slice(9);
                                return;
                            }
                            spinner.show(data || form.dataset.spinnerLabel);
                        }
                    }
                    spinner.hide();
                } else {
                    const response = await fetch(form.action, {
                        method,
                        body: formData,
                        redirect: "follow",
                    });

                    const targetUrl = response.url || formData.get("redirect_to") || "/";
                    window.location.href = targetUrl;
                }
            } catch (error) {
                console.error("Request failed", error);
                spinner.hide();
                toastManager.show("Request failed. Please try again.", "error");
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const spinner = new SpinnerController({
        overlay: document.getElementById("sync-spinner"),
        messageElement: document.getElementById("spinner-message"),
        onTimeout: () => {
            toastManager.show("Request timed out. Please try again.", "error");
        },
    });
    spinner.hide();

    const toastManager = new ToastManager({
        container: document.getElementById("toast-container"),
        dataset: document.getElementById("toast-data"),
    });
    toastManager.hydrateFromDataset();

    installSpinnerForms(spinner, toastManager);

    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            spinner.hide();
        }
    });

    installScrollRestore({
        forms: document.querySelectorAll("form[data-scroll-restore]"),
        storageKey: "dashboard-scroll",
    });

    installInsightSearch({
        input: document.getElementById("insights-search"),
        grid: document.getElementById("insights-grid"),
        visibleCount: document.getElementById("insights-visible-count"),
        emptyNotice: document.getElementById("insights-filter-empty"),
    });
});
