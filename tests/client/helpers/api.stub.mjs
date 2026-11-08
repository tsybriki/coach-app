/* Заглушка API для UI-тестов.
 *
 * Подменяет настоящий `client/api.js`: в тестах нет сети, а нужен
 * предсказуемый ответ. Данные берутся из `globalThis.__fixture` —
 * тест задаёт их перед загрузкой приложения.
 */

const fixture = () => globalThis.__fixture || {};

export function getSnapshot() {
  const f = fixture();
  f.snapshotCalls = (f.snapshotCalls || 0) + 1;
  const delay = f.delayMs || 0;
  // Профиль — из фикстуры: тест может задать свой (например, с FTP).
  const snapshot = f.snapshot
    ? {...f.snapshot, athlete: f.athlete || f.snapshot.athlete}
    : {season: {horizon: {start: '2026-10-11', end: '2027-09-18',
                          season_week_count: 49}},
       athlete: f.athlete || {vdot: 48, hr_max: 182, lth: 164,
                              hr_zones: {}}};
  if (!delay) {
    return Promise.resolve({version: f.version ?? 42, data: snapshot});
  }
  // Ответ с задержкой — как будто сервер думает.
  return new Promise((resolve) => setTimeout(
    () => resolve({version: f.version ?? 42, data: snapshot}), delay,
  ));
}

export function getWeeks() {
  const f = fixture();
  return Promise.resolve({version: f.version ?? 42, data: {weeks: f.weeks || []}});
}

export function getCurrentWeek() {
  const f = fixture();
  return Promise.resolve({
    version: f.version ?? 42,
    // Неделя сезона по календарю. Ручной выбор недели хранится отдельно
    // (localStorage) и может указывать на другую неделю.
    data: {season_week: f.currentWeek ?? f.seasonWeek ?? 3},
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

/* Метрики формы тренировки — из разбора FIT. */
export function getMetrics(actualId) {
  const f = fixture();
  const metrics = (f.metrics || {})[actualId];
  if (!metrics) {
    const error = new Error('метрики не посчитаны');
    error.code = 'not_found';
    return Promise.reject(error);
  }
  return Promise.resolve({version: f.version ?? 42, data: metrics});
}

/* Оценка FTP по тренировкам — 95-й перцентиль мощности. */
export function getFtpEstimate() {
  const f = fixture();
  return Promise.resolve({
    version: f.version ?? 42,
    data: f.ftpEstimate || {estimated_ftp_w: null, current_ftp_w: null,
                           workouts_used: 0},
  });
}

export function getSeason() {
  const f = fixture();
  return Promise.resolve({version: f.version ?? 42, data: f.seasonPlan || {}});
}

export function getSlots() {
  const f = fixture();
  return Promise.resolve({
    version: f.version ?? 42,
    data: {slots: f.slots || []},
  });
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
