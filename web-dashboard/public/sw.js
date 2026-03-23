const CACHE_NAME = 'forge-v1.0.0';

const APP_SHELL = [
  '/',
  '/index.html',
  '/src/main.jsx',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Bebas+Neue&display=swap',
];

// Install: precache the app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL).catch((err) => {
        console.warn('[SW] Failed to cache some app shell resources:', err);
        // Cache what we can, don't fail the install for optional resources
        return Promise.allSettled(
          APP_SHELL.map((url) =>
            cache.add(url).catch((e) => {
              console.warn(`[SW] Could not cache: ${url}`, e);
            })
          )
        );
      });
    })
  );
  // Activate immediately, don't wait for old SW to finish
  self.skipWaiting();
});

// Activate: purge old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log(`[SW] Purging old cache: ${name}`);
            return caches.delete(name);
          })
      );
    })
  );
  // Take control of all clients immediately
  self.clients.claim();
});

// Fetch: routing strategies
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip WebSocket and chrome-extension requests
  if (url.protocol === 'ws:' || url.protocol === 'wss:' || url.protocol === 'chrome-extension:') {
    return;
  }

  // API calls: network-first with cache fallback
  if (url.pathname.includes('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Navigation requests (SPA routing): return cached index.html
  if (request.mode === 'navigate') {
    event.respondWith(
      caches.match('/index.html').then((cached) => {
        return cached || fetch(request).catch(() => {
          return new Response('Offline — The Forge is unavailable.', {
            status: 503,
            headers: { 'Content-Type': 'text/plain' },
          });
        });
      })
    );
    return;
  }

  // Static assets (CSS, JS, images, fonts): cache-first with network fallback
  if (isStaticAsset(url, request)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Everything else: network-first
  event.respondWith(networkFirst(request));
});

/**
 * Determine if a request is for a static asset.
 */
function isStaticAsset(url, request) {
  const staticExtensions = [
    '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
    '.woff', '.woff2', '.ttf', '.eot', '.otf', '.webp', '.avif',
    '.json', '.webmanifest',
  ];

  const pathname = url.pathname.toLowerCase();

  // Check file extensions
  if (staticExtensions.some((ext) => pathname.endsWith(ext))) {
    return true;
  }

  // Google Fonts CSS and font files
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    return true;
  }

  // Request destination hints
  const destinations = ['style', 'script', 'image', 'font'];
  if (destinations.includes(request.destination)) {
    return true;
  }

  return false;
}

/**
 * Cache-first strategy: check cache, fall back to network, update cache.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    console.warn('[SW] Cache-first fetch failed:', request.url, err);
    return new Response('', { status: 504, statusText: 'Gateway Timeout' });
  }
}

/**
 * Network-first strategy: try network, fall back to cache.
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    // Cache successful responses for future offline use
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) {
      console.log('[SW] Serving from cache (offline):', request.url);
      return cached;
    }
    console.warn('[SW] Network-first failed, no cache:', request.url, err);
    return new Response(
      JSON.stringify({ error: 'offline', message: 'The Forge is offline' }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}