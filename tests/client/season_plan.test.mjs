/* UI-тесты вкладки «Сезон»: макро-план сезона.
 *
 * Проверяем то, что просил Кирилл: макро-план виден на вкладке «Сезон»,
 * у закрытых недель есть факт, текущие и будущие — без факта, и по
 * неделе можно перейти.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

const SEASON_PLAN = {
  id: 'S1',
  horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
  plans: [
    {id: 'g1', status: 'active', goal: '40:00',
     race_date: '2027-04-18', venue: 'S25 Berlin 10K'},
  ],
  phases: [
    {id: 'run_base', objective: 'Поднимаем базовый объём',
     week_from: 1, week_to: 2},
    {id: 'run_taper', objective: 'Снижаем объём', week_from: 3, week_to: 3},
  ],
  macro_weeks: [
    {season_week: 1, phase_id: 'run_base', focus: 'progression',
     goal_text: 'Развиваем базу', run_km: 27, total_h: 4.99,
     sessions_target: 6, deload: false, status: 'closed', has_fact: true,
     start: '2026-10-11', end: '2026-10-17'},
    {season_week: 2, phase_id: 'run_base', focus: 'vo2max',
     goal_text: 'Развиваем VO2max', run_km: 35, total_h: 6.24,
     sessions_target: 7, deload: false, status: null, has_fact: false,
     start: '2026-10-18', end: '2026-10-24'},
    {season_week: 3, phase_id: 'run_taper', focus: 'taper_race_pace',
     goal_text: 'Снимаем объём', run_km: 16, total_h: 3.15,
     sessions_target: 5, deload: true, status: null, has_fact: false,
     start: '2026-10-25', end: '2026-10-31'},
    {season_week: 4, phase_id: 'run_taper', focus: 'taper_race_pace',
     goal_text: 'Снимаем объём', run_km: 12, total_h: 2.8,
     sessions_target: 4, deload: true, status: null, has_fact: false,
     start: '2026-11-01', end: '2026-11-07'},
  ],
};

const WEEK = {
  id: 'W1', season_week: 1, start: '2026-10-11', end: '2026-10-17',
  status: 'closed', focus: 'Развиваем базу',
  load_target: {hours: 6.24, sessions: 7, distance_m: 35000},
  requests: [], assignments: [], unplaced: [],
  workouts: [], summary: null,
};

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

/* ------------------------------------------------------------------ dom */

let dom;

function setupDom() {
  dom = new JSDOM('<!doctype html><html><body>'
    + '<div id="appbar"></div><div id="picker"></div>'
    + '<div id="cardWrap" class="hidden"><div id="cardHost"></div></div>'
    + '<div id="detailWrap" class="hidden"><div id="detailHost"></div></div>'
    + '<nav id="nav"></nav></body></html>',
    {url: 'http://localhost/'});

  const put = (key, value) => Object.defineProperty(globalThis, key, {
    value, configurable: true, writable: true,
  });
  put('window', dom.window);
  put('document', dom.window.document);
  put('navigator', dom.window.navigator);
  put('location', dom.window.location);
  put('localStorage', dom.window.localStorage);
  put('history', dom.window.history);
  put('HTMLElement', dom.window.HTMLElement);
  put('Element', dom.window.Element);
  put('Node', dom.window.Node);
  put('CustomEvent', dom.window.CustomEvent);
  put('Event', dom.window.Event);
  put('MouseEvent', dom.window.MouseEvent);
  put('getComputedStyle', dom.window.getComputedStyle.bind(dom.window));
  return dom;
}

async function loadApp({week, seasonPlan} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 2,
    snapshot: SNAPSHOT,
    week: week || WEEK,
    actual: [],
    weeks: [],
    details: {},
    seasonPlan: seasonPlan === undefined ? SEASON_PLAN : seasonPlan,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.getElementById('nav').children.length > 0);
}

async function waitFor(predicate, timeout = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return false;
}

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

