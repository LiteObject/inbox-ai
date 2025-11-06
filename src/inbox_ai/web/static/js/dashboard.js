import { SpinnerController } from "./modules/spinner.js";
import { ToastManager } from "./modules/toast.js";
import { DialogManager } from "./modules/dialog.js";
import { installScrollRestore } from "./modules/scroll.js";
import ListDetailController from "./modules/list-detail.js";
import { installEmailListSearch } from "./modules/search.js";

const AVAILABLE_THEMES = ["default", "plant", "dark", "high-contrast", "vibrant"];
const THEME_STORAGE_KEY = "dashboard.theme";

function resolveInitialTheme() {
    let storedTheme = null;
    try {
        storedTheme = window.localStorage?.getItem(THEME_STORAGE_KEY) ?? null;
    } catch (error) {
        storedTheme = null;
    }

    if (storedTheme && AVAILABLE_THEMES.includes(storedTheme)) {
        return storedTheme;
    }

    if (window.matchMedia?.("(prefers-color-scheme: dark)")?.matches) {
        return "dark";
    }

    return "default";
}

document.documentElement.setAttribute("data-theme", resolveInitialTheme());

class ThemeManager {
    constructor(initialTheme) {
        this.validThemes = AVAILABLE_THEMES;
        this.storageKey = THEME_STORAGE_KEY;
        this.currentTheme = null;
        this.applyTheme(initialTheme ?? resolveInitialTheme(), { persist: false });
    }

    applyTheme(theme, options = {}) {
        if (!this.validThemes.includes(theme)) {
            return;
        }

        document.documentElement.setAttribute("data-theme", theme);
        this.currentTheme = theme;

        if (options.persist !== false) {
            try {
                window.localStorage?.setItem(this.storageKey, theme);
            } catch (error) {
                console.warn("Unable to persist theme selection", error);
            }
        }

        this.updateActiveControls();
        window.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
    }

    setTheme(theme) {
        this.applyTheme(theme);
    }

    updateActiveControls() {
        const buttons = document.querySelectorAll("[data-theme-select]");
        if (!buttons.length) {
            return;
        }
        buttons.forEach((button) => {
            const isActive = button.dataset.themeSelect === this.currentTheme;
            button.classList.toggle("active", isActive);
        });
    }
}

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

function installSpinnerForms(spinner, toastManager, dialogManager) {
    const forms = document.querySelectorAll("form[data-spinner]:not([data-spinner-bound='true'])");
    forms.forEach((form) => {
        form.setAttribute("data-spinner-bound", "true");
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
            event.preventDefault();

            const submitter = event.submitter ?? lastSubmitter ?? submitButtons[0] ?? null;
            lastSubmitter = null;

            const confirmMessage = submitter?.dataset.confirm ?? form.dataset.confirm;
            if (confirmMessage) {
                const confirmed = await dialogManager.confirm(confirmMessage, 'Confirm Action', 'Delete', 'Cancel');
                if (!confirmed) {
                    return;
                }
            }

            if (!window.fetch) {
                form.submit();
                return;
            }
            const spinnerLabel = submitter?.dataset.spinnerLabel ?? form.dataset.spinnerLabel;
            spinner.show(spinnerLabel);

            try {
                const formData = new FormData(form);

                // Get the action URL - ensure it's properly resolved to an absolute URL
                let action = submitter?.formAction || form.action;
                if (!action || action === window.location.href) {
                    action = form.getAttribute('action');
                    if (action) {
                        // Resolve relative URL to absolute URL
                        action = new URL(action, window.location.href).href;
                    } else {
                        action = window.location.href;
                    }
                }

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

function installSettingsNavigation() {
    const settingsButton = document.getElementById("settings-button");
    if (!settingsButton) {
        return;
    }

    const target = settingsButton.dataset.href || "/settings";

    const navigateToSettings = (event) => {
        if (event?.metaKey || event?.ctrlKey || event?.shiftKey) {
            window.open(target, "_blank", "noopener,noreferrer");
            return;
        }

        event?.preventDefault?.();
        queueToastsForNavigation(target);
        window.location.href = target;
    };

    settingsButton.addEventListener("click", (event) => {
        navigateToSettings(event);
    });

    settingsButton.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " " || event.key === "Spacebar" || event.key === "Space") {
            navigateToSettings(event);
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const themeManager = new ThemeManager(document.documentElement.getAttribute("data-theme"));
    window.themeManager = themeManager;

    const themeButtons = document.querySelectorAll("[data-theme-select]");
    themeButtons.forEach((button) => {
        button.addEventListener("click", () => {
            themeManager.setTheme(button.dataset.themeSelect);
        });
    });
    themeManager.updateActiveControls();

    const toastManager = new ToastManager({
        container: document.getElementById("toast-container"),
        dataset: document.getElementById("toast-data"),
    });
    toastManager.hydrateFromDataset();
    consumeStoredToasts(toastManager);

    const spinner = new SpinnerController({
        overlay: document.getElementById("sync-spinner"),
        messageElement: document.getElementById("spinner-message"),
        onTimeout: () => {
            toastManager.show("Request timed out. Please try again.", "error");
        },
    });
    spinner.hide();

    const dialogManager = new DialogManager();

    const bindInteractiveForms = () => {
        installSpinnerForms(spinner, toastManager, dialogManager);
        installScrollRestore({
            forms: document.querySelectorAll("form[data-scroll-restore]"),
            storageKey: "dashboard-scroll",
        });
    };

    bindInteractiveForms();

    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            spinner.hide();
        }
    });

    installSettingsNavigation();

    const listDetailContainer = document.querySelector('.list-detail-container');
    const emailList = document.getElementById('email-list');
    const detailHost = document.getElementById('detail-content');
    const templateContainer = document.getElementById('detail-templates');

    if (listDetailContainer && emailList && detailHost && templateContainer) {
        window.listDetailController = new ListDetailController({
            container: listDetailContainer,
            list: emailList,
            detailHost,
            templateContainer,
            onDetailChanged: () => {
                bindInteractiveForms();
            },
        });

        const visibleCountTargets = document.querySelectorAll('#insights-visible-count, #insights-visible-count-2');

        installEmailListSearch({
            input: document.getElementById('insights-search'),
            list: emailList,
            visibleCount: visibleCountTargets,
            emptyNotice: document.getElementById('insights-filter-empty'),
        });
    }
});
