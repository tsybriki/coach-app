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
import { linkCandidates } from './link.js';
import { axisLabels, polyline, timeLabels, toPoints, zoneBands } from './chart.js';
import {
  groupBlocks,
  isExerciseBlock,
  isSetBlock,
  nameHasReps,
  repsLabel,
  setReps,
} from './structure.js';

const state = {
  screen: 'week',
  seasonWeek: Number(localStorage.getItem('coach-app-week')) || null,
  version: 0,
  week: null,
  season: null,
  athlete: null,
  actual: [],
  detail: null,
  detailId: null,        // разбор какой факта открыт
  weeks: [],
  summary: null,
  stale: false,
  cachedAt: null,
  online: navigator.onLine,
  outbox: [],
  openWorkoutId: null,
  message: null,
  messageKind: 'info',   // 'info' — гаснет само, 'error' — ждёт действия
  messageTimer: null,
  base: localStorage.getItem('coach-app-base') || location.origin,
};

/* ------------------------------------------------------------------ рендер */

const picker = document.getElementById('picker');
const nav = document.getElementById('nav');
const bar = document.getElementById('appbar');
const cardWrap = document.getElementById('cardWrap');
const cardHost = document.getElementById('cardHost');
const detailWrap = document.getElementById('detailWrap');
const detailHost = document.getElementById('detailHost');

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

  bar.innerHTML = chromeBar();
  renderScreen();
}

/* Шапка зависит от уровня вложенности:
 *   разбор  → «←» + название разбора
 *   тренировка → «←» + название тренировки
 *   раздел  → заголовок раздела
 */
function chromeBar() {
  if (state.detailId) {
    const fact = state.actual.find((a) => a.id === state.detailId);
    const title = fact
      ? `${((fact.distance_m || 0) / 1000).toFixed(1)} км · ${SPORT_NAME[fact.sport] || fact.sport}`
      : 'Разбор тренировки';
    return detailBar(title, fact ? fact.date : '');
  }
  if (state.openWorkoutId && state.week) {
    const workout = (state.week.workouts || [])
      .find((w) => w.id === state.openWorkoutId);
    if (workout) {
      const objective = workout.objective || {};
      return detailBar(objective.name || workout.kind, objective.day || '');
    }
  }
  return appBar();
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
  return state.message
    ? `<div class="msg ${escapeHtml(state.messageKind)}" id="msg">${escapeHtml(state.message)}</div>`
    : '';
}

/* Показать сообщение. Информационное гаснет само через несколько секунд —
 * иначе плашка висит и закрывает половину экрана. Ошибка ждёт действия:
 * её закрывают вручную. */
function showMessage(text, kind = 'info') {
  state.message = text;
  state.messageKind = kind;
  if (state.messageTimer) {
    clearTimeout(state.messageTimer);
    state.messageTimer = null;
  }
  if (kind === 'info') {
    state.messageTimer = setTimeout(() => {
      state.message = null;
      state.messageTimer = null;
      render();
    }, 4000);
  }
}

/* Иконка вида спорта — как в эталонном plan-wN.html. */
const SPORT_NAME = {
  run: 'Бег', bike: 'Велосипед', swim: 'Плавание', hiit: 'HIIT',
  strength: 'Силовая', ofp: 'ОФП', mobility: 'Мобильность',
};

