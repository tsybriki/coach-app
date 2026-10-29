/* Локальное хранилище клиента: снапшот и очередь команд.
 *
 * IndexedDB. Снапшот — производная: помечен версией сервера, чтобы знать,
 * протух ли. Outbox — очередь команд, сделанных без сети.
 */

const DB_NAME = 'coach-app';
const DB_VERSION = 1;

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains('cache')) {
        db.createObjectStore('cache', { keyPath: 'key' });
      }
      if (!db.objectStoreNames.contains('outbox')) {
        const store = db.createObjectStore('outbox', { keyPath: 'id' });
        store.createIndex('created_at', 'created_at');
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(name, mode, action) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(name, mode);
    const store = tx.objectStore(name);
    let request;
    try {
      request = action(store);
    } catch (error) {
      reject(error);
      return;
    }
    // Значение берём из запроса: у отсутствующего ключа result === undefined.
    // Раньше возвращался сам объект запроса — вызывающий получал не то.
    tx.oncomplete = () => resolve(
      request && typeof request === 'object' && 'result' in request
        ? request.result
        : request,
    );
    tx.onerror = () => reject(tx.error);
  });
}

export async function putCache(key, value, version) {
  return withStore('cache', 'readwrite', (store) =>
    store.put({ key, value, version, cached_at: Date.now() }));
}

export async function getCache(key) {
  const entry = await withStore('cache', 'readonly', (store) => store.get(key));
  return entry ?? null;
}

export async function clearCache() {
  return withStore('cache', 'readwrite', (store) => store.clear());
}

export async function enqueue(command) {
  return withStore('outbox', 'readwrite', (store) =>
    store.put({ ...command, created_at: Date.now(), attempts: 0 }));
}

export async function pendingCommands() {
  const all = await withStore('outbox', 'readonly', (store) => store.getAll());
  return (all || []).sort((a, b) => a.created_at - b.created_at);
}

export async function removeCommand(id) {
  return withStore('outbox', 'readwrite', (store) => store.delete(id));
}

export async function markAttempt(id, error) {
  const entry = await withStore('outbox', 'readonly', (store) => store.get(id));
  if (!entry) return null;
  entry.attempts = (entry.attempts || 0) + 1;
  entry.last_error = error || null;
  return withStore('outbox', 'readwrite', (store) => store.put(entry));
}
