/**
 * Client-side navigation handler for SPA-like experience
 * Provides smooth transitions without full page reloads
 */

class NavigationManager {
    constructor() {
        this.contentTarget = document.getElementById('main-content');
        this.headerElement = document.getElementById('dashboard-app-bar');
        this.cache = new Map();
        this.maxCacheSize = 10; // Limit cache size to prevent memory issues
        this.setupEventListeners();

        // Store initial state
        const currentUrl = window.location.pathname + window.location.search;
        history.replaceState({ url: currentUrl }, document.title, currentUrl);
    }

    setupEventListeners() {
        // Intercept all internal navigation clicks
        document.addEventListener('click', (e) => {
            const link = e.target.closest('a[href^="/"], button[data-navigate]');
            if (link && !link.hasAttribute('data-external') && !link.hasAttribute('data-no-navigate')) {
                e.preventDefault();
                const url = link.getAttribute('href') || link.getAttribute('data-navigate');
                if (url) {
                    this.navigate(url);
                }
            }
        });

        // Handle browser back/forward buttons
        window.addEventListener('popstate', (e) => {
            if (e.state && e.state.url) {
                this.loadContent(e.state.url, false);
            }
        });

        // Listen for data changes to invalidate cache
        window.addEventListener('data-changed', (e) => {
            this.invalidateCache(e.detail?.pattern);
        });
    }

    async navigate(url, options = {}) {
        const { skipCache = false, method = 'GET', body = null } = options;

        // Check cache first (only for GET requests)
        if (method === 'GET' && !skipCache && this.cache.has(url)) {
            console.log('[Navigation] Serving from cache:', url);
            this.renderContent(this.cache.get(url), url, true);
            return;
        }

        await this.loadContent(url, true, method, body);
    }

    async loadContent(url, pushState = true, method = 'GET', body = null) {
        try {
            this.showLoader('Loading page...');

            const options = {
                method,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'text/html'
                }
            };

            if (body) {
                options.body = body;
            }

            const response = await fetch(url, options);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const html = await response.text();

            // Cache GET responses (with size limit)
            if (method === 'GET') {
                this.addToCache(url, html);
            }

            this.renderContent(html, url, pushState);

        } catch (error) {
            console.error('[Navigation] Error:', error);
            this.showError('Failed to load page. Refreshing...');
            setTimeout(() => {
                window.location.href = url;
            }, 1500);
        } finally {
            this.hideLoader();
        }
    }

    renderContent(html, url, pushState) {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        // Extract and update main content
        const newContent = doc.getElementById('main-content') || doc.querySelector('main');
        if (newContent) {
            if (this.contentTarget) {
                // Fade out current content
                this.contentTarget.style.opacity = '0';

                setTimeout(() => {
                    this.contentTarget.innerHTML = newContent.innerHTML;

                    // Fade in new content
                    this.contentTarget.style.opacity = '1';
                }, 150);
            }
        }

        // Update page title
        const newTitle = doc.querySelector('title')?.textContent;
        if (newTitle) {
            document.title = newTitle;
        }

        // Update header if needed (for settings vs dashboard)
        const newHeader = doc.getElementById('dashboard-app-bar');
        if (newHeader && this.headerElement) {
            const currentButtons = this.headerElement.querySelector('.md3-top-app-bar-actions');
            const newButtons = newHeader.querySelector('.md3-top-app-bar-actions');

            if (currentButtons && newButtons && currentButtons.innerHTML !== newButtons.innerHTML) {
                currentButtons.innerHTML = newButtons.innerHTML;
            }

            // Update title section if changed
            const currentTitleSection = this.headerElement.querySelector('.md3-app-bar-title-section');
            const newTitleSection = newHeader.querySelector('.md3-app-bar-title-section');
            if (currentTitleSection && newTitleSection) {
                const currentTitle = currentTitleSection.querySelector('.md3-app-bar-title')?.textContent;
                const newTitleText = newTitleSection.querySelector('.md3-app-bar-title')?.textContent;
                if (currentTitle !== newTitleText) {
                    currentTitleSection.innerHTML = newTitleSection.innerHTML;
                }
            }
        }

        // Update URL without reload
        if (pushState) {
            history.pushState({ url }, newTitle || '', url);
        }

        // Reinitialize page-specific modules
        this.reinitializeModules();

        // Smooth scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });

        // Announce navigation to screen readers
        this.announceNavigation(newTitle || url);

        console.log('[Navigation] Navigated to:', url);
    }

    addToCache(url, html) {
        // Implement LRU cache: remove oldest if at capacity
        if (this.cache.size >= this.maxCacheSize) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
        this.cache.set(url, html);
    }

    reinitializeModules() {
        // Dispatch event for modules to reinitialize
        window.dispatchEvent(new CustomEvent('content-loaded', {
            detail: {
                url: window.location.pathname,
                timestamp: Date.now()
            }
        }));
    }

    showLoader(message = 'Loading...') {
        const spinner = document.getElementById('sync-spinner');
        if (spinner) {
            const messageElement = spinner.querySelector('#spinner-message');
            if (messageElement) {
                messageElement.textContent = message;
            }
            spinner.hidden = false;
        }
    }

    hideLoader() {
        const spinner = document.getElementById('sync-spinner');
        if (spinner) {
            spinner.hidden = true;
        }
    }

    showError(message) {
        // Use existing toast notification system if available
        if (window.showToast) {
            window.showToast(message, 'error');
        } else {
            // Fallback to custom event
            window.dispatchEvent(new CustomEvent('show-toast', {
                detail: { message, type: 'error' }
            }));
        }
    }

    announceNavigation(title) {
        const announcer = document.createElement('div');
        announcer.setAttribute('role', 'status');
        announcer.setAttribute('aria-live', 'polite');
        announcer.className = 'sr-only';
        announcer.textContent = `Navigated to ${title}`;
        document.body.appendChild(announcer);
        setTimeout(() => announcer.remove(), 1000);
    }

    // Clear cache when data changes
    invalidateCache(pattern = null) {
        if (pattern) {
            console.log('[Navigation] Invalidating cache for pattern:', pattern);
            for (const [url] of this.cache) {
                if (url.includes(pattern)) {
                    this.cache.delete(url);
                }
            }
        } else {
            console.log('[Navigation] Clearing all cache');
            this.cache.clear();
        }
    }

    // Public method to prefetch a URL
    async prefetch(url) {
        if (this.cache.has(url)) {
            return; // Already cached
        }

        try {
            const response = await fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'text/html'
                }
            });

            if (response.ok) {
                const html = await response.text();
                this.addToCache(url, html);
                console.log('[Navigation] Prefetched:', url);
            }
        } catch (error) {
            console.warn('[Navigation] Prefetch failed:', url, error);
        }
    }
}

// Initialize navigation manager
let navigationManager;

function initializeNavigation() {
    if (!navigationManager) {
        navigationManager = new NavigationManager();

        // Expose for cache invalidation and prefetching
        window.navigationManager = navigationManager;

        console.log('[Navigation] Navigation manager initialized');
    }
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeNavigation);
} else {
    initializeNavigation();
}

export default NavigationManager;
