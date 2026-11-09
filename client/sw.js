/* Service worker.
 *
 * Оболочка — network-first: при наличии сети отдаётся свежий файл, кэш
 * обновляется на ходу. Без сети — кэш: приложение открывается и без
 * сети. API — всегда в сеть; клиент сам берёт кэш из IndexedDB и
 * показывает отметку «данные на <время>».
 *
 * Почему не cache-first: при нём правка в коде не доезжает до экрана —
 * телефон берёт старый `app.js` из кэша worker'а, и приложение выглядит
 * сломанным. В инкогнито, где worker'а нет, работало — отсюда разница.
 *
 * Ответы команд и ошибки не кэшируются никогда.
 */

const CACHE = 'coach-app-shell-v29';
const SHELL = ['/', '/index.html', '/app.js', '/api.js', '/store.js', '/link.js',
               '/chart.js', '/structure.js', '/style.css', '/manifest.json',
               '/icons/icon-192.png', '/icons/icon-512.png',
               '/icons/icon-maskable-512.png', '/icons/icon.svg'];

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

  // Сам service worker — всегда из сети. Иначе он обслуживает себя из
  // своего же кэша, новая версия никогда не устанавливается, и оболочка
  // навсегда остаётся старой.
  if (url.pathname === '/sw.js') return;

  // Оболочка — из сети, кэш только офлайн.
  //
  // Раньше было cache-first: кэш отдавался всегда, и обновление уходило в
  // фон. Из-за этого правка в коде не доезжала до экрана — телефон брал
  // старый `app.js` из кэша service worker'а, и приложение выглядело
  // сломанным (в инкогнито, где worker'а нет, работало).
  //
  // Теперь при наличии сети отдаётся свежий файл, а кэш обновляется на
  // ходу. Без сети — кэш: офлайн по-прежнему работает.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then(
        (cached) => cached || caches.match('/index.html'))),
  );
});
