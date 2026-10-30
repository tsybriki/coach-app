/* Заглушка API для UI-тестов.
 *
 * Подменяет настоящий `client/api.js`: в тестах нет сети, а нужен
 * предсказуемый ответ. Данные берутся из `globalThis.__fixture` —
 * тест задаёт их перед загрузкой приложения.
 */

const fixture = () => globalThis.__fixture || {};

export function getSnapshot() {
  const f = fixture();
  return Promise.resolve({version: f.version ?? 42, data: f.snapshot});
}

export function getWeeks() {
  const f = fixture();
  return Promise.resolve({version: f.version ?? 42, data: {weeks: f.weeks || []}});
}

export function getCurrentWeek() {
  const f = fixture();
  return Promise.resolve({
    version: f.version ?? 42,
    data: {season_week: f.seasonWeek ?? 3},
  });
}

export function getWeek() {
  const f = fixture();
  return Promise.resolve({version: f.version ?? 42, data: f.week});
}

export function getActual() {
  const f = fixture();
  return Promise.resolve({
    version: f.version ?? 42,
    data: {sessions: f.actual || []},
  });
}

export function getDetail(actualId) {
  const f = fixture();
  const detail = (f.details || {})[actualId] || null;
  if (!detail) {
    const error = new Error('разбор не загружен');
    error.code = 'not_found';
    return Promise.reject(error);
  }
  return Promise.resolve({version: f.version ?? 42, data: detail});
}

export function sendCommand(command) {
  const f = fixture();
  const handler = f.onCommand;
  if (handler) return handler(command);
  return Promise.resolve({version: f.version ?? 42, data: {status: 'applied'}});
}

export function narrate() {
  return Promise.resolve({version: 42, data: {text: ''}});
}

export function subscribe(callback) {
  const list = globalThis.__subscribers || (globalThis.__subscribers = []);
  list.push(callback);
  return () => {
    const index = list.indexOf(callback);
    if (index >= 0) list.splice(index, 1);
  };
}