function openSeason() {
  click(document.querySelector('#nav [data-screen="season"]'));
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('вкладка «Сезон»: виден макро-план сезона', async () => {
  await loadApp();
  openSeason();

  const picker = document.getElementById('picker');
  assert.match(picker.textContent, /Макро-план сезона/);
  assert.match(picker.textContent, /Поднимаем базовый объём/, 'нет цели фазы');
  assert.match(picker.textContent, /Развиваем базу/, 'нет фокуса недели');
  assert.match(picker.textContent, /S25 Berlin 10K/, 'нет цели сезона');
  assert.match(picker.textContent, /2027-04-18/, 'нет даты гонки');
});

test('вкладка «Сезон»: недели по фазам, с фокусом и объёмом', async () => {
  await loadApp();
  openSeason();

  const rows = document.querySelectorAll('.macro-week');
  assert.equal(rows.length, 4, 'не все недели макро-плана показаны');

  const first = rows[0].textContent;
  assert.match(first, /W1/);
  assert.match(first, /Развиваем базу/);
  assert.match(first, /27 км/, 'нет километража');
  assert.match(first, /5\.0 ч|4\.99 ч/, 'нет часов');
});

/* В макроплане неделя стоит по номеру («W1»), а номер не говорит, когда
 * она идёт: W1 в начале сезона и W1 в середине — одно и то же слово.
 * Поэтому рядом с номером нужны даты. */
test('в макроплане у недели есть даты, а не только номер', async () => {
  await loadApp();
  openSeason();

  const rows = document.querySelectorAll('.macro-week');
  /* Один месяц — месяц пишется один раз: «11–17.10». */
  assert.match(rows[0].textContent, /11–17\.10/,
    `нет дат первой недели: ${rows[0].textContent}`);
  assert.match(rows[1].textContent, /18–24\.10/,
    `нет дат второй недели: ${rows[1].textContent}`);
  /* Месяц сменился — оба числа с месяцем. */
  assert.match(rows[3].textContent, /1–7\.11/,
    `нет дат четвёртой недели: ${rows[3].textContent}`);
});

test('вкладка «Сезон»: закрытая неделя помечена фактом', async () => {
  await loadApp();
  openSeason();

  const closed = document.querySelector('.macro-week.closed');
  assert.ok(closed, 'закрытая неделя не помечена');
  assert.match(closed.textContent, /факт/);
});

test('вкладка «Сезон»: текущая и будущие недели без факта', async () => {
  await loadApp();
  openSeason();

  const withFact = [...document.querySelectorAll('.macro-week')]
    .filter((row) => row.textContent.includes('факт'));
  assert.equal(withFact.length, 1, 'факт должен быть только у закрытой недели');

  const current = document.querySelector('.macro-week.current');
  assert.ok(current, 'текущая неделя не помечена');
  assert.match(current.textContent, /W2/);
  assert.ok(!current.textContent.includes('факт'), 'у текущей недели нет факта');
});

test('вкладка «Сезон»: тап по закрытой неделе открывает её', async () => {
  await loadApp();
  openSeason();

  const closed = document.querySelector('.macro-week.closed');
  assert.ok(closed, 'закрытая неделя не найдена');
  click(closed);
  await waitFor(() => document.getElementById('appbar').textContent.includes('Неделя 1'));

  assert.match(document.getElementById('appbar').textContent, /Неделя 1/);
  assert.equal(localStorage.getItem('coach-app-week'), '1');
});

test('вкладка «Сезон»: будущая неделя не кликабельна', async () => {
  await loadApp();
  openSeason();

  // Текущая неделя — W2, и она сама ещё не спланирована: планировать
  // надо её. W4 — дальше текущей, её не планируют.
  const future = [...document.querySelectorAll('.macro-week')]
    .find((row) => row.textContent.includes('W4'));
  assert.ok(future, 'дальняя неделя не найдена');
  assert.equal(future.tagName, 'DIV', 'дальняя неделя не кликабельна');
  assert.ok(!future.hasAttribute('data-week'));
});

test('вкладка «Сезон»: неделя, которую планируем, кликабельна', async () => {
  await loadApp();
  openSeason();

  // W2 — текущая неделя, плана у неё нет: её и предлагают. Планировать
  // можно до закрытия предыдущей (I45).
  const next = [...document.querySelectorAll('.macro-week')]
    .find((row) => row.textContent.includes('W2'));
  assert.ok(next, 'планируемая неделя не найдена');
  assert.equal(next.tagName, 'BUTTON', 'планируемая неделя должна быть кликабельна');
  assert.equal(next.dataset.week, '2');
});

test('вкладка «Сезон»: без макро-плана — понятное сообщение', async () => {
  await loadApp({seasonPlan: {horizon: SNAPSHOT.season.horizon, plans: [],
                              phases: [], macro_weeks: []}});
  openSeason();

  const picker = document.getElementById('picker');
  assert.match(picker.textContent, /Макро-план сезона/);
  assert.match(picker.textContent, /не загружен/);
});
