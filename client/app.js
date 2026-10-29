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
  weeks: [],
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
const bar = document.getElementById('bar');

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

  bar.innerHTML = barInner();
  app.innerHTML = body;
}

function barInner() {
  const stale = state.stale
    ? `<span class="stale">данные на ${timeOf(state.cachedAt)}</span>`
    : '';
  const queued = state.outbox.length
    ? `<span class="queued">в очереди: ${state.outbox.length}</span>`
    : '';
  return `<span class="ver">v${state.version}</span>
      ${stale}${queued}
      <button class="refresh" id="refresh">обновить</button>`;
}

/* Сообщение — под шапкой, отдельным блоком. */
function messageBlock() {
  return state.message ? `<div class="msg">${escapeHtml(state.message)}</div>` : '';
}

/* Иконка вида спорта — как в эталонном plan-wN.html. */
const KIND_ICON = {
  run: '🏃', bike: '🚴', swim: '🏊', ofp: '💪',
  strength: '🏋️', mobility: '🧘', brick: '🔄',
};

function kindTag(sport) {
  return `<span class="kind kind-${escapeHtml(sport)}">${escapeHtml(sport)}</span>`;
}

/* Роль шага — по-русски. */
const ROLE_RU = {
  warmup: 'разминка',
  work: 'работа',
  rest: 'отдых',
  cooldown: 'заминка',
  transition: 'переход',
};

/* Порядок дней тренировочной недели: вс→сб. */
const DAY_ORDER = ['ВС', 'ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ'];

/* Карточка тренировки: иконка · название · теги · шаги. */
function workoutCard(workout, linked) {
  const steps = (workout.steps || []).map((step) => {
    const zone = step.focus_value && step.focus_value.zone;
    const name = step.notes ? ` — ${escapeHtml(step.notes)}` : '';
    return `<li><b>${escapeHtml(ROLE_RU[step.role] || step.role)}</b>
      ${formatDuration(step.duration_min)}${name}
      ${zone ? `<span class="zone">${escapeHtml(zone)}</span>` : ''}</li>`;
  }).join('');

  const meta = [];
  if (workout.location) meta.push(`📍 ${escapeHtml(workout.location)}`);
  if (workout.time) meta.push(`🕐 ${escapeHtml(workout.time)}`);
  if (workout.focus) meta.push(`🎯 ${escapeHtml(workout.focus)}`);

  const title = (workout.objective && workout.objective.name) || workout.kind;
  const day = workout.objective && workout.objective.day;

  return `<div class="card">
      <div class="chead">
        ${day ? `<span class="day">${escapeHtml(day)}</span>` : ''}
        <span>${KIND_ICON[workout.sport] || '🎯'}</span>
        <span class="name">${escapeHtml(title)}</span>
        ${kindTag(workout.sport)}
        <span class="dur">${formatDuration(workout.duration_min)}</span>
        ${linked ? '<span class="zone">✓</span>' : ''}
      </div>
      ${meta.length ? `<div class="sub">${meta.join(' · ')}</div>` : ''}
      <ul class="steps">${steps}</ul>
    </div>`;
}

/* Тренировки в порядке дней недели. */
function sortedWorkouts(workouts) {
  return [...workouts].sort((a, b) => {
    const dayA = DAY_ORDER.indexOf((a.objective || {}).day || '');
    const dayB = DAY_ORDER.indexOf((b.objective || {}).day || '');
    if (dayA !== dayB) return (dayA < 0 ? 99 : dayA) - (dayB < 0 ? 99 : dayB);
    return String((a.objective || {}).name || '').localeCompare(
      String((b.objective || {}).name || ''), 'ru');
  });
}

function screenWeek() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const week = state.week;
  const target = week.load_target || {};

  const summary = `<div class="card">
      <div class="chead">Итого недели</div>
      <div class="metrics">
        <div class="metric"><div class="v">${formatHours(target.hours * 60)}</div><div class="l">ч · план</div></div>
        <div class="metric"><div class="v">${target.sessions || 0}</div><div class="l">сессий</div></div>
        <div class="metric"><div class="v">${(target.distance_m / 1000).toFixed(0)}</div><div class="l">км</div></div>
      </div>
    </div>`;

  const workouts = sortedWorkouts(week.workouts || []).map((w) => {
    const linked = state.actual.some((a) => a.id === w.actual_id);
    return workoutCard(w, linked);
  }).join('');

  const unplaced = (week.unplaced || []).length
    ? `<div class="card warn"><div class="chead">Висяки: ${week.unplaced.length}</div>
        <p>Не разложилось по слотам. Решаете вы.</p></div>`
    : '';

  return `${messageBlock()}<h2>Неделя ${week.season_week}</h2>
    <div class="sub">${week.start} — ${week.end} · ${escapeHtml(week.status)}</div>
    ${week.focus ? `<div class="card goal"><h3>Фокус недели</h3><p class="lead">${escapeHtml(week.focus)}</p></div>` : ''}
    ${summary}
    ${unplaced}
    ${workouts || '<p>Тренировок нет.</p>'}`;
}

