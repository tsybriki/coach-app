/* Coach App — клиент.
 *
 * Одностраничное приложение. Экраны — проекции из снапшота, UI не знает,
 * как считается план.
 *
 * Офлайн: показываем кэш с отметкой «данные на <время>». Команды без сети
 * уходят в очередь и применяются при появлении сети.
 */

import * as api from './api.js';
import {
  getCache, putCache, enqueue, pendingCommands, removeCommand, markAttempt,
} from './store.js';

const state = {
  screen: 'week',
  seasonWeek: Number(localStorage.getItem('coach-app-week')) || null,
  version: 0,
  week: null,
  season: null,
  athlete: null,
  actual: [],
  summary: null,
  stale: false,
  cachedAt: null,
  online: navigator.onLine,
  outbox: [],
  message: null,
  base: localStorage.getItem('coach-app-base') || location.origin,
};

/* ------------------------------------------------------------------ рендер */

const app = document.getElementById('app');
const nav = document.getElementById('nav');

const SCREENS = [
  ['week', 'Неделя'],
  ['season', 'Сезон'],
  ['fact', 'План vs факт'],
  ['link', 'Связывание'],
  ['close', 'Закрытие'],
  ['athlete', 'Атлет'],
];

function render() {
  nav.innerHTML = SCREENS
    .map(([id, title]) =>
      `<button class="tab${state.screen === id ? ' on' : ''}" data-screen="${id}">${title}</button>`)
    .join('');

  const body = state.screen === 'week' ? screenWeek()
    : state.screen === 'season' ? screenSeason()
    : state.screen === 'fact' ? screenFact()
    : state.screen === 'link' ? screenLink()
    : state.screen === 'close' ? screenClose()
    : screenAthlete();

  app.innerHTML = header() + body;
}

function header() {
  const stale = state.stale
    ? `<span class="stale">данные на ${timeOf(state.cachedAt)}</span>`
    : '';
  const queued = state.outbox.length
    ? `<span class="queued">в очереди: ${state.outbox.length}</span>`
    : '';
  const message = state.message
    ? `<div class="msg">${escapeHtml(state.message)}</div>`
    : '';
  return `<div class="bar">
      <span class="ver">v${state.version}</span>
      ${stale}${queued}
      <button class="refresh" id="refresh">обновить</button>
    </div>${message}`;
}

function screenWeek() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const week = state.week;
  const days = new Map();
  for (const assignment of week.assignments || []) {
    if (!days.has(assignment.slot_id)) days.set(assignment.slot_id, []);
    days.get(assignment.slot_id).push(assignment);
  }

  const workouts = (week.workouts || []).map((w) => {
    const steps = (w.steps || []).map((s) =>
      `<li><b>${escapeHtml(s.role)}</b> ${formatDuration(s.duration_min)}
        ${s.focus_value && s.focus_value.zone ? '· ' + escapeHtml(s.focus_value.zone) : ''}</li>`).join('');
    const actual = state.actual.find((a) => a.id === w.actual_id);
    const mark = actual ? ' ✓' : '';
    return `<div class="card">
        <div class="chead">${escapeHtml(w.kind)} · ${escapeHtml(w.sport)} · ${formatDuration(w.duration_min)}${mark}</div>
        <ul class="steps">${steps}</ul>
      </div>`;
  }).join('');

  const unplaced = (week.unplaced || []).length
    ? `<div class="card warn"><div class="chead">Висяки: ${week.unplaced.length}</div>
        <p>Не разложилось по слотам. Решаете вы.</p></div>`
    : '';

  return `<h2>Неделя ${week.season_week}</h2>
    <div class="sub">${week.start} — ${week.end} · ${escapeHtml(week.status)}</div>
    ${unplaced}
    ${workouts || '<p>Тренировок нет.</p>'}`;
}

