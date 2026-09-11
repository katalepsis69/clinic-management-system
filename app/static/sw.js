// ClinicCare PWA Service Worker
const CACHE_NAME = 'cliniccare-pwa-v2.9.1';
const STATIC_ASSETS = [
  '/',
  '/static/index.html',
  '/static/display.html',
  '/static/css/app.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable.png',
  '/static/icons/apple-touch-icon.png'
];

// Install event: cache application shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('PWA: Failed to cache some static assets during install:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate event: clean up stale caches and claim clients immediately
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event: Network-First for API and UI assets, cache fallback when offline
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Do not intercept non-GET requests or WebSocket connections
  if (event.request.method !== 'GET' || url.protocol === 'ws:' || url.protocol === 'wss:') {
    return;
  }

  // Dynamic API calls: Network-first
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ offline: true, error: 'Network unavailable. You are currently offline.' }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // UI assets & HTML navigation: Network-First (always fresh online, fallback to cache offline)
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(async () => {
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
        // If offline navigation, return cached root or index
        if (event.request.mode === 'navigate') {
          return (await caches.match('/')) || (await caches.match('/static/index.html'));
        }
      })
  );
});
