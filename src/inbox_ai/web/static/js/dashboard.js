import { SpinnerController } from "./modules/spinner.js";
import { ToastManager } from "./modules/toast.js";
import { installScrollRestore } from "./modules/scroll.js";
import { installInsightSearch } from "./modules/search.js";

const TOAST_STORAGE_KEY = "dashboard.pendingToasts";
const STATUS_PARAM_PAIRS = [
    ["sync_status", "sync_message"],
    ["delete_status", "delete_message"],
    ["categorize_status", "categorize_message"],
    ["draft_status", "draft_message"],
    ["config_status", "config_message"],
    ["clear_status", "clear_message"],
];

function queueToastsForNavigation(targetUrl) {
    if (!window.sessionStorage || !targetUrl) {
        return;
    }

    let parsedUrl;
    try {
        parsedUrl = new URL(targetUrl, window.location.href);
    } catch (error) {
        console.warn("Unable to parse redirect URL for toast handling", error);
        return;
    }

    // If the target URL already has status params, let hydrateFromDataset handle it
    const hasStatusParams = STATUS_PARAM_PAIRS.some(([statusKey, messageKey]) => {
        return parsedUrl.searchParams.has(statusKey) && parsedUrl.searchParams.has(messageKey);
    });
    if (hasStatusParams) {
        return;
    }

    const pending = [];
    STATUS_PARAM_PAIRS.forEach(([statusKey, messageKey]) => {
        const status = parsedUrl.searchParams.get(statusKey);
        const message = parsedUrl.searchParams.get(messageKey);
        if (status && message) {
            const variant = status === "ok" ? "success" : "error";
            pending.push({ message, variant });
        }
    });

    if (pending.length === 0) {
        return;
    }

    try {
        const existingRaw = window.sessionStorage.getItem(TOAST_STORAGE_KEY);
        const existing = existingRaw ? JSON.parse(existingRaw) : [];
        const next = Array.isArray(existing) ? existing.concat(pending) : pending;
        window.sessionStorage.setItem(TOAST_STORAGE_KEY, JSON.stringify(next));
    } catch (error) {
        console.warn("Unable to persist toast notifications", error);
    }
}

function consumeStoredToasts(toastManager) {
    if (!window.sessionStorage) {
        return;
    }
    let stored = null;
    try {
        stored = window.sessionStorage.getItem(TOAST_STORAGE_KEY);
    } catch (error) {
        console.warn("Unable to read stored toast notifications", error);
        return;
    }

    if (!stored) {
        return;
    }

    window.sessionStorage.removeItem(TOAST_STORAGE_KEY);
    let payload;
    try {
        payload = JSON.parse(stored);
    } catch (error) {
        console.warn("Unable to parse stored toast notifications", error);
        return;
    }

    if (!Array.isArray(payload) || payload.length === 0) {
        return;
    }

    payload.forEach((toast, index) => {
        if (toast && typeof toast.message === "string") {
            const variant = toast.variant || "info";
            window.setTimeout(() => {
                toastManager.show(toast.message, variant);
            }, index * 240);
        }
    });
}

function installSpinnerForms(spinner, toastManager) {
    const forms = document.querySelectorAll("form[data-spinner]");
    forms.forEach((form) => {
        const submitButtons = form.querySelectorAll("button[type='submit'], button:not([type])");
        let lastSubmitter = null;
        submitButtons.forEach((button) => {
            spinner.registerButton(button);
            const trackSubmitter = () => {
                lastSubmitter = button;
            };
            button.addEventListener("click", trackSubmitter);
            button.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    trackSubmitter();
                }
            });
        });

        form.addEventListener("submit", async (event) => {
            const submitter = event.submitter ?? lastSubmitter ?? submitButtons[0] ?? null;
            lastSubmitter = null;
            const confirmMessage = submitter?.dataset.confirm ?? form.dataset.confirm;
            if (confirmMessage && !window.confirm(confirmMessage)) {
                event.preventDefault();
                return;
            }

            if (!window.fetch) {
                return;
            }

            event.preventDefault();
            const spinnerLabel = submitter?.dataset.spinnerLabel ?? form.dataset.spinnerLabel;
            spinner.show(spinnerLabel);

            try {
                const formData = new FormData(form);
                const action = submitter?.formAction || form.action || window.location.href;
                const method = (submitter?.formMethod || form.method || "post").toUpperCase();

                if (action.endsWith("/sync")) {
                    const response = await fetch(action, {
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
                    const response = await fetch(action, {
                        method,
                        body: formData,
                        redirect: "follow",
                    });

                    const targetUrl = response.url || formData.get("redirect_to") || "/";
                    if (response.redirected || targetUrl) {
                        queueToastsForNavigation(targetUrl);
                    }
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
    consumeStoredToasts(toastManager);

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
