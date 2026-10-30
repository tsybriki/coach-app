/* Service worker.
 *
 * Оболочка — cache-first: приложение открывается мгновенно и без сети.
 * API — network-first: при недоступности сети клиент берёт кэш сам
 * (IndexedDB) и показывает отметку «данные на <время>».
 *
 * Ответы команд и ошибки не кэшируются никогда.
 */

const CACHE = 'coach-app-shell-v13';
const SHELL = ['/', '/index.html', '/app.js', '/api.js', '/store.js', '/link.js',
               '/chart.js', '/structure.js', '/style.css', '/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  // API и события — всегда в сеть
  if (url.pathname.startsWith('/api/')) return;

  // оболочка — из кэша, обновление в фоне
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached || caches.match('/index.html'));
      return cached || network;
    }),
  );
});
