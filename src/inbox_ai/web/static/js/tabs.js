/**
 * Material Design 3 Tab Management
 * Handles tab switching, keyboard navigation, and lazy loading of email content
 */

/**
 * MD3TabManager Class
 * Manages tabbed interface with accessibility and lazy loading support
 */
class MD3TabManager {
    constructor(tabsContainer) {
        this.tabsContainer = tabsContainer;
        this.tabs = Array.from(tabsContainer.querySelectorAll('[role="tab"]'));
        this.panels = Array.from(
            tabsContainer.parentElement.querySelectorAll('[role="tabpanel"]')
        );

        // Track loaded panels to avoid re-fetching
        this.loadedPanels = new Set();

        this.setupEventListeners();
    }

    setupEventListeners() {
        this.tabs.forEach((tab, index) => {
            // Click handling
            tab.addEventListener('click', () => this.selectTab(index));

            // Keyboard navigation (ARIA pattern)
            tab.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowLeft') {
                    e.preventDefault();
                    const prevIndex = index > 0 ? index - 1 : this.tabs.length - 1;
                    this.tabs[prevIndex].focus();
                    this.selectTab(prevIndex);
                } else if (e.key === 'ArrowRight') {
                    e.preventDefault();
                    const nextIndex = (index + 1) % this.tabs.length;
                    this.tabs[nextIndex].focus();
                    this.selectTab(nextIndex);
                } else if (e.key === 'Home') {
                    e.preventDefault();
                    this.tabs[0].focus();
                    this.selectTab(0);
                } else if (e.key === 'End') {
                    e.preventDefault();
                    const lastIndex = this.tabs.length - 1;
                    this.tabs[lastIndex].focus();
                    this.selectTab(lastIndex);
                }
            });
        });
    }

    selectTab(index) {
        // Deactivate all tabs
        this.tabs.forEach((tab, i) => {
            const isSelected = i === index;
            tab.classList.toggle('md3-tab--active', isSelected);
            tab.setAttribute('aria-selected', isSelected);
            tab.setAttribute('tabindex', isSelected ? '0' : '-1');
        });

        // Show selected panel, hide others
        this.panels.forEach((panel, i) => {
            const isActive = i === index;
            panel.classList.toggle('md3-tab-panel--active', isActive);
            panel.hidden = !isActive;
        });

        // Lazy load original email content when switching to that tab
        const selectedPanel = this.panels[index];
        const tabType = this.tabs[index].dataset.tab;

        if (tabType === 'original' && !this.loadedPanels.has(index)) {
            this.loadOriginalEmail(selectedPanel);
            this.loadedPanels.add(index);
        }

        // Announce to screen readers
        this.announceTabChange(this.tabs[index].querySelector('.md3-tab__text-label').textContent);
    }

    async loadOriginalEmail(panel) {
        const emailBody = panel.querySelector('.email-body');
        const uid = emailBody.dataset.uid;

        if (!uid) {
            emailBody.innerHTML = '<p class="error-message">Email UID not found</p>';
            return;
        }

        try {
            const response = await fetch(`/api/email/${uid}/detail`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.error) {
                emailBody.innerHTML = `<p class="error-message">${escapeHtml(data.error)}</p>`;
                return;
            }

            // Prefer HTML body, fall back to plain text
            if (data.bodyHtml) {
                // Render HTML in sandboxed iframe for security
                const iframe = document.createElement('iframe');
                iframe.sandbox = 'allow-same-origin'; // No scripts
                iframe.setAttribute('title', 'Email content');
                iframe.srcdoc = data.bodyHtml;
                emailBody.innerHTML = '';
                emailBody.appendChild(iframe);

                // Adjust iframe height to content
                iframe.addEventListener('load', () => {
                    try {
                        const height = iframe.contentDocument.body.scrollHeight;
                        iframe.style.height = `${Math.max(height + 20, 200)}px`;
                    } catch (e) {
                        // Cross-origin restriction, use default height
                        console.warn('Cannot access iframe content height:', e);
                        iframe.style.height = '400px';
                    }
                });
            } else if (data.bodyText) {
                emailBody.innerHTML = `<pre>${escapeHtml(data.bodyText)}</pre>`;
            } else {
                emailBody.innerHTML = '<p class="info-message">No email body available</p>';
            }
        } catch (error) {
            console.error('Failed to load email body:', error);
            emailBody.innerHTML = `<p class="error-message">Failed to load email content: ${escapeHtml(error.message)}</p>`;
        }
    }

    announceTabChange(tabLabel) {
        // Create live region for screen reader announcement
        const announcer = document.createElement('div');
        announcer.setAttribute('role', 'status');
        announcer.setAttribute('aria-live', 'polite');
        announcer.className = 'sr-only';
        announcer.textContent = `${tabLabel} tab selected`;
        document.body.appendChild(announcer);

        // Remove after announcement
        setTimeout(() => announcer.remove(), 1000);
    }
}

/**
 * Escape HTML to prevent XSS when displaying plain text
 * @param {string} text - Text to escape
 * @returns {string} - Escaped HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Initialize tab managers for all tab containers on the page
 */
function initializeTabs() {
    const tabContainers = document.querySelectorAll('.md3-tabs');

    if (tabContainers.length === 0) {
        return;
    }

    tabContainers.forEach(tabsContainer => {
        // Avoid re-initializing
        if (tabsContainer.dataset.initialized === 'true') {
            return;
        }

        new MD3TabManager(tabsContainer);
        tabsContainer.dataset.initialized = 'true';
    });

    console.log(`Initialized ${tabContainers.length} tab manager(s)`);
}

// Make available globally
window.initializeTabs = initializeTabs;

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeTabs);
} else {
    initializeTabs();
}

// Re-initialize after dynamic content loads (for SPA-like behavior)
window.addEventListener('content-loaded', initializeTabs);

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MD3TabManager, initializeTabs, escapeHtml };
}
