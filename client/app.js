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
  openWorkoutId: null,
  message: null,
  base: localStorage.getItem('coach-app-base') || location.origin,
};

/* ------------------------------------------------------------------ рендер */

const picker = document.getElementById('picker');
const nav = document.getElementById('nav');
const bar = document.getElementById('appbar');
const cardWrap = document.getElementById('cardWrap');
const cardHost = document.getElementById('cardHost');

/* Нижняя навигация: иконка + подпись. Шесть экранов — в две строки нет,
 * поэтому нижняя навигация показывает пять, а шестой экран («Связывание»)
 * живёт внутри недели: факт — часть работы с неделей.
 */
const SCREENS = [
  ['week', 'Неделя', '📅'],
  ['fact', 'Факт', '📊'],
  ['season', 'Сезон', '🏆'],
  ['close', 'Закрыть', '🔒'],
  ['athlete', 'Атлет', '👤'],
];

function render() {
  nav.innerHTML = SCREENS
    .map(([id, title, ico]) =>
      `<button class="${state.screen === id ? 'on' : ''}" data-screen="${id}">
        <span class="ico">${ico}</span><span class="lbl">${title}</span>
      </button>`)
    .join('');

  bar.innerHTML = appBar();
  renderScreen();
}

/* Шапка приложения: заголовок, счётчик версии, кнопка обновить. */
function appBar() {
  const stale = state.stale
    ? `<span class="stale">данные на ${timeOf(state.cachedAt)}</span>`
    : '';
  const queued = state.outbox.length
    ? `<span class="queued">в очереди: ${state.outbox.length}</span>`
    : '';
  return `<div class="title">
        <div>${escapeHtml(screenTitle())}</div>
        <div class="sub">${escapeHtml(screenSubtitle())}</div>
      </div>
      <div class="right">
        ${stale}${queued}
        <span class="ver">v${state.version}</span>
        <button class="refresh" id="refresh">↻</button>
      </div>`;
}

function screenTitle() {
  if (state.screen === 'week') {
    return state.week ? `Неделя ${state.week.season_week}` : 'Неделя';
  }
  const found = SCREENS.find(([id]) => id === state.screen);
  return found ? found[1] : 'Coach';
}

function screenSubtitle() {
  if (state.screen === 'week' && state.week) {
    return `${state.week.start.slice(5)} — ${state.week.end.slice(5)}`;
  }
  if (state.screen === 'fact' && state.week) {
    return `${state.actual.length} сессий в факте`;
  }
  if (state.screen === 'season' && state.season) {
    return `${state.season.horizon.season_week_count} недель`;
  }
  return '';
}

