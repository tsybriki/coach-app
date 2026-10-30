/* Заглушка локального хранилища для UI-тестов.
 *
 * Настоящий `client/store.js` работает через IndexedDB, которого в Node
 * нет. Здесь — память: очередь команд и кэш снимка.
 */

const cache = new Map();
const outbox = [];

export function getCache(key) {
  const entry = cache.get(key);
  return Promise.resolve(entry ? {value: entry.value, version: entry.version} : null);
}

export function putCache(key, value, version) {
  cache.set(key, {value, version});
  return Promise.resolve();
}

export function clearCache() {
  cache.clear();
  return Promise.resolve();
}

export function enqueue(command) {
  outbox.push({...command, created_at: Date.now(), attempts: 0});
  return Promise.resolve();
}

export function pendingCommands() {
  return Promise.resolve([...outbox].sort((a, b) => a.created_at - b.created_at));
}

export function removeCommand(id) {
  const index = outbox.findIndex((command) => command.id === id);
  if (index >= 0) outbox.splice(index, 1);
  return Promise.resolve();
}

export function markAttempt(id, error) {
  const entry = outbox.find((command) => command.id === id);
  if (entry) {
    entry.attempts = (entry.attempts || 0) + 1;
    entry.last_error = error || null;
  }
  return Promise.resolve(entry || null);
}