function screenSeason() {
  if (!state.season) return empty('Сезон ещё не загружена');
  const s = state.season;
  const plans = (s.plans || []).map((p) =>
    `<li>${escapeHtml(p.goal || p.id)} — ${escapeHtml(p.status)}</li>`).join('');
  return `<h2>Сезон</h2>
    <div class="sub">${s.horizon.start} — ${s.horizon.end} · ${s.horizon.season_week_count} недель</div>
    <div class="card"><div class="chead">Планы</div><ul>${plans || '<li>нет</li>'}</ul></div>`;
}

function screenFact() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const summary = state.summary;
  if (!summary) {
    return `<h2>План vs факт</h2>
      <p>Итога ещё нет. Неделя не закрыта.</p>
      <div class="card">
        <div class="chead">Факт без саммари</div>
        <p>Сессий загружено: ${state.actual.length}</p>
      </div>`;
  }
  const rows = Object.entries(summary.verdict || {})
    .filter(([, count]) => count)
    .map(([name, count]) => `<li>${escapeHtml(name)}: ${count}</li>`).join('');
  const totals = summary.totals || {};
  return `<h2>План vs факт</h2>
    <div class="card"><div class="chead">Итоги недели</div>
      <ul>
        <li>план: ${formatDuration(totals.planned_minutes)}</li>
        <li>факт: ${formatDuration(totals.actual_minutes)}</li>
        <li>сессий: ${totals.planned_sessions || 0} → ${totals.actual_sessions || 0}</li>
      </ul>
    </div>
    <div class="card"><div class="chead">Вердикты</div><ul>${rows || '<li>нет</li>'}</ul></div>`;
}

function screenLink() {
  const facts = state.actual.map((a) => {
    const linked = a.linked_workout_id
      ? `связан с ${a.linked_workout_id}`
      : '<span class="free">не связан</span>';
    return `<div class="card">
        <div class="chead">${escapeHtml(a.sport)} · ${formatDuration(a.duration_min)} · ${a.date}</div>
        <div class="sub">${linked}</div>
      </div>`;
  }).join('');
  return `<h2>Связывание</h2>
    <p>Связь ставится вручную. Без загруженного факта связывать нечего.</p>
    <button class="action" id="pull">Загрузить из Garmin</button>
    ${facts || '<p>Факта нет.</p>'}`;
}

function screenClose() {
  return `<h2>Закрытие недели</h2>
    <p>Ритуал: вытянуть факт → сопоставить руками → посчитать и записать.</p>
    <ol class="steps-list">
      <li>Вытянуть остаток факта</li>
      <li>Сопоставить факт с тренировками</li>
      <li>Посчитать и записать</li>
    </ol>
    <button class="action" id="close">Закрыть неделю</button>`;
}

function screenAthlete() {
  if (!state.athlete) return empty('Профиль ещё не загружен');
  const a = state.athlete;
  return `<h2>Атлет</h2>
    <div class="card"><div class="chead">Нормативы</div>
      <ul>
        <li>VDOT: ${a.vdot || '—'}</li>
        <li>HRmax: ${a.hr_max || '—'}</li>
        <li>ЛТП: ${a.lth || '—'}</li>
        <li>Вес: ${a.weight_kg || '—'} кг</li>
      </ul>
    </div>`;
}

function empty(text) {
  return `<p>${escapeHtml(text)}</p>`;
}

/* ------------------------------------------------------------------ данные */

