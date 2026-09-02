/**
 * QuantumGrinch v7 — Service Worker
 * Features: Cache-first strategy, Background Sync, Push Notifications
 */

const CACHE_NAME = 'quantumgrinch-v12-net-profit';
const STATIC_ASSETS = [
  '/',
  '/static/css/grid_style.css',
  '/static/js/grid_dashboard.js?v=20260902-net-profit-1',
  '/static/js/lightweight-charts.standalone.production.js',
  '/static/manifest.json',
];
const OPTIONAL_ASSETS = [
  'https://cdn.socket.io/4.7.2/socket.io.min.js',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'
];

// Install: cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await cache.addAll(STATIC_ASSETS);
      // A CDN outage must not prevent the new worker from installing.
      await Promise.all(OPTIONAL_ASSETS.map((url) => cache.add(url).catch(() => null)));
    }).then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: cache-first for static, network-first for API
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Always refresh the dashboard shell so new controls and settings logic
  // reach the browser instead of being hidden behind an old cached page.
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // API requests: network first, fallback to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Static assets: cache first
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      });
    })
  );
});

// Background Sync: retry failed requests
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-price-data') {
    event.waitUntil(syncPriceData());
  }
});

async function syncPriceData() {
  const clients = await self.clients.matchAll();
  clients.forEach((client) => client.postMessage({ type: 'SYNC_COMPLETE' }));
}

// Push Notifications
self.addEventListener('push', (event) => {
  const data = event.data?.json() || {};
  event.waitUntil(
    self.registration.showNotification(data.title || 'QuantumGrinch', {
      body: data.body || 'New trading signal detected',
      icon: '/static/img/icon-192.png',
      badge: '/static/img/icon-192.png',
      tag: data.tag || 'signal',
      requireInteraction: true,
      actions: [
        { action: 'open', title: 'Открыть' },
        { action: 'dismiss', title: 'Закрыть' }
      ]
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'open') {
    event.waitUntil(self.clients.openWindow('/'));
  }
});