/* Основной экран — по выбранному разделу. */
function renderScreen() {
  const body = state.screen === 'week' ? screenWeek()
    : state.screen === 'season' ? screenSeason()
    : state.screen === 'fact' ? screenFact()
    : state.screen === 'close' ? screenClose()
    : screenAthlete();
  picker.innerHTML = body;
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

/* Плашка тренировки в списке недели. По нажатию — детали. */
function slotButton(workout, linked) {
  const objective = workout.objective || {};
  const title = objective.name || workout.kind;
  const day = objective.day || '';
  const focus = workout.focus && workout.focus !== 'core' ? workout.focus : '';
  const done = linked ? ' <span class="done-mark">✓</span>' : '';

  return `<button class="slot${linked ? ' done' : ''}" data-slot="${escapeHtml(workout.id)}">
      <div class="slot-head">
        <span class="ico">${KIND_ICON[workout.sport] || '🎯'}</span>
        <span class="day">${escapeHtml(day)} · ${escapeHtml(workout.time || '')}</span>
        <span class="dur">${formatDuration(workout.duration_min)}${done}</span>
      </div>
      <div class="name">${escapeHtml(title)}</div>
      ${focus ? `<div class="focus">🎯 ${escapeHtml(focus)}</div>` : ''}
    </button>`;
}

/* Тренировки в порядке дней недели, внутри дня — по времени. */
function sortedWorkouts(workouts) {
  return [...workouts].sort((a, b) => {
    const dayA = DAY_ORDER.indexOf((a.objective || {}).day || '');
    const dayB = DAY_ORDER.indexOf((b.objective || {}).day || '');
    if (dayA !== dayB) return (dayA < 0 ? 99 : dayA) - (dayB < 0 ? 99 : dayB);
    const timeA = String(a.time || '99:99');
    const timeB = String(b.time || '99:99');
    if (timeA !== timeB) return timeA.localeCompare(timeB);
    return String((a.objective || {}).name || '').localeCompare(
      String((b.objective || {}).name || ''), 'ru');
  });
}

function screenWeek() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const week = state.week;
  const target = week.load_target || {};

  const slots = sortedWorkouts(week.workouts || []).map((w) => {
    const linked = state.actual.some((a) => a.id === w.actual_id);
    return slotButton(w, linked);
  }).join('');

  const unplaced = (week.unplaced || []).length
    ? `<div class="card warn"><div class="chead">Висяки: ${week.unplaced.length}</div></div>`
    : '';

  return `${messageBlock()}
    ${week.focus ? `<div class="card goal"><h3>Фокус недели</h3><p class="lead">${escapeHtml(week.focus)}</p></div>` : ''}
    <div class="totals-card">
      <div class="metrics">
        <div class="metric"><div class="v">${formatHours(target.hours * 60)}</div><div class="l">ч · план</div></div>
        <div class="metric"><div class="v">${target.sessions || 0}</div><div class="l">сессий</div></div>
        <div class="metric"><div class="v">${(target.distance_m / 1000).toFixed(0)}</div><div class="l">км</div></div>
      </div>
    </div>
    ${unplaced}
    <h2 class="slots-header">Тренировки · ${(week.workouts || []).length} шт</h2>
    <div class="slots-list">${slots || '<p>Тренировок нет.</p>'}</div>`;
}

