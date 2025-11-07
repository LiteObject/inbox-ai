/**
 * Service Worker Registration
 * Registers the service worker for offline caching
 */

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/js/service-worker.js')
            .then((registration) => {
                console.log('[SW Registration] Success:', registration.scope);

                // Check for updates periodically
                setInterval(() => {
                    registration.update();
                }, 60000); // Check every minute

                // Listen for updates
                registration.addEventListener('updatefound', () => {
                    const newWorker = registration.installing;
                    if (newWorker) {
                        newWorker.addEventListener('statechange', () => {
                            if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                                // New service worker available
                                console.log('[SW Registration] New version available');

                                // Optionally show update notification
                                showUpdateNotification(newWorker);
                            }
                        });
                    }
                });
            })
            .catch((error) => {
                console.error('[SW Registration] Failed:', error);
            });
    });

    // Handle service worker updates
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!refreshing) {
            refreshing = true;
            console.log('[SW] Controller changed, reloading page');
            window.location.reload();
        }
    });
}

/**
 * Show notification when service worker update is available
 */
function showUpdateNotification(worker) {
    // Create a simple notification banner
    const banner = document.createElement('div');
    banner.className = 'update-notification';
    banner.innerHTML = `
        <div class="update-content">
            <span class="material-icons">info</span>
            <span>A new version is available!</span>
            <button class="md3-button md3-button--text" onclick="updateServiceWorker()">
                Update
            </button>
            <button class="md3-button md3-button--text" onclick="dismissUpdateNotification()">
                Dismiss
            </button>
        </div>
    `;

    banner.style.cssText = `
        position: fixed;
        top: 64px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--md-sys-color-primary-container);
        color: var(--md-sys-color-on-primary-container);
        padding: 16px 24px;
        border-radius: 8px;
        box-shadow: var(--md-sys-elevation-3);
        z-index: 1000;
        display: flex;
        align-items: center;
        gap: 16px;
        animation: slideDown 0.3s ease-out;
    `;

    document.body.appendChild(banner);

    // Store reference for update function
    window._pendingServiceWorker = worker;
}

/**
 * Update to new service worker version
 */
function updateServiceWorker() {
    if (window._pendingServiceWorker) {
        window._pendingServiceWorker.postMessage({ type: 'SKIP_WAITING' });
        window._pendingServiceWorker = null;
    }
}

/**
 * Dismiss update notification
 */
function dismissUpdateNotification() {
    const banner = document.querySelector('.update-notification');
    if (banner) {
        banner.remove();
    }
}

/**
 * Clear service worker cache (useful for development)
 */
function clearServiceWorkerCache() {
    if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_CACHE' });
        console.log('[SW] Cache clear requested');
    }
}

// Expose functions globally for use in HTML
window.updateServiceWorker = updateServiceWorker;
window.dismissUpdateNotification = dismissUpdateNotification;
window.clearServiceWorkerCache = clearServiceWorkerCache;

console.log('[SW Registration] Script loaded');