function screenSeason() {
  if (!state.season) return empty('Сезон ещё не загружена');
  const s = state.season;
  const plans = (s.plans || []).map((p) =>
    `<li><div class="row"><span>${escapeHtml(p.goal || p.id)}</span>
      <span class="num">${escapeHtml(p.status)}</span></div>
      ${p.race_date ? `<div class="sub">гонка ${p.race_date}</div>` : ''}</li>`).join('');

  const weeks = state.weeks || [];
  const weekRows = weeks.map((w) =>
    `<li><div class="row"><span>W${w.season_week}</span>
      <span class="num">${w.start.slice(5)} — ${w.end.slice(5)}</span></div></li>`).join('');

  return `${messageBlock()}<h2>Сезон</h2>
    <div class="sub">${s.horizon.start} — ${s.horizon.end} · ${s.horizon.season_week_count} недель</div>
    <div class="card"><h3>Планы</h3><ul class="plain">${plans || '<li>нет</li>'}</ul></div>
    <div class="card"><h3>Загруженные недели</h3>
      <ul class="plain">${weekRows || '<li>недель пока нет</li>'}</ul></div>`;
}

function screenFact() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const summary = state.summary;
  const sessions = state.actual.length;

  if (!summary) {
    return `${messageBlock()}<h2>План vs факт</h2>
      <div class="card">
        <div class="chead">Факт без саммари</div>
        <div class="metrics">
          <div class="metric"><div class="v">${sessions}</div><div class="l">сессий</div></div>
          <div class="metric"><div class="v">${(state.actual.reduce((sum, a) => sum + (a.distance_m || 0), 0) / 1000).toFixed(1)}</div><div class="l">км</div></div>
          <div class="metric"><div class="v">${formatHours(state.actual.reduce((sum, a) => sum + (a.duration_min || 0), 0))}</div><div class="l">ч · время</div></div>
        </div>
        <p>Итога ещё нет: неделя не закрыта.</p>
      </div>`;
  }

  const totals = summary.totals || {};
  const rows = Object.entries(summary.verdict || {})
    .filter(([, count]) => count)
    .map(([name, count]) =>
      `<li><div class="row"><span>${escapeHtml(name)}</span><span class="num">${count}</span></div></li>`)
    .join('');

  const planned = totals.planned_minutes || 0;
  const actual = totals.actual_minutes || 0;
  const delta = actual - planned;

  return `${messageBlock()}<h2>План vs факт</h2>
    <div class="card">
      <div class="chead">Итоги недели</div>
      <div class="metrics">
        <div class="metric"><div class="v">${formatHours(planned)}</div><div class="l">ч · план</div></div>
        <div class="metric ${actual >= planned ? 'good' : 'warn'}"><div class="v">${formatHours(actual)}</div><div class="l">ч · факт</div></div>
        <div class="metric ${delta >= 0 ? 'good' : 'warn'}"><div class="v">${delta >= 0 ? '+' : ''}${formatHours(delta)}</div><div class="l">ч · дельта</div></div>
      </div>
    </div>
    <div class="card"><h3>Вердикты</h3><ul class="plain">${rows || '<li>нет</li>'}</ul></div>`;
}

function screenLink() {
  const facts = state.actual.map((a) => {
    const linked = a.linked_workout_id
      ? `связан с ${a.linked_workout_id}`
      : '<span class="free">не связан</span>';
    return `<div class="card">
        <div class="chead">
          <span>${KIND_ICON[a.sport] || '🎯'}</span>
          <span>${escapeHtml(a.sport)}</span>
          <span class="dur">${formatDuration(a.duration_min)}</span>
        </div>
        <div class="sub">${a.date} · ${((a.distance_m || 0) / 1000).toFixed(1)} км · ${linked}</div>
      </div>`;
  }).join('');
  return `${messageBlock()}<h2>Связывание</h2>
    <p>Связь ставится вручную. Без загруженного факта связывать нечего.</p>
    <button class="action" id="pull">Загрузить из Garmin</button>
    ${facts || '<p>Факта нет.</p>'}`;
}

function screenClose() {
  return `${messageBlock()}<h2>Закрытие недели</h2>
    <p>Ритуал: вытянуть факт → сопоставить руками → посчитать и записать.</p>
    <div class="card">
      <h3>Шаги</h3>
      <ol class="steps-list">
        <li>Вытянуть остаток факта</li>
        <li>Сопоставить факт с тренировками</li>
        <li>Посчитать и записать</li>
      </ol>
    </div>
    <button class="action" id="close">Закрыть неделю</button>`;
}

function screenAthlete() {
  if (!state.athlete) return empty('Профиль ещё не загружен');
  const a = state.athlete;
  return `${messageBlock()}<h2>Атлет</h2>
    <div class="card">
      <div class="chead">Нормативы</div>
      <div class="metrics">
        <div class="metric"><div class="v">${a.vdot || '—'}</div><div class="l">VDOT</div></div>
        <div class="metric"><div class="v">${a.hr_max || '—'}</div><div class="l">HRmax</div></div>
        <div class="metric"><div class="v">${a.lth || '—'}</div><div class="l">ЛТП</div></div>
      </div>
      <ul class="plain" style="margin-top:10px">
        <li><div class="row"><span>Вес</span><span class="num">${a.weight_kg || '—'} кг</span></div></li>
        <li><div class="row"><span>Состояние</span><span class="num">${escapeHtml(a.form || '—')}</span></div></li>
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

    try {
      const weeks = await api.getWeeks();
      state.weeks = weeks.data.weeks || [];
      await putCache('weeks', state.weeks, snapshot.version);
    } catch (error) {
      state.weeks = state.weeks || [];
    }

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

  try {
    const weeks = await getCache('weeks');
    if (weeks) state.weeks = weeks.value;
  } catch (error) { /* списка недель в кэше нет */ }

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

/* Компактный формат для метрик: «6,2 ч» вместо «6 ч 14 мин». */
function formatHours(minutes) {
  if (!minutes) return '0';
  const hours = minutes / 60;
  return hours >= 10 ? hours.toFixed(0) : hours.toFixed(1);
}

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