/* Список факта недели — для выбора: что связать с этой тренировкой. */
function factList(workoutId) {
  const facts = state.actual.map((a) => {
    const mine = a.linked_workout_id === workoutId;
    const taken = a.linked_workout_id && !mine;
    const disabled = taken ? ' disabled' : '';
    const label = mine ? 'связана' : (taken ? 'занята' : 'связать');
    return `<button class="fact${mine ? ' linked' : ''}" data-actual="${escapeHtml(a.id)}"
        data-workout="${escapeHtml(workoutId)}"${disabled}>
        <span class="ico">${KIND_ICON[a.sport] || '🎯'}</span>
        <span class="body">
          <span class="date">${a.date}</span>
          <span class="meta">${((a.distance_m || 0) / 1000).toFixed(1)} км · ${formatDuration(a.duration_min)}${a.hr_avg ? ` · HR ${a.hr_avg}` : ''}</span>
        </span>
        <span class="act">${label}</span>
      </button>`;
  }).join('');
  return facts || '<p>Факта нет.</p>';
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

function screenClose() {
  return `${messageBlock()}<h2>Закрытие недели</h2>
    <div class="card">
      <div class="chead">Неделя ${state.week ? state.week.season_week : ''}</div>
      <div class="metrics">
        <div class="metric"><div class="v">${state.actual.length}</div><div class="l">сессий в факте</div></div>
        <div class="metric"><div class="v">${state.week ? (state.week.workouts || []).length : 0}</div><div class="l">в плане</div></div>
        <div class="metric"><div class="v">${state.week ? (state.week.workouts || []).filter((w) => w.actual_id).length : 0}</div><div class="l">связано</div></div>
      </div>
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


/* ------------------------------------------------------------------ детали */

/* Детали тренировки — по эталонному plan-wN.html.
 * Сеты собираются обратно: шаги с одинаковым group — один блок,
 * шаги с round — повторы внутри блока.
 */
function showWorkout(workoutId) {
  const workout = (state.week.workouts || []).find((w) => w.id === workoutId);
  if (!workout) {
    cardHost.innerHTML = '<div class="card">Тренировка не найдена</div>';
    return;
  }

  const objective = workout.objective || {};
  const title = objective.name || workout.kind;
  const stepCount = (workout.steps || []).length;

  const meta = [];
  if (workout.location) meta.push(`📍 ${escapeHtml(workout.location)}`);
  if (workout.focus) meta.push(`<span class="meta-item focus-pill focus-${escapeHtml(workout.focus)}">🎯 ${escapeHtml(workout.focus)}</span>`);
  if (objective.subkind) meta.push(`<span class="meta-item">${escapeHtml(objective.subkind)}</span>`);

  const session = objective.session || {};
  let goalHtml = '';
  if (session.session_goal) {
    goalHtml = `<div class="goal-block">
        <div class="lbl">Цель сессии</div>
        <div>${escapeHtml(session.session_goal)}</div>
        ${session.label ? `<div class="goal-row"><span class="meta-item">${escapeHtml(session.label)}</span></div>` : ''}
      </div>`;
  }

  let rationaleHtml = '';
  if (workout.rationale) {
    rationaleHtml = `<div class="rationale">
        <div class="lbl">Зачем</div>
        ${escapeHtml(workout.rationale)}
      </div>`;
  }

  const inventory = objective.inventory || [];
  const invHtml = inventory.length
    ? `<div class="inventory">
        <div class="lbl">Что нужно</div>
        ${inventory.map((i) => `<div class="inv-item"><span class="ico">${escapeHtml(i.icon || '•')}</span><span>${escapeHtml(i.name || '')}</span></div>`).join('')}
      </div>`
    : '';

  const linkedActual = workout.actual_id
    ? state.actual.find((a) => a.id === workout.actual_id)
    : null;

  const actualBlock = linkedActual
    ? `<div class="actual-block">
        <div class="lbl">Выполнено</div>
        <div class="line">
          <b>${((linkedActual.distance_m || 0) / 1000).toFixed(1)} км</b> ·
          ${formatDuration(linkedActual.duration_min)}
          ${linkedActual.hr_avg ? ` · HR ${linkedActual.hr_avg}` : ''}
        </div>
        <div class="when">${linkedActual.date}</div>
        <button class="action secondary" data-unlink="${escapeHtml(workout.id)}">Отвязать</button>
      </div>`
    : `<div class="actual-block empty">
        <div class="lbl">Не выполнено</div>
        <div class="facts">${factList(workout.id)}</div>
        <button class="action secondary" id="pull">Загрузить факт из Garmin</button>
      </div>`;

  cardHost.innerHTML = `<div class="card detail">
      <div class="card-header">
        <div class="headline">
          <span class="kind-ico">${KIND_ICON[workout.sport] || '🎯'}</span>
          <span class="name">${escapeHtml(title)}</span>
        </div>
        <span class="tag kind-${escapeHtml(workout.sport)}">${stepCount} шагов</span>
      </div>
      <div class="subtitle">${escapeHtml(objective.day || '')} · ${escapeHtml(workout.time || '')} · ${formatDuration(workout.duration_min)}</div>
      ${meta.length ? `<div class="meta-row">${meta.join('')}</div>` : ''}
      ${goalHtml}
      ${rationaleHtml}
      ${invHtml}
      <h3>Структура тренировки</h3>
      ${structureHtml(workout)}
      <h3>Факт</h3>
      ${actualBlock}
    </div>`;

  state.openWorkoutId = workoutId;
  cardWrap.classList.remove('hidden');
  picker.classList.add('hidden');
  bar.innerHTML = detailBar(title, objective.day || '');

  const slug = slotSlug(workout);
  try {
    if (history.state && history.state.page === 'detail') {
      history.replaceState({page: 'detail', slot: workoutId}, '', '#' + slug);
    } else {
      history.pushState({page: 'detail', slot: workoutId}, '', '#' + slug);
    }
  } catch (error) {
    history.replaceState(null, '', '#' + slug);
  }
  window.scrollTo(0, 0);
}

/* Идентификатор тренировки для адреса — латиницей: кириллица в URL
 * ломает кодировку и делит ссылку на части.
 */
function slotSlug(workout) {
  const objective = workout.objective || {};
  const day = objective.day || '';
  const name = (objective.name || workout.kind || '')
    .toLowerCase()
    .replace(/[^a-zа-яё0-9]+/gi, '-')
    .replace(/^-|-$/g, '');
  return `w${workout.season_week || state.seasonWeek}-${day}-${name}`;
}

/* Шапка на экране деталей: кнопка «назад» + название. */
function detailBar(title, day) {
  return `<button class="back" id="backBtn">←</button>
    <div class="title">
      <div>${escapeHtml(title)}</div>
      ${day ? `<div class="sub">${escapeHtml(day)}</div>` : ''}
    </div>`;
}

/* Обратно к списку. */
function showPicker() {
  state.openWorkoutId = null;
  cardWrap.classList.add('hidden');
  picker.classList.remove('hidden');
  if (window.location.hash) {
    try { history.replaceState(history.state, '', ' '); } catch (error) { /* нет */ }
  }
  renderScreen();
  bar.innerHTML = appBar();
  window.scrollTo(0, 0);
}

/* Структура тренировки: сеты собираются обратно из group/round. */
function structureHtml(workout) {
  const steps = workout.steps || [];
  if (!steps.length) return '<div class="empty">Нет структуры</div>';

  const blocks = [];
  let current = null;

  for (const step of steps) {
    // Блок начинается, если сменилась группа или тип шага (упражнение / нет).
    const isExercise = Boolean(step.label && step.focus_value?.reps);
    if (current && (step.group !== current.group || isExercise !== current.isExercise)) {
      current = {group: step.group, steps: [], isSet: false, isExercise};
      blocks.push(current);
    } else if (!current) {
      current = {group: step.group, steps: [], isSet: false, isExercise};
      blocks.push(current);
    }
    current.steps.push(step);
  }

  return `<ol class="structure-list">${blocks.map(renderBlock).join('')}</ol>`;
}

/* Один блок структуры: одиночный шаг, сет или упражнение. */
function renderBlock(block) {
  const steps = block.steps;

  // Упражнения ОФП: у каждого шага есть название и повторы в focus_value.
  // Проверка именно по обоим полям: у разминки focus_value пустой.
  if (steps.length > 1 && steps.every((s) => s.label && s.focus_value?.reps)) {
    return `<li class="step step-ofp">
        <div class="step-head"><span class="step-phase">${escapeHtml(block.group || 'main')}</span></div>
        <ol class="ex-list">${steps.map((s, i) => `
          <li class="ex-item">
            <div class="ex-num">${i + 1}</div>
            <div class="ex-content">
              <div class="ex-name">${escapeHtml(s.label || '')}</div>
              <div class="ex-reps">${escapeHtml(s.focus_value.reps)}</div>
              ${s.notes ? `<div class="ex-why">${escapeHtml(s.notes)}</div>` : ''}
            </div>
          </li>`).join('')}
        </ol>
      </li>`;
  }

  // Сет интервалов: у шагов есть round — это повторы
  if (steps.length > 1 && steps.every((s) => s.round !== null && s.round !== undefined)) {
    // Число повторов — из плана (3×800), а не количество шагов: в шагах
    // есть и отдых, поэтому шагов вдвое больше.
    const reps = steps[0].focus_value?.set_reps || steps.length;
    return `<li class="step step-set">
        <div class="step-head">
          <span class="step-phase">${escapeHtml(block.group || 'set')}</span>
          <span class="step-reps">× ${reps}</span>
        </div>
        <ol class="step-sublist">${steps.map(renderSubStep).join('')}</ol>
      </li>`;
  }

  // Одиночный шаг
  return `<li class="step">${renderSubStep(steps[0])}</li>`;
}

/* Шаг внутри: зона, роль, объём, пульс, темп. */
function renderSubStep(step) {
  const fv = step.focus_value || {};
  const zone = fv.zone ? `<span class="step-zone">${escapeHtml(fv.zone)}</span>` : '';
  const role = step.label || ROLE_RU[step.role] || step.role;

  let value = '';
  if (step.target_type === 'distance') {
    value = `<span class="step-dur">${Math.round(step.target_value)}м</span>`;
  } else if (step.target_type === 'reps') {
    value = `<span class="step-reps">× ${step.target_value}</span>`;
  } else {
    value = `<span class="step-dur">${Math.round(step.duration_min)}мин</span>`;
  }

  const hr = fv.hr_target ? ` <span class="step-extra">HR ${fv.hr_target}</span>` : '';
  const pace = fv.pace_min_per_km ? ` <span class="step-extra">@ ${escapeHtml(fv.pace_min_per_km)}/км</span>` : '';

  return `<div class="step-head">${zone}
      <span class="step-phase">${escapeHtml(role)}</span> ${value}${hr}${pace}
    </div>`;
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
  const slot = target.closest ? target.closest('[data-slot]') : null;

  // Тап по плашке тренировки — открыть детали
  if (slot) {
    showWorkout(slot.dataset.slot);
    return;
  }

  // Кнопка «назад» из деталей
  if (target.id === 'backBtn') {
    if (history.state && history.state.page === 'detail') {
      history.back();
    } else {
      showPicker();
    }
    return;
  }

  if (target.dataset.screen) {
    state.screen = target.dataset.screen;
    showPicker();
    render();
    return;
  }

  if (target.id === 'refresh') {
    await load();
    await flushOutbox();
    render();
    return;
  }

  // Тап по факту — связать с открытой тренировкой
  const fact = target.closest ? target.closest('[data-actual]') : null;
  if (fact) {
    await linkActual(fact.dataset.actual, fact.dataset.workout);
    return;
  }

  // Отвязать факт от тренировки
  const unlink = target.closest ? target.closest('[data-unlink]') : null;
  if (unlink) {
    await unlinkActual(unlink.dataset.unlink);
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
    state.message = null;
    render();
    // Вернуться в детали, если тренировка была открыта.
    if (state.week && state.openWorkoutId) showWorkout(state.openWorkoutId);
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

/* Кнопка «назад» на телефоне — вернуться к списку. */
window.addEventListener('popstate', (event) => {
  const current = event.state;
  if (!current || current.page !== 'detail') {
    showPicker();
  }
});

/* Связать факт с тренировкой. */
async function linkActual(actualId, workoutId) {
  state.message = 'Связываю…';
  render();
  await queueCommand({
    id: `link-${actualId}-${workoutId}-${Date.now()}`,
    type: 'link_actual',
    args: { season_week: state.seasonWeek, actual_id: actualId, workout_id: workoutId },
    reason: 'связь факта с тренировкой',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  // Вернуться в детали тренировки: после загрузки экран сбрасывается.
  if (state.week && workoutId) showWorkout(workoutId);
}

/* Отвязать факт от тренировки. */
async function unlinkActual(workoutId) {
  state.message = 'Отвязываю…';
  render();
  await queueCommand({
    id: `unlink-${workoutId}-${Date.now()}`,
    type: 'unlink_actual',
    args: { season_week: state.seasonWeek, workout_id: workoutId },
    reason: 'разрыв связи факта с тренировкой',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  if (state.week && workoutId) showWorkout(workoutId);
}

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

load().then(flushOutbox).then(render).then(() => {
  // Если в адресе есть хэш тренировки — открыть её (ссылка на детали).
  const hash = window.location.hash.replace('#', '');
  if (hash && state.week) {
    const match = (state.week.workouts || []).find((w) => slotSlug(w) === hash);
    if (match) {
      history.replaceState({page: 'init'}, '', ' ');
      showWorkout(match.id);
    }
  }
});
