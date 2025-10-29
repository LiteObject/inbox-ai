document.addEventListener("DOMContentLoaded", () => {
    const spinnerOverlay = document.getElementById("sync-spinner");
    const spinnerMessage = document.getElementById("spinner-message");
    const defaultSpinnerText = spinnerMessage ? spinnerMessage.textContent : "";
    const toastContainer = document.getElementById("toast-container");
    const toastDataset = document.getElementById("toast-data");
    const insightsSearch = document.getElementById("insights-search");
    const insightsGrid = document.getElementById("insights-grid");
    const visibleCount = document.getElementById("insights-visible-count");
    const emptyNotice = document.getElementById("insights-filter-empty");
    const scrollStorageKey = "dashboard-scroll";

    const spinnerButtons = [];

    function hideSpinner() {
        if (spinnerOverlay) {
            spinnerOverlay.hidden = true;
        }
        spinnerButtons.forEach((button) => {
            if (button) {
                button.disabled = false;
            }
        });
        if (spinnerMessage) {
            spinnerMessage.textContent = defaultSpinnerText;
        }
    }

    function showSpinner(label) {
        if (spinnerOverlay) {
            spinnerOverlay.hidden = false;
        }
        if (spinnerMessage) {
            spinnerMessage.textContent = label || defaultSpinnerText;
        }
        spinnerButtons.forEach((button) => {
            if (button) {
                button.disabled = true;
            }
        });
    }

    hideSpinner();

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

    function showToast(message, variant, duration) {
        if (!toastContainer || !message) {
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
        toastContainer.appendChild(toast);

        window.requestAnimationFrame(() => {
            toast.classList.add("show");
        });

        const hideDelay = typeof duration === "number" ? duration : 5000;
        const hideTimer = window.setTimeout(() => {
            dismissToast(toast);
        }, hideDelay);

        close.addEventListener("click", () => {
            window.clearTimeout(hideTimer);
            dismissToast(toast);
        });
    }

    function clearStatusQueryParams() {
        if (!window.history || !window.history.replaceState || !window.URL) {
            return;
        }
        const currentUrl = new URL(window.location.href);
        const statusKeys = [
            "sync_status",
            "sync_message",
            "delete_status",
            "delete_message",
            "categorize_status",
            "categorize_message",
            "config_status",
        ];
        let removed = false;
        statusKeys.forEach((key) => {
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

    function hydrateToasts() {
        if (!toastDataset) {
            return;
        }

        const pendingToasts = [];
        const mapVariant = (status) => (status === "ok" ? "success" : "error");
        /** @type {[string, string][]} */
        const statusPairs = [
            ["syncStatus", "syncMessage"],
            ["deleteStatus", "deleteMessage"],
            ["categorizeStatus", "categorizeMessage"],
        ];

        statusPairs.forEach(([statusKey, messageKey]) => {
            const status = (toastDataset.dataset[statusKey] || "").trim();
            const message = (toastDataset.dataset[messageKey] || "").trim();
            if (status && message) {
                pendingToasts.push({
                    message,
                    variant: mapVariant(status),
                });
            }
        });

        pendingToasts.forEach((toast, index) => {
            window.setTimeout(() => {
                showToast(toast.message, toast.variant);
            }, index * 240);
        });

        if (pendingToasts.length > 0) {
            clearStatusQueryParams();
        }
    }

    hydrateToasts();

    function installSpinnerForms() {
        const forms = document.querySelectorAll("form[data-spinner]");
        forms.forEach((form) => {
            const submitButton = form.querySelector("button[type='submit'], button:not([type])");
            if (submitButton) {
                spinnerButtons.push(submitButton);
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
                showSpinner(form.dataset.spinnerLabel);

                try {
                    const formData = new FormData(form);
                    const method = (form.method || "post").toUpperCase();
                    const response = await fetch(form.action, {
                        method,
                        body: formData,
                        redirect: "follow",
                    });

                    const targetUrl = response.url || formData.get("redirect_to") || "/";
                    window.location.href = targetUrl;
                } catch (error) {
                    console.error("Request failed", error);
                    hideSpinner();
                    showToast("Request failed. Please try again.", "error");
                }
            });
        });
    }

    installSpinnerForms();

    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            hideSpinner();
        }
    });

    function installScrollRestore() {
        const forms = document.querySelectorAll("form[data-scroll-restore]");
        forms.forEach((form) => {
            form.addEventListener("submit", () => {
                try {
                    const position = {
                        x: window.pageXOffset || document.documentElement.scrollLeft || 0,
                        y: window.pageYOffset || document.documentElement.scrollTop || 0,
                    };
                    sessionStorage.setItem(scrollStorageKey, JSON.stringify(position));
                } catch (error) {
                    console.warn("Unable to persist scroll position", error);
                }
            });
        });

        try {
            const stored = sessionStorage.getItem(scrollStorageKey);
            if (!stored) {
                return;
            }
            sessionStorage.removeItem(scrollStorageKey);
            const parsed = JSON.parse(stored);
            if (
                parsed &&
                Number.isFinite(parsed.x) &&
                Number.isFinite(parsed.y)
            ) {
                window.scrollTo({ left: parsed.x, top: parsed.y, behavior: "auto" });
            }
        } catch (error) {
            console.warn("Unable to restore scroll position", error);
        }
    }

    installScrollRestore();

    function installInsightSearch() {
        if (!insightsSearch || !insightsGrid) {
            return;
        }
        const cards = Array.prototype.slice.call(
            insightsGrid.querySelectorAll(".insight-card")
        );
        cards.forEach((card) => {
            card.dataset.searchText = (card.textContent || "").toLowerCase();
        });

        function applyFilter() {
            const term = insightsSearch.value.trim().toLowerCase();
            let visible = 0;
            cards.forEach((card) => {
                const matches = !term || card.dataset.searchText.indexOf(term) !== -1;
                card.style.display = matches ? "" : "none";
                if (matches) {
                    visible += 1;
                }
            });
            if (visibleCount) {
                visibleCount.textContent = String(visible);
            }
            if (emptyNotice) {
                emptyNotice.hidden = visible !== 0;
            }
        }

        insightsSearch.addEventListener("input", applyFilter);
        applyFilter();
    }

    installInsightSearch();
});
