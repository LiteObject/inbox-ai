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

                    if (form.action.endsWith('/sync')) {
                        // Handle sync with Server-Sent Events
                        const response = await fetch(form.action, {
                            method,
                            body: formData,
                        });

                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                        }

                        const reader = response.body.getReader();
                        const decoder = new TextDecoder();
                        let buffer = '';

                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;
                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split('\n');
                            buffer = lines.pop();
                            for (const line of lines) {
                                if (line.startsWith('data: ')) {
                                    const data = line.slice(6);
                                    if (data.startsWith('redirect:')) {
                                        window.location.href = data.slice(9);
                                        return;
                                    } else {
                                        showSpinner(data);
                                    }
                                }
                            }
                        }
                    } else {
                        // Normal form submission
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

    function normalizeString(value) {
        if (value === undefined || value === null) {
            return "";
        }
        return String(value).replace(/\s+/g, " ").trim().toLowerCase();
    }

    function boolFromDataset(value) {
        if (typeof value !== "string") {
            return false;
        }
        const normalized = value.trim().toLowerCase();
        return normalized === "true" || normalized === "1" || normalized === "yes";
    }

    function parseNumeric(value) {
        if (value === undefined || value === null || value === "") {
            return null;
        }
        const parsed = Number.parseFloat(String(value));
        return Number.isFinite(parsed) ? parsed : null;
    }

    function buildSearchIndex(card) {
        const dataset = card.dataset;
        return {
            text: normalizeString(card.textContent || ""),
            subject: normalizeString(dataset.subject),
            sender: normalizeString(dataset.sender),
            summary: normalizeString(dataset.summary),
            actions: normalizeString(dataset.actions),
            categories: normalizeString(dataset.categories),
            priority: normalizeString(dataset.priority),
            priorityValue: parseNumeric(dataset.priorityValue),
            provider: normalizeString(dataset.provider),
            follow: normalizeString(dataset.follow),
            draft: normalizeString(dataset.draft),
            draftProvider: normalizeString(dataset.draftProvider),
            draftFallback: boolFromDataset(dataset.draftFallback),
            uid: normalizeString(dataset.uid),
            thread: normalizeString(dataset.threadId),
            hasFollow: boolFromDataset(dataset.hasFollowups),
            hasDraft: boolFromDataset(dataset.hasDraft),
        };
    }

    function splitSearchQuery(query) {
        const rawTokens = [];
        let current = "";
        let inQuotes = false;
        let quoteChar = "";
        for (let index = 0; index < query.length; index += 1) {
            const char = query[index];
            if (char === "\"" || char === "'") {
                if (inQuotes && char === quoteChar) {
                    inQuotes = false;
                    quoteChar = "";
                    continue;
                }
                if (!inQuotes) {
                    inQuotes = true;
                    quoteChar = char;
                    continue;
                }
            }
            if (/\s/.test(char) && !inQuotes) {
                if (current) {
                    rawTokens.push(current);
                    current = "";
                }
                continue;
            }
            current += char;
        }
        if (current) {
            rawTokens.push(current);
        }
        return rawTokens;
    }

    function parseSearchTokens(query) {
        const rawTokens = splitSearchQuery(query || "");
        const tokens = [];
        rawTokens.forEach((raw) => {
            if (!raw) {
                return;
            }
            let token = raw;
            let negated = false;
            if (token.startsWith("-") && token.length > 1) {
                negated = true;
                token = token.slice(1);
            }
            const colonIndex = token.indexOf(":");
            if (colonIndex > 0) {
                const keyRaw = token.slice(0, colonIndex).toLowerCase();
                const valueRaw = token.slice(colonIndex + 1);
                const trimmedValue = valueRaw.trim();
                if (!trimmedValue) {
                    return;
                }
                tokens.push({
                    kind: "field",
                    key: keyRaw,
                    normalizedKey: keyRaw.replace(/[^a-z0-9]/g, ""),
                    value: normalizeString(trimmedValue),
                    rawValue: trimmedValue,
                    negated,
                });
                return;
            }
            const normalizedValue = normalizeString(token);
            if (!normalizedValue) {
                return;
            }
            tokens.push({
                kind: "term",
                value: normalizedValue,
                rawValue: token,
                negated,
            });
        });
        return tokens;
    }

    function matchesPriorityField(index, token) {
        if (!token.value) {
            return true;
        }
        const compact = token.value.replace(/\s+/g, "");
        if (compact.endsWith("+")) {
            const base = Number.parseInt(compact.slice(0, -1), 10);
            if (!Number.isNaN(base) && index.priorityValue !== null) {
                return index.priorityValue >= base;
            }
        }
        const comparisonMatch = compact.match(/^(>=|<=|>|<|=)?(\d{1,2})$/);
        if (comparisonMatch && index.priorityValue !== null) {
            const operator = comparisonMatch[1] || "=";
            const target = Number.parseInt(comparisonMatch[2], 10);
            switch (operator) {
                case ">":
                    return index.priorityValue > target;
                case ">=":
                    return index.priorityValue >= target;
                case "<":
                    return index.priorityValue < target;
                case "<=":
                    return index.priorityValue <= target;
                default:
                    return index.priorityValue === target;
            }
        }
        if (index.priorityValue !== null) {
            const numeric = Number.parseInt(compact, 10);
            if (!Number.isNaN(numeric)) {
                return index.priorityValue === numeric;
            }
        }
        return index.priority.includes(token.value);
    }

    function matchesIsField(index, value) {
        switch (value) {
            case "followup":
            case "followups":
            case "tasks":
                return index.hasFollow;
            case "draft":
            case "reply":
                return index.hasDraft;
            case "fallback":
                return index.provider.includes("fallback") || index.draftFallback;
            case "open":
            case "done":
                return index.follow.includes(value);
            default:
                return index.text.includes(value);
        }
    }

    function matchesHasField(index, value) {
        switch (value) {
            case "followup":
            case "followups":
            case "tasks":
                return index.hasFollow;
            case "draft":
            case "reply":
                return index.hasDraft;
            default:
                return index.text.includes(value);
        }
    }

    function matchesFieldToken(index, token) {
        if (!token.value && !token.rawValue) {
            return true;
        }
        const key = token.normalizedKey;
        const value = token.value;
        switch (key) {
            case "from":
            case "sender":
                return index.sender.includes(value);
            case "subject":
            case "title":
                return index.subject.includes(value);
            case "summary":
            case "body":
            case "text":
                return index.summary.includes(value) || index.draft.includes(value);
            case "action":
            case "actions":
            case "todo":
                return index.actions.includes(value);
            case "category":
            case "categories":
            case "tag":
            case "labels":
                return index.categories.includes(value);
            case "priority":
            case "score":
                return matchesPriorityField(index, token);
            case "provider":
            case "source":
                return (
                    index.provider.includes(value) ||
                    index.draftProvider.includes(value)
                );
            case "draft":
            case "reply":
                return (
                    index.draft.includes(value) ||
                    index.draftProvider.includes(value)
                );
            case "follow":
            case "followup":
            case "followups":
            case "task":
            case "tasks":
            case "status":
                return index.follow.includes(value);
            case "uid":
            case "id":
                return index.uid.includes(value);
            case "thread":
            case "threadid":
                return index.thread.includes(value);
            case "is":
                return matchesIsField(index, value);
            case "has":
                return matchesHasField(index, value);
            default:
                return index.text.includes(value);
        }
    }

    function matchesTerm(index, token) {
        if (!token.value) {
            return true;
        }
        return index.text.includes(token.value);
    }

    function cardMatches(index, tokens) {
        if (!tokens.length) {
            return true;
        }
        for (const token of tokens) {
            const matched = token.kind === "term"
                ? matchesTerm(index, token)
                : matchesFieldToken(index, token);
            if (token.negated) {
                if (matched) {
                    return false;
                }
            } else if (!matched) {
                return false;
            }
        }
        return true;
    }

    function installInsightSearch() {
        if (!insightsSearch || !insightsGrid) {
            return;
        }
        const cards = Array.from(insightsGrid.querySelectorAll(".insight-card"));
        if (!cards.length) {
            return;
        }
        const indexMap = new Map();
        cards.forEach((card) => {
            indexMap.set(card, buildSearchIndex(card));
        });

        function applyFilter() {
            const tokens = parseSearchTokens(insightsSearch.value || "");
            let visible = 0;
            cards.forEach((card) => {
                const cardIndex = indexMap.get(card);
                const matches = cardIndex ? cardMatches(cardIndex, tokens) : true;
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
        insightsSearch.addEventListener("search", applyFilter);
        applyFilter();
    }

    installInsightSearch();
});
