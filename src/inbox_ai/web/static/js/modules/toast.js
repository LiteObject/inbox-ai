const DEFAULT_STATUS_KEYS = [
    "sync_status",
    "sync_message",
    "delete_status",
    "delete_message",
    "categorize_status",
    "categorize_message",
    "config_status",
    "draft_status",
    "draft_message",
    "config_message",
    "clear_status",
    "clear_message",
];

function dismissToast(element) {
    if (!element) {
        return;
    }
    element.classList.remove("show");
    window.setTimeout(() => {
        if (element.parentNode) {
            element.parentNode.removeChild(element);
        }
    }, 220);
}

export class ToastManager {
    constructor({ container, dataset, statusKeys = DEFAULT_STATUS_KEYS } = {}) {
        this.container = container ?? null;
        this.datasetElement = dataset ?? null;
        this.statusKeys = statusKeys;
    }

    show(message, variant = "info", duration = 5000) {
        if (!this.container || !message) {
            return;
        }

        const toast = document.createElement("div");
        toast.className = `toast${variant ? ` ${variant}` : ""}`;
        toast.setAttribute("role", "status");
        toast.setAttribute("aria-live", "assertive");

        const text = document.createElement("div");
        text.className = "toast-message";
        text.textContent = message;

        const close = document.createElement("button");
        close.type = "button";
        close.setAttribute("aria-label", "Dismiss notification");
        close.innerHTML = "&times;";

        toast.appendChild(text);
        toast.appendChild(close);
        this.container.appendChild(toast);

        window.requestAnimationFrame(() => {
            toast.classList.add("show");
        });

        const hideDelay = typeof duration === "number" ? duration : 5000;
        const timer = window.setTimeout(() => dismissToast(toast), hideDelay);

        close.addEventListener("click", () => {
            window.clearTimeout(timer);
            dismissToast(toast);
        });
    }

    hydrateFromDataset() {
        if (!this.datasetElement) {
            return;
        }
        const pending = [];
        const mapVariant = (status) => (status === "ok" ? "success" : "error");
        const dataset = this.datasetElement.dataset;
        const pairs = [
            ["syncStatus", "syncMessage"],
            ["deleteStatus", "deleteMessage"],
            ["categorizeStatus", "categorizeMessage"],
            ["draftStatus", "draftMessage"],
            ["configStatus", "configMessage"],
            ["clearStatus", "clearMessage"],
        ];

        pairs.forEach(([statusKey, messageKey]) => {
            const status = (dataset[statusKey] || "").trim();
            const message = (dataset[messageKey] || "").trim();
            if (status && message) {
                pending.push({
                    message,
                    variant: mapVariant(status),
                });
            }
        });

        pending.forEach((toast, index) => {
            window.setTimeout(() => {
                this.show(toast.message, toast.variant);
            }, index * 240);
        });

        if (pending.length > 0) {
            this.clearStatusQueryParams();
        }
    }

    clearStatusQueryParams(keys = this.statusKeys) {
        if (!window.history || !window.history.replaceState || !window.URL) {
            return;
        }
        const currentUrl = new URL(window.location.href);
        let removed = false;
        keys.forEach((key) => {
            if (currentUrl.searchParams.has(key)) {
                currentUrl.searchParams.delete(key);
                removed = true;
            }
        });
        if (removed) {
            const nextUrl = `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`;
            window.history.replaceState({}, document.title, nextUrl);
        }
    }
}

export default ToastManager;
