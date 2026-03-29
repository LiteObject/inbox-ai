/**
 * Service Worker for Inbox AI
 * Provides offline caching and faster repeat visits
 */

const CACHE_NAME = 'inbox-ai-v2';
const STATIC_ASSETS = [
    '/static/css/style.css',
    '/static/js/dashboard.js',
    'https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap',
    'https://fonts.googleapis.com/icon?family=Material+Icons',
    'https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,400,0,0',
];

function getStaticCacheKey(url) {
    const normalizedUrl = new URL(url, self.location.origin);
    return `${normalizedUrl.origin}${normalizedUrl.pathname}`;
}

// Install service worker and cache static assets
self.addEventListener('install', (event) => {
    console.log('[ServiceWorker] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[ServiceWorker] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[ServiceWorker] Installed successfully');
                return self.skipWaiting(); // Activate immediately
            })
            .catch((error) => {
                console.error('[ServiceWorker] Installation failed:', error);
            })
    );
});

// Activate and clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[ServiceWorker] Activating...');
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => name !== CACHE_NAME)
                        .map((name) => {
                            console.log('[ServiceWorker] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[ServiceWorker] Activated successfully');
                return self.clients.claim(); // Take control immediately
            })
    );
});

// Fetch strategy:
// - network-first for local static assets so UI changes propagate quickly
// - cache-first for third-party font assets
// - network-first for dynamic content
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const requestUrl = new URL(request.url);
    const isSameOrigin = requestUrl.origin === self.location.origin;
    const isFontAsset = request.url.includes('googleapis.com') || request.url.includes('gstatic.com');
    const isLocalStaticAsset = isSameOrigin && requestUrl.pathname.startsWith('/static/');

    // Only handle GET requests
    if (request.method !== 'GET') {
        return;
    }

    // Skip cross-origin requests that aren't our fonts
    if (request.url.startsWith('http') && !request.url.includes(self.location.origin) && !request.url.includes('googleapis.com') && !request.url.includes('gstatic.com')) {
        return;
    }

    // Cache-first strategy for third-party font assets.
    if (isFontAsset) {
        event.respondWith(
            caches.match(request)
                .then((cachedResponse) => {
                    if (cachedResponse) {
                        console.log('[ServiceWorker] Serving from cache:', request.url);
                        return cachedResponse;
                    }

                    console.log('[ServiceWorker] Fetching and caching:', request.url);
                    return fetch(request)
                        .then((response) => {
                            // Only cache successful responses
                            if (response.ok) {
                                const responseClone = response.clone();
                                caches.open(CACHE_NAME).then((cache) => {
                                    cache.put(request, responseClone);
                                });
                            }
                            return response;
                        });
                })
                .catch((error) => {
                    console.error('[ServiceWorker] Fetch failed:', error);
                    // Return offline fallback if available
                    return caches.match('/static/offline.html').catch(() => {
                        return new Response('Offline - please check your connection', {
                            status: 503,
                            statusText: 'Service Unavailable',
                            headers: new Headers({
                                'Content-Type': 'text/plain',
                            }),
                        });
                    });
                })
        );
        return;
    }

    // Network-first strategy for local static assets so fresh JS/CSS wins when online.
    if (isLocalStaticAsset) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response.ok) {
                        const responseClone = response.clone();
                        const cacheKey = getStaticCacheKey(request.url);
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(cacheKey, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    const cacheKey = getStaticCacheKey(request.url);
                    return caches.match(request)
                        .then((cachedResponse) => cachedResponse || caches.match(cacheKey))
                        .then((cachedResponse) => {
                            if (cachedResponse) {
                                console.log('[ServiceWorker] Serving cached static asset:', request.url);
                                return cachedResponse;
                            }

                            return new Response('Offline - asset not available', {
                                status: 503,
                                statusText: 'Service Unavailable',
                                headers: new Headers({
                                    'Content-Type': 'text/plain',
                                }),
                            });
                        });
                })
        );
        return;
    }

    // Network-first strategy for dynamic content (HTML pages, API calls)
    event.respondWith(
        fetch(request)
            .then((response) => {
                // Clone and cache successful HTML responses
                if (response.ok && response.headers.get('content-type')?.includes('text/html')) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Fallback to cache if network fails
                console.log('[ServiceWorker] Network failed, trying cache:', request.url);
                return caches.match(request)
                    .then((cachedResponse) => {
                        if (cachedResponse) {
                            console.log('[ServiceWorker] Serving stale content from cache');
                            return cachedResponse;
                        }

                        // No cache available
                        return new Response('Offline - content not available', {
                            status: 503,
                            statusText: 'Service Unavailable',
                            headers: new Headers({
                                'Content-Type': 'text/plain',
                            }),
                        });
                    });
            })
    );
});

// Handle messages from clients
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        console.log('[ServiceWorker] Received SKIP_WAITING message');
        self.skipWaiting();
    }

    if (event.data && event.data.type === 'CLEAR_CACHE') {
        console.log('[ServiceWorker] Received CLEAR_CACHE message');
        event.waitUntil(
            caches.keys().then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((name) => caches.delete(name))
                );
            })
        );
    }
});

console.log('[ServiceWorker] Script loaded');