async function load() {
  try {
    const snapshot = await api.getSnapshot();
    state.version = snapshot.version;
    state.season = snapshot.data.season;
    state.athlete = snapshot.data.athlete;
    state.stale = false;
    state.cachedAt = Date.now();
    await putCache('snapshot', snapshot.data, snapshot.version);

    // Текущая неделя — по дате на сервере: клиент не знает про начало сезона.
    // Ручной выбор в localStorage перекрывает.
    if (!state.seasonWeek) {
      const current = await api.getCurrentWeek();
      state.seasonWeek = current.data.season_week;
    }

    // недели может не быть — это не ошибка, а пустое состояние
    try {
      const week = await api.getWeek(state.seasonWeek);
      state.week = week.data;
      await putCache(`week:${state.seasonWeek}`, week.data, snapshot.version);
    } catch (error) {
      if (error.code === 'not_found') {
        state.week = null;
      } else {
        throw error;
      }
    }

    try {
      const actual = await api.getActual(state.seasonWeek);
      state.actual = actual.data.sessions || [];
      await putCache(`actual:${state.seasonWeek}`, state.actual, snapshot.version);
    } catch (error) {
      state.actual = (await getCache(`actual:${state.seasonWeek}`))?.value || [];
    }

    state.summary = state.week ? state.week.summary : null;
    state.message = null;
  } catch (error) {
    await loadFromCache();
    state.message = 'Сервер недоступен — показан последний известный снимок';
  }
  render();
}

async function loadFromCache() {
  // Каждый кэш читается независимо: отсутствие одного не должно ронять
  // остальные — показываем то, что есть.
  try {
    const snapshot = await getCache('snapshot');
    if (snapshot) {
      state.season = snapshot.value.season;
      state.athlete = snapshot.value.athlete;
      state.version = snapshot.version;
      state.cachedAt = snapshot.cached_at;
    }
  } catch (error) { /* кэша нет — пустое состояние */ }

  try {
    const week = await getCache(`week:${state.seasonWeek}`);
    if (week) {
      state.week = week.value;
      state.summary = week.value.summary;
    }
  } catch (error) { /* недели в кэше нет */ }

  try {
    const actual = await getCache(`actual:${state.seasonWeek}`);
    if (actual) state.actual = actual.value;
  } catch (error) { /* факта в кэше нет */ }

  state.stale = true;
}

async function flushOutbox() {
  const queued = await pendingCommands();
  state.outbox = queued;
  if (!queued.length) return;

  for (const command of queued) {
    try {
      await api.sendCommand(command);
      await removeCommand(command.id);
    } catch (error) {
      await markAttempt(command.id, error.message);
      if (error.code === 'version_conflict') {
        state.message = 'Состояние изменилось — посмотрите заново';
      }
      break;
    }
  }
  state.outbox = await pendingCommands();
}

/* ------------------------------------------------------------------ события */

document.addEventListener('click', async (event) => {
  const target = event.target;

  if (target.dataset.screen) {
    state.screen = target.dataset.screen;
    render();
    return;
  }

  if (target.id === 'refresh') {
    await load();
    await flushOutbox();
    render();
    return;
  }

  if (target.id === 'pull') {
    state.message = 'Загружаю факт из Garmin…';
    render();
    await queueCommand({
      id: `pull-${Date.now()}`,
      type: 'pull_fact',
      args: { season_week: state.seasonWeek },
      reason: 'загрузка факта из Garmin',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    return;
  }

  if (target.id === 'close') {
    state.message = 'Закрываю неделю…';
    render();
    await queueCommand({
      id: `close-${Date.now()}`,
      type: 'close_week',
      args: { season_week: state.seasonWeek },
      reason: 'закрытие недели',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
  }
});

async function queueCommand(command) {
  await enqueue(command);
  state.outbox = await pendingCommands();
}

/* ------------------------------------------------------------------ утилиты */

function formatDuration(minutes) {
  if (!minutes) return '0 мин';
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (!h) return `${m} мин`;
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

function timeOf(timestamp) {
  if (!timestamp) return '—';
  return new Date(timestamp).toLocaleTimeString('ru-RU', {
    hour: '2-digit', minute: '2-digit',
  });
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

window.addEventListener('online', () => {
  state.online = true;
  flushOutbox().then(load);
});

window.addEventListener('offline', () => {
  state.online = false;
  render();
});

api.subscribe((event) => {
  if (event.version !== state.version) {
    load();
  }
});

/* Service worker: оболочка кэшируется, приложение открывается без сети. */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {
    /* без service worker приложение всё равно работает, только без офлайна */
  });
}

load().then(flushOutbox).then(render);