const KIND_ICON = {
  run: '🏃', bike: '🚴', swim: '🏊', ofp: '💪',
  strength: '🏋️', mobility: '🧘', hiit: '⚡', brick: '🔄',
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
function slotButton(workout, actual) {
  const objective = workout.objective || {};
  const title = objective.name || workout.kind;
  const day = objective.day || '';
  const focus = workout.focus && workout.focus !== 'core' ? workout.focus : '';
  const done = actual ? ' <span class="done-mark">✓</span>' : '';

  const actualLine = actual
    ? `<div class="done-line">${((actual.distance_m || 0) / 1000).toFixed(1)} км · ${formatDuration(actual.duration_min)}${actual.hr_avg ? ` · HR ${actual.hr_avg}` : ''}</div>`
    : '';

  return `<button class="slot${actual ? ' done' : ''}" data-slot="${escapeHtml(workout.id)}">
      <div class="slot-head">
        <span class="ico">${KIND_ICON[workout.sport] || '🎯'}</span>
        <span class="day">${escapeHtml(day)} · ${escapeHtml(workout.time || '')}</span>
        <span class="dur">${formatDuration(workout.duration_min)}${done}</span>
      </div>
      <div class="name">${escapeHtml(title)}</div>
      ${focus ? `<div class="focus">🎯 ${escapeHtml(focus)}</div>` : ''}
      ${actualLine}
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
    const actual = state.actual.find((a) => a.id === w.actual_id);
    return slotButton(w, actual);
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
      ${progressBlock(week.progress)}
    </div>
    ${unplaced}
    <h2 class="slots-header">Тренировки · ${(week.workouts || []).length} шт</h2>
    <div class="slots-list">${slots || '<p>Тренировок нет.</p>'}</div>`;
}

/* Факт недели против плана: «N из M».
 *
 * Показывается по всем трём величинам: часы, сессии, километраж бега.
 * План сверху, факт снизу — так виден разрыв.
 */
function progressBlock(progress) {
  if (!progress) return '';
  const rows = [];

  const hours = progress.hours || {};
  if (hours.planned) {
    rows.push(progressRow('ч', formatHours(hours.actual * 60),
      formatHours(hours.planned * 60), hours.actual / hours.planned));
  }

  const sessions = progress.sessions || {};
  if (sessions.planned) {
    rows.push(progressRow('сессий', String(sessions.actual), String(sessions.planned),
      sessions.actual / sessions.planned));
  }

  const distance = progress.distance_m || {};
  if (distance.planned) {
    rows.push(progressRow('км', (distance.actual / 1000).toFixed(1),
      (distance.planned / 1000).toFixed(0),
      distance.actual / distance.planned));
  }

  if (!rows.length) return '';
  return `<div class="progress">${rows.join('')}</div>`;
}

/* Одна строка прогресса: факт, план и доля выполнения. */
function progressRow(label, actual, planned, share) {
  const pct = Math.round(Math.min(share, 1.5) * 100);
  const over = share > 1.02;
  const width = Math.min(100, pct);
  return `<div class="prog-row">
      <span class="prog-label">${escapeHtml(label)}</span>
      <span class="prog-value ${over ? 'over' : ''}">${escapeHtml(actual)}</span>
      <span class="prog-plan">из ${escapeHtml(planned)}</span>
      <span class="prog-bar"><i style="width:${width}%"${over ? ' class="over"' : ''}></i></span>
    </div>`;
}

/* Список факта недели — для выбора: что связать с этой тренировкой. */
function factList(workout) {
  const facts = linkCandidates(workout, state.actual).map((a) => {
    return `<button class="fact" data-actual="${escapeHtml(a.id)}"
        data-workout="${escapeHtml(workout.id)}">
        <span class="ico">${KIND_ICON[a.sport] || '🎯'}</span>
        <span class="body">
          <span class="date">${a.date}</span>
          <span class="meta">${SPORT_NAME[a.sport] || a.sport} · ${((a.distance_m || 0) / 1000).toFixed(1)} км · ${formatDuration(a.duration_min)}${a.hr_avg ? ` · HR ${a.hr_avg}` : ''}</span>
        </span>
        <span class="act">связать</span>
      </button>`;
  }).join('');
  return facts || `<p>${SPORT_NAME[workout.sport] || workout.sport}: активностей нет</p>`;
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



/* ------------------------------------------------------------------ разбор */

/* Цвета зон пульса — по порядку, от Z1 к Z7. */
const ZONE_COLORS = [
  'rgba(92,214,192,.10)',
  'rgba(92,214,192,.16)',
  'rgba(240,198,116,.14)',
  'rgba(255,155,106,.14)',
  'rgba(216,160,255,.16)',
  'rgba(216,160,255,.22)',
  'rgba(255,107,90,.22)',
];

/* Зоны пульса атлета из профиля. */
function hrZones() {
  const zones = state.athlete && state.athlete.hr_zones;
  if (!zones) return [];
  return Object.entries(zones).map(([name, bounds], index) => ({
    name,
    low: bounds.low,
    high: bounds.high,
    color: ZONE_COLORS[index % ZONE_COLORS.length],
  }));
}

/* Экран разбора выполненной тренировки — третий уровень.
 *
 * Отдельный экран, а не блок внизу карточки: разбор — это данные другой
 * сущности (факт), а не продолжение описания тренировки.
 */
function screenDetail() {
  const detail = state.detail;
  if (!detail) {
    return `<div class="card"><p class="lead">Разбор не загружен</p></div>`;
  }
  return detailContent(detail);
}

/* Открыть разбор: свой экран, свой заголовок, своя кнопка «назад». */
function showDetail(actualId) {
  const fact = state.actual.find((a) => a.id === actualId);
  const title = fact
    ? `${((fact.distance_m || 0) / 1000).toFixed(1)} км · ${escapeHtml(SPORT_NAME[fact.sport] || fact.sport)}`
    : 'Разбор тренировки';

  state.detailId = actualId;
  detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
  detailWrap.classList.remove('hidden');
  cardWrap.classList.add('hidden');
  picker.classList.add('hidden');

  try {
    history.pushState({page: 'detail', actual: actualId}, '', `#d${actualId}`);
  } catch (error) {
    history.replaceState(null, '', `#d${actualId}`);
  }
  render();
  window.scrollTo(0, 0);
}

/* Содержимое разбора. */
function detailContent(detail) {
  const distance = (detail.distance_m || 0) / 1000;
  const moving = formatDuration((detail.duration_s || 0) / 60);

  const stats = `<div class="card">
      <div class="chead">Итоги</div>
      <div class="metrics">
        <div class="metric"><div class="v">${distance.toFixed(1)}</div><div class="l">км</div></div>
        <div class="metric"><div class="v">${moving}</div><div class="l">время</div></div>
        <div class="metric"><div class="v">${detail.avg_hr ?? '—'}</div><div class="l">HR средний</div></div>
        <div class="metric"><div class="v">${detail.max_hr ?? '—'}</div><div class="l">HR макс</div></div>
        <div class="metric"><div class="v">${detail.avg_cadence ?? '—'}</div><div class="l">кад. ср</div></div>
        <div class="metric"><div class="v">${detail.max_cadence ?? '—'}</div><div class="l">кад. макс</div></div>
        <div class="metric"><div class="v">${Math.round(detail.ascent_m || 0)}</div><div class="l">м набор</div></div>
        <div class="metric"><div class="v">${detail.calories ?? '—'}</div><div class="l">ккал</div></div>
      </div>
      ${detail.cadence_source ? `<div class="sub">Каденция: ${detail.cadence_source === 'stryd' ? 'нагрудный ремень (Stryd)' : 'часы'}</div>` : ''}
    </div>`;

  return stats + zoneContent(detail) + chartContent(detail) + splitsContent(detail);
}

/* Время в зонах пульса атлета. */
function zoneContent(detail) {
  const minutes = detail.hr_zone_minutes || {};
  const total = Object.values(minutes).reduce((sum, value) => sum + value, 0);
  if (!total) return '';

  const rows = Object.entries(minutes).map(([zone, value]) => {
    const share = (value / total) * 100;
    return `<div class="zone-row">
        <span class="zone-name">${escapeHtml(zone)}</span>
        <span class="zone-bar"><i style="width:${share.toFixed(1)}%"></i></span>
        <span class="zone-value">${value.toFixed(0)} мин · ${share.toFixed(0)}%</span>
      </div>`;
  }).join('');

  return `<div class="card">
      <h3>Время в зонах пульса</h3>
      <div class="zones">${rows}</div>
    </div>`;
}

/* Графики: пульс, каденция, мощность. */
function chartContent(detail) {
  const series = detail.series || {};
  const blocks = [];
  if (series.hr && series.hr.length > 1) {
    blocks.push(chartCard('Пульс', series.hr, 'bpm', '#7aa2ff', true));
  }
  if (series.cadence && series.cadence.length > 1) {
    blocks.push(chartCard('Каденция', series.cadence, 'spm', '#5cd6c0', false));
  }
  if (series.power && series.power.length > 1) {
    blocks.push(chartCard('Мощность', series.power, 'Вт', '#ff9b6a', false));
  }
  return blocks.join('');
}

/* Один график: SVG с линией, подписями осей и зонами пульса. */
function chartCard(title, series, unit, color, withZones) {
  const plotWidth = 300;
  const height = 110;
  const gutter = 26;          // слева — подписи значений
  const bottom = 14;          // снизу — подписи времени
  const values = series.map((point) => point[1]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);

  const points = toPoints(series, plotWidth, height, minValue, maxValue);
  const bands = withZones
    ? zoneBands(hrZones(), values, plotWidth, height, minValue, maxValue)
    : [];
  const yLabels = axisLabels(minValue, maxValue, 4);
  const xLabels = timeLabels(series, 4);

  const bandHtml = bands.map((band) =>
    `<rect x="${gutter}" y="${band.y.toFixed(1)}" width="${plotWidth}" height="${band.height.toFixed(1)}" fill="${band.color}"/>`).join('');

  const yHtml = yLabels.map((label, index) => {
    const y = (index / Math.max(1, yLabels.length - 1)) * height;
    return `<line x1="${gutter}" y1="${y.toFixed(1)}" x2="${gutter + plotWidth}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.05)"/>
      <text x="${gutter - 4}" y="${(y + 3).toFixed(1)}" class="c-label c-right">${label}</text>`;
  }).join('');

  const xHtml = xLabels.map((label) => {
    const x = gutter + (label.x / 100) * plotWidth;
    const anchor = label.x <= 0 ? 'start' : label.x >= 100 ? 'end' : 'middle';
    return `<text x="${x.toFixed(1)}" y="${height + bottom - 2}" class="c-label c-mid" text-anchor="${anchor}">${label.text}</text>`;
  }).join('');

  return `<div class="card">
      <h3>${escapeHtml(title)} <span class="c-unit">${escapeHtml(unit)}</span></h3>
      <svg class="chart" viewBox="0 0 ${gutter + plotWidth} ${height + bottom}">
        ${bandHtml}
        ${yHtml}
        <polyline points="${polyline(points)}" fill="none" stroke="${color}" stroke-width="1.6"
          stroke-linejoin="round" stroke-linecap="round"
          transform="translate(${gutter} 0)"/>
        ${xHtml}
      </svg>
      <div class="c-foot">мин</div>
    </div>`;
}

/* Отрезки тренировки. */
function splitsContent(detail) {
  const splits = detail.splits || [];
  if (!splits.length) return '';

  const rows = splits.map((split) => {
    const speed = split.avg_speed_mps ? `${formatPace(split.avg_speed_mps)}/км` : '—';
    return `<li>
        <div class="row">
          <span>${split.index}</span>
          <span class="num">${((split.distance_m || 0) / 1000).toFixed(2)} км · ${speed}</span>
        </div>
        <div class="sub">
          ${formatDuration(split.duration_s / 60)}
          ${split.avg_hr ? ` · HR ${split.avg_hr}` : ''}
          ${split.avg_cadence ? ` · ${split.avg_cadence} spm` : ''}
          ${split.ascent_m ? ` · +${Math.round(split.ascent_m)} м` : ''}
        </div>
      </li>`;
  }).join('');

  return `<div class="card">
      <h3>Отрезки · ${splits.length}</h3>
      <ul class="plain">${rows}</ul>
    </div>`;
}

/* Темп из скорости: м/с → мин/км. */
function formatPace(mps) {
  if (!mps) return '—';
  const secPerKm = 1000 / mps;
  const minutes = Math.floor(secPerKm / 60);
  const seconds = Math.round(secPerKm % 60);
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
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
  if (workout.location) meta.push(`<span class="meta-item">📍 ${escapeHtml(workout.location)}</span>`);
  if (workout.focus) meta.push(`<span class="meta-item focus-pill focus-${escapeHtml(workout.focus)}">${escapeHtml(workout.focus)}</span>`);
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
    ? `<div class="actual-block linked" data-detail="${escapeHtml(linkedActual.id)}">
        <div class="lbl">Выполнено</div>
        <div class="line">
          <b>${((linkedActual.distance_m || 0) / 1000).toFixed(1)} км</b> ·
          ${formatDuration(linkedActual.duration_min)}
          ${linkedActual.hr_avg ? ` · HR ${linkedActual.hr_avg}` : ''}
        </div>
        <div class="when">${linkedActual.date} · ${escapeHtml(SPORT_NAME[linkedActual.sport] || linkedActual.sport)}</div>
        <div class="actual-actions">
          <button class="action" data-detail="${escapeHtml(linkedActual.id)}">Разбор тренировки →</button>
          <button class="action secondary" data-unlink="${escapeHtml(workout.id)}">Отвязать</button>
        </div>
      </div>`
    : `<div class="actual-block empty">
        <div class="lbl">Факт не привязан</div>
        <div class="facts">${factList(workout)}</div>
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
      ${actualBlock}
    </div>
    <div id="detail-block"></div>`;

  state.openWorkoutId = workoutId;
  state.detailId = null;
  cardWrap.classList.remove('hidden');
  detailWrap.classList.add('hidden');
  picker.classList.add('hidden');

  const slug = slotSlug(workout);
  try {
    // Запись в историю: если мы уже на уровне тренировки — заменяем
    // текущую (переходим между тренировками), иначе добавляем новую.
    // Разбор поверх тренировки — отдельная запись, см. showDetail.
    const onWorkoutLevel = history.state
      && history.state.page === 'detail'
      && !history.state.actual;
    if (onWorkoutLevel) {
      history.replaceState({page: 'detail', slot: workoutId}, '', '#' + slug);
    } else {
      history.pushState({page: 'detail', slot: workoutId}, '', '#' + slug);
    }
  } catch (error) {
    history.replaceState(null, '', '#' + slug);
  }
  render();
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
  state.detailId = null;
  cardWrap.classList.add('hidden');
  detailWrap.classList.add('hidden');
  picker.classList.remove('hidden');
  if (window.location.hash) {
    try { history.replaceState(history.state, '', ' '); } catch (error) { /* нет */ }
  }
  renderScreen();
  bar.innerHTML = chromeBar();
  // Прокрутка вверх — только если мы не наверху: лишний scrollTo
  // вызывает пересчёт раскладки и задерживает кадр.
  if (window.scrollY > 0) window.scrollTo(0, 0);
}

/* Назад с экрана разбора — к тренировке, из которой пришли.
 *
 * Уровни вложенности: неделя → тренировка → разбор. Назад убирает
 * верхний уровень, а не сбрасывает всё сразу.
 */
function showDetailBack() {
  const cameFromDetail = history.state && history.state.actual;
  state.detailId = null;

  if (cameFromDetail) {
    // Возврат — шаг назад по истории. Запись с разбором должна из
    // истории уйти, а не перезаписаться: иначе второй «назад» не
    // дойдёт до списка. Экраном займётся popstate.
    history.back();
    return;
  }

  detailWrap.classList.add('hidden');
  if (state.openWorkoutId) {
    showWorkout(state.openWorkoutId);
    return;
  }
  showPicker();
}

/* Структура тренировки: сеты собираются обратно из group/round. */
function structureHtml(workout) {
  const steps = workout.steps || [];
  if (!steps.length) return '<div class="empty">Нет структуры</div>';

  const blocks = groupBlocks(steps);
  return `<ol class="structure-list">${blocks.map(renderBlock).join('')}</ol>`;
}

/* Один блок структуры: одиночный шаг, сет или упражнение. */
function renderBlock(block) {
  const steps = block.steps;

  // Упражнения ОФП: у каждого шага есть название и повторы в focus_value.
  // Проверка именно по обоим полям: у разминки focus_value пустой.
  if (isExerciseBlock(steps)) {
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
  if (isSetBlock(steps)) {
    const reps = setReps(steps);
    // Название сета часто уже содержит число повторов («3×800м»).
    // Повторять его рядом — значит сказать одно и то же дважды.
    const repsTag = nameHasReps(block.group)
      ? ''
      : `<span class="step-reps">${repsLabel(reps)}</span>`;
    return `<li class="step step-set">
        <div class="step-head">
          <span class="step-phase">${escapeHtml(block.group || 'сет')}</span>
          ${repsTag}
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
  // Записи в кэш — в фоне: экран не должен ждать IndexedDB.
  const cacheWrites = [];
  try {
    // Запросы идут параллельно, а не по очереди: пять последовательных
    // round-trip'ов на телефоне — это и есть «несколько секунд».
    const [snapshot, weeks, current] = await Promise.all([
      api.getSnapshot(),
      api.getWeeks().catch(() => null),
      api.getCurrentWeek().catch(() => null),
    ]);

    state.version = snapshot.version;
    state.season = snapshot.data.season;
    state.athlete = snapshot.data.athlete;
    state.stale = false;
    state.cachedAt = Date.now();
    // Кэш пишем после отрисовки: IndexedDB на телефоне медленный, и
    // ждать его перед показом экрана незачем.
    cacheWrites.push(putCache('snapshot', snapshot.data, snapshot.version));

    if (weeks) {
      state.weeks = weeks.data.weeks || [];
      cacheWrites.push(putCache('weeks', state.weeks, snapshot.version));
    } else {
      state.weeks = state.weeks || [];
    }

    // Текущая неделя — по дате на сервере: клиент не знает про начало сезона.
    // Ручной выбор в localStorage перекрывает.
    if (!state.seasonWeek && current) {
      state.seasonWeek = current.data.season_week;
    }
    const seasonWeek = state.seasonWeek;

    // недели может не быть — это не ошибка, а пустое состояние
    const [week, actual] = await Promise.all([
      api.getWeek(seasonWeek).catch((error) => {
        if (error.code === 'not_found') return null;
        throw error;
      }),
      api.getActual(seasonWeek).catch(() => null),
    ]);

    if (week) {
      state.week = week.data;
      cacheWrites.push(putCache(`week:${seasonWeek}`, week.data, snapshot.version));
    } else {
      state.week = null;
    }

    if (actual) {
      state.actual = actual.data.sessions || [];
      cacheWrites.push(putCache(`actual:${seasonWeek}`, state.actual, snapshot.version));
    } else {
      state.actual = (await getCache(`actual:${seasonWeek}`))?.value || [];
    }

    state.summary = state.week ? state.week.summary : null;
    state.message = null;
  } catch (error) {
    await loadFromCache();
    showMessage('Сервер недоступен — показан последний известный снимок', 'error');
  }
  render();
  // Кэш дописываем после отрисовки, ошибки в нём ничего не ломают.
  await Promise.allSettled(cacheWrites);
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

/* Ошибка, из-за которой команда бессмысленна: повтор не поможет.
 * Такую команду убираем из очереди, иначе она блокирует все следующие.
 */
function isPermanentError(error) {
  return error.code === 'degraded'
    || error.code === 'invalid_command'
    || error.code === 'not_found';
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
      if (isPermanentError(error)) {
        // Команда не выполнима — убираем, чтобы не блокировать очередь.
        await removeCommand(command.id);
        showMessage(error.message, 'error');
        continue;
      }
      if (error.code === 'version_conflict') {
        // Состояние изменилось на сервере: перечитываем и повторяем
        // команду с новой версией. Плашка тут не помогала — она висела
        // и ничего не делала.
        await load();
        command.expected_version = state.version;
        await api.sendCommand(command);
        await removeCommand(command.id);
        continue;
      }
      if (!error.code) {
        showMessage('Нет связи с сервером — команда ждёт в очереди', 'error');
      } else {
        showMessage(error.message, 'error');
      }
      break;
    }
  }
  state.outbox = await pendingCommands();
}

/* ------------------------------------------------------------------ события */

document.addEventListener('click', async (event) => {
  const target = event.target;
  // Ищем ближайшего предка с признаком: тап может прийти по иконке или
  // подписи внутри кнопки — тогда target не сама кнопка.
  const closest = (selector) => (target.closest ? target.closest(selector) : null);

  // Тап по плашке сообщения — закрыть её
  if (closest('#msg')) {
    state.message = null;
    if (state.messageTimer) clearTimeout(state.messageTimer);
    state.messageTimer = null;
    render();
    return;
  }

  const slot = closest('[data-slot]');

  // Тап по плашке тренировки — открыть детали
  if (slot) {
    showWorkout(slot.dataset.slot);
    return;
  }

  // Кнопка «назад»: убираем верхний уровень вложенности
  if (closest('#backBtn')) {
    if (state.detailId) {
      // с разбора — к тренировке
      showDetailBack();
    } else if (history.state && history.state.page === 'detail') {
      history.back();
    } else {
      showPicker();
    }
    return;
  }

  // Переход в раздел: тап по кнопке, её иконке или подписи.
  const screen = closest('[data-screen]');
  if (screen) {
    state.screen = screen.dataset.screen;
    // showPicker() уже перерисовывает экран и шапку — второй render()
    // делал ту же работу дважды.
    showPicker();
    return;
  }

  if (closest('#refresh')) {
    await load();
    await flushOutbox();
    render();
    return;
  }

  // Тап по факту — связать с открытой тренировкой
  const fact = closest('[data-actual]');
  if (fact) {
    await linkActual(fact.dataset.actual, fact.dataset.workout);
    return;
  }

  // Отвязать факт от тренировки
  const unlink = closest('[data-unlink]');
  if (unlink) {
    await unlinkActual(unlink.dataset.unlink);
    return;
  }

  // Разбор тренировки: загрузить детали или разобрать FIT
  const detail = closest('[data-detail]');
  if (detail) {
    await loadDetail(detail.dataset.detail);
    return;
  }

  if (closest('#pull')) {
    showMessage('Загружаю факт из Garmin…');
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

  if (closest('#close')) {
    showMessage('Закрываю неделю…');
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

/* Кнопка «назад» на телефоне — убрать верхний уровень вложенности.
 *
 * Уровни: неделя → тренировка → разбор. Свайп назад из разбора
 * возвращает к тренировке, из тренировки — к списку.
 */
window.addEventListener('popstate', (event) => {
  const current = event.state;
  if (current && current.page === 'detail' && current.actual) {
    // Вперёд: открыт разбор.
    state.detailId = current.actual;
    detailWrap.classList.remove('hidden');
    cardWrap.classList.add('hidden');
    picker.classList.add('hidden');
    detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
    render();
    return;
  }
  if (current && current.page === 'detail') {
    // Назад с разбора: мы на уровне тренировки.
    state.detailId = null;
    detailWrap.classList.add('hidden');
    showWorkout(current.slot);
    return;
  }
  showPicker();
});

/* Разбор тренировки: сначала пробуем готовый, иначе разбираем FIT. */
async function loadDetail(actualId) {
  // Экран разбора открываем сразу — пока грузится, он пустой.
  showDetail(actualId);
  showMessage('Загружаю разбор…');
  render();
  try {
    const detail = await api.getDetail(actualId);
    state.detail = detail.data;
    state.message = null;
    detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
    render();
    return;
  } catch (error) {
    if (error.code !== 'not_found') {
      showMessage(error.message, 'error');
      render();
      return;
    }
  }

  // Разбора нет — разбираем FIT через Garmin
  showMessage('Разбираю FIT-файл…');
  render();
  await queueCommand({
    id: `fit-${actualId}-${Date.now()}`,
    type: 'import_fit',
    args: { actual_id: actualId },
    reason: 'разбор тренировки из Garmin',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  try {
    const detail = await api.getDetail(actualId);
    state.detail = detail.data;
  } catch (error) {
    showMessage('Разбор не удался', 'error');
  }
  detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
  render();
}
/* Связать факт с тренировкой. */
async function linkActual(actualId, workoutId) {
  showMessage('Связываю…');
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
  showMessage('Отвязываю…');
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
  // Событие с той же версией — перезагрузка не нужна. Раньше сравнение
  // шло с версией сезона, а клиент держит глобальную: расхождение было
  // постоянным, и каждое событие перезагружало данные целиком.
  if (event.version === state.version) return;
  load();
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
