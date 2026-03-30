import { SpinnerController } from "./modules/spinner.js";
import { ToastManager } from "./modules/toast.js";
import { DialogManager } from "./modules/dialog.js";
import { installScrollRestore } from "./modules/scroll.js";
import ListDetailController from "./modules/list-detail.js";
import { installEmailListSearch } from "./modules/search.js";
import { LazyLoadingManager } from "./modules/lazy-loading.js";

let AVAILABLE_THEMES = ["default", "plant", "dark", "high-contrast", "vibrant", "teal", "lavender"];
const THEME_STORAGE_KEY = "dashboard.theme";

// Load themes from config
async function loadThemesConfig() {
    try {
        const response = await fetch("/static/config/themes.json");
        if (!response.ok) throw new Error("Failed to load themes config");
        const config = await response.json();
        AVAILABLE_THEMES = config.themes.map(theme => theme.id);
        return config.themes;
    } catch (error) {
        console.warn("Failed to load themes config, using defaults:", error);
        return null;
    }
}

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
    ["send_status", "send_message"],
    ["config_status", "config_message"],
    ["clear_status", "clear_message"],
    ["followup_status", "followup_message"],
    ["feedback_status", "feedback_message"],
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
                const formAction = submitter?.formAction || form.action || '';
                const isDeleteAction = /\/bulk-delete$|\/delete$/i.test(formAction);
                const confirmed = await dialogManager.confirm(
                    confirmMessage,
                    'Confirm Action',
                    'Delete',
                    'Cancel',
                    { initialFocus: isDeleteAction ? 'confirm' : 'cancel' },
                );
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
                } else if (action.includes("/draft")) {
                    // Handle draft operations - these need page reload to show updated content
                    const response = await fetch(action, {
                        method,
                        body: formData,
                        redirect: "follow",
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }

                    // For draft operations, we need to reload to show updated content
                    // Get the redirected URL or the current URL
                    const targetUrl = response.url || formData.get("redirect_to") || window.location.href;

                    // Preserve the currently selected email UID so we can re-select it after reload
                    const currentlySelectedItem = document.querySelector('.email-list-item[selected]');
                    const selectedUid = currentlySelectedItem?.dataset.uid;

                    // Store the selected email so detail view is restored after reload.
                    try {
                        if (selectedUid) {
                            window.sessionStorage?.setItem('dashboard.selectedEmailUid', selectedUid);
                        }
                    } catch (error) {
                        console.warn("Unable to persist data before reload", error);
                    }

                    queueToastsForNavigation(targetUrl);
                    spinner.hide();
                    window.location.href = targetUrl;
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

document.addEventListener("DOMContentLoaded", async () => {
    // Load themes from config first
    await loadThemesConfig();

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
    window.InboxAI = window.InboxAI || {};
    window.InboxAI.toast = toastManager;
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
    const totalCountTarget = document.getElementById('insights-total-count');

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

    const updateTotalCount = (delta) => {
        if (!totalCountTarget) {
            return;
        }

        const current = Number.parseInt(totalCountTarget.textContent || '', 10);
        if (!Number.isFinite(current)) {
            return;
        }

        totalCountTarget.textContent = String(Math.max(0, current + delta));
    };

    const getCsrfToken = () => {
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        return tokenInput?.value || '';
    };

    let emailListSearch = null;

    const deleteSelectedEmail = async (uid) => {
        const csrfToken = getCsrfToken();
        if (!uid || !csrfToken || !window.listDetailController) {
            return;
        }

        const confirmed = await dialogManager.confirm(
            'Move this email to trash? You can recover it from your trash folder.',
            'Confirm Action',
            'Delete',
            'Cancel',
            { initialFocus: 'confirm' },
        );
        if (!confirmed) {
            return;
        }

        spinner.show('Moving email to trash...');

        try {
            const response = await fetch(`/api/emails/${uid}`, {
                method: 'DELETE',
                headers: {
                    Accept: 'application/json',
                    'X-CSRF-Token': csrfToken,
                },
            });

            const payload = await response.json();
            if (!response.ok || !payload.success) {
                throw new Error(payload.message || 'Delete failed.');
            }

            window.listDetailController.removeItem(String(uid));
            emailListSearch?.refresh();
            updateTotalCount(-1);
            toastManager.show(payload.message || 'Email deleted.', 'success');
        } catch (error) {
            console.error('Delete request failed', error);
            toastManager.show(error.message || 'Delete failed. Please try again.', 'error');
        } finally {
            spinner.hide();
        }
    };

    // ── Filter toolbar: auto-submit + popover ──────────────
    const filterForm = document.getElementById('filter-rail');
    if (filterForm) {
        let submitTimer = null;
        const autoSubmitDelay = 600; // ms, only used for number input

        filterForm.querySelectorAll('[data-auto-submit]').forEach((el) => {
            const event = el.tagName === 'INPUT' ? 'input' : 'change';
            el.addEventListener(event, () => {
                clearTimeout(submitTimer);
                if (el.type === 'number') {
                    submitTimer = setTimeout(() => filterForm.submit(), autoSubmitDelay);
                } else {
                    filterForm.submit();
                }
            });
        });

        const moreBtn = document.getElementById('more-filters-toggle');
        const popover = document.getElementById('more-filters-popover');

        if (moreBtn && popover) {
            const openPopover = () => {
                popover.hidden = false;
                moreBtn.setAttribute('aria-expanded', 'true');
            };

            const closePopover = () => {
                popover.hidden = true;
                moreBtn.setAttribute('aria-expanded', 'false');
            };

            moreBtn.addEventListener('click', (e) => {
                e.preventDefault();
                if (popover.hidden) {
                    openPopover();
                } else {
                    closePopover();
                }
            });

            document.addEventListener('mousedown', (e) => {
                if (!popover.hidden && !popover.contains(e.target) && !moreBtn.contains(e.target)) {
                    closePopover();
                }
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && !popover.hidden) {
                    closePopover();
                    moreBtn.focus();
                }
            });
        }
    }

    const listDetailContainer = document.querySelector('.list-detail-container');
    const emailList = document.getElementById('email-list');
    const detailHost = document.getElementById('detail-content');
    const templateContainer = document.getElementById('detail-templates');
    const listPane = emailList?.closest('.md3-list-pane');
    const calendarRailRoot = document.getElementById('calendar-rail');
    const calendarRailData = document.getElementById('calendar-rail-data');
    const staticAssetVersion = window.__INBOX_AI_STATIC_VERSION || 'dev';
    let CalendarRailController = null;

    if (calendarRailRoot && calendarRailData) {
        try {
            ({ default: CalendarRailController } = await import(`./calendar-rail.js?v=${encodeURIComponent(staticAssetVersion)}`));
        } catch (error) {
            console.error('Failed to load calendar rail controller:', error);
        }
    }

    const calendarRail = CalendarRailController
        ? new CalendarRailController({
            root: calendarRailRoot,
            dataRoot: calendarRailData,
            onSelectEmail: (uid) => {
                window.listDetailController?.selectItem(uid, {
                    scroll: true,
                    updateHistory: false,
                });
            },
        })
        : null;

    if (listDetailContainer && emailList && detailHost && templateContainer) {
        // Initialize lazy loading manager
        window.lazyLoadingManager = new LazyLoadingManager({
            onLoadStart: (uid) => {
                const detailView = detailHost.querySelector('.detail-view');
                if (detailView) {
                    detailView.classList.add('loading');
                }
            },
            onLoadSuccess: (uid, data) => {
                const detailView = detailHost.querySelector('.detail-view');
                if (detailView) {
                    detailView.classList.remove('loading');
                    // Update body content if exists
                    const bodyText = detailView.querySelector('.email-body-text');
                    if (bodyText && data.bodyText) {
                        bodyText.textContent = data.bodyText;
                    }
                    const bodyHtml = detailView.querySelector('.email-body-html');
                    if (bodyHtml && data.bodyHtml) {
                        bodyHtml.innerHTML = data.bodyHtml;
                    }
                }
            },
            onLoadError: (uid, error) => {
                const detailView = detailHost.querySelector('.detail-view');
                if (detailView) {
                    detailView.classList.remove('loading');
                }
                console.error(`Failed to load email detail for UID ${uid}:`, error);
            },
        });

        window.listDetailController = new ListDetailController({
            container: listDetailContainer,
            list: emailList,
            detailHost,
            templateContainer,
            onDelete: deleteSelectedEmail,
            onDetailChanged: () => {
                bindInteractiveForms();
                // Initialize tabs for the newly loaded detail view
                if (typeof window.initializeTabs === 'function') {
                    window.initializeTabs();
                } else {
                    // Dispatch custom event for tabs.js to handle
                    window.dispatchEvent(new CustomEvent('content-loaded'));
                }
            },
            onSelect: (uid) => {
                // Lazy load email detail when selected
                if (window.lazyLoadingManager) {
                    window.lazyLoadingManager.loadEmailDetail(uid).catch((error) => {
                        console.error('Lazy loading failed:', error);
                    });
                }
                calendarRail?.setSelectedEmail(uid);
            },
        });

        // Restore previously selected email if it was stored (e.g., after a draft save reload)
        try {
            const previouslySelectedUid = window.sessionStorage?.getItem('dashboard.selectedEmailUid');
            if (previouslySelectedUid) {
                const previousItem = emailList.querySelector(`[data-uid="${previouslySelectedUid}"]`);
                if (previousItem) {
                    window.listDetailController.selectItem(previouslySelectedUid, { scroll: false, updateHistory: false });
                }
                window.sessionStorage?.removeItem('dashboard.selectedEmailUid');
            }
        } catch (error) {
            console.warn("Unable to restore previously selected email", error);
        }

        const visibleCountTargets = document.querySelectorAll('#insights-visible-count');

        emailListSearch = installEmailListSearch({
            input: document.getElementById('insights-search'),
            list: emailList,
            visibleCount: visibleCountTargets,
            emptyNotice: document.getElementById('insights-filter-empty'),
            onFilterChange: ({ visibleItems, hasQuery }) => {
                listPane?.classList.toggle('md3-list-pane--empty', visibleItems.length === 0);

                if (!window.listDetailController) {
                    return;
                }

                if (visibleItems.length === 0) {
                    window.listDetailController.clearSelection({
                        emptyState: hasQuery
                            ? {
                                icon: 'search_off',
                                title: 'No matching emails',
                                message: 'Try another sender, subject, or keyword to continue browsing the inbox.',
                            }
                            : {
                                icon: 'draft',
                                title: 'No email details yet',
                                message: 'Once messages are available, this panel will show summaries, actions, and draft replies.',
                            },
                    });
                    calendarRail?.setSelectedEmail(null);
                    return;
                }

                const visibleUids = visibleItems.map((item) => item.dataset.uid);
                window.listDetailController.syncVisibleItems(visibleUids);
            },
        });

        // Setup sort controls
        const sortToggle = document.getElementById('sort-toggle');
        const SORT_ORDER_KEY = 'dashboard.sort-order';
        let currentSortOrder = localStorage?.getItem(SORT_ORDER_KEY) ?? 'desc';

        const updateSortButton = () => {
            if (sortToggle) {
                sortToggle.setAttribute('data-direction', currentSortOrder);
                const label = currentSortOrder === 'desc' ? 'newest first' : 'oldest first';
                sortToggle.setAttribute('aria-label', `Sort by received date, currently ${label}`);
                sortToggle.setAttribute('title', `Sort by received date (${label})`);
            }
        };

        const sortList = (order) => {
            const items = Array.from(emailList.querySelectorAll('li'));

            items.sort((a, b) => {
                const buttonA = a.querySelector('.email-list-item');
                const buttonB = b.querySelector('.email-list-item');

                if (!buttonA || !buttonB) return 0;

                const dateA = buttonA.getAttribute('data-received') || '';
                const dateB = buttonB.getAttribute('data-received') || '';

                // Compare ISO-8601 date strings lexicographically
                if (dateA < dateB) return order === 'asc' ? -1 : 1;
                if (dateA > dateB) return order === 'asc' ? 1 : -1;
                return 0;
            });

            // Re-insert items in sorted order
            items.forEach((item) => {
                emailList.appendChild(item);
            });

            currentSortOrder = order;
            try {
                localStorage?.setItem(SORT_ORDER_KEY, order);
            } catch (error) {
                console.warn("Unable to persist sort order", error);
            }

            updateSortButton();
        };

        if (sortToggle) {
            sortToggle.addEventListener('click', () => {
                const newOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
                sortList(newOrder);
            });

            // Initialize sort state and apply saved preference
            updateSortButton();
            // Only sort if not already in the expected order (server typically sends desc)
            if (currentSortOrder === 'asc') {
                sortList('asc');
            }
        }
    }
});
