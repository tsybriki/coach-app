/* Нагрузка сезона на вкладке «Сезон».
 *
 * Кирилл (22.11.2026): «Нужно куда то добавить суммарный tss недели,
 * который, я надеюсь, не теряется при закрытии недели. Например, добавить
 * какую то аналитику на вкладку сезон. Сейчас там только план на сезон».
 *
 * Что тут проверяется:
 *  - карточка нагрузки есть на вкладке «Сезон»;
 *  - видны суммарная нагрузка, средняя в неделю и форма;
 *  - неделя с фактом показывает свою нагрузку — по ней видно динамику;
 *  - без факта карточки нет: ноль на экране читался бы как «посчитали
 *    — ноль».
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

const LOAD = {
  tss_total: 1691.1,
  tss_avg_week: 338.2,
  tss_avg_recent: 324.8,
  recent_weeks: 4,
  weeks_counted: 5,
  vo2max: 51,
  distance_km: 278.2,
  weekly: [
    {season_week: 3, tss: 392, complete: true},
    {season_week: 4, tss: 394.5, complete: true},
    {season_week: 5, tss: 394.9, complete: true},
    {season_week: 6, tss: 414.2, complete: true},
    {season_week: 7, tss: 95.5, complete: false},
  ],
};

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
  ],
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

async function waitFor(predicate, timeout = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return false;
}

async function loadApp({load} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 1,
    currentWeek: 1,
    snapshot: SNAPSHOT,
    seasonPlan: {...SEASON_PLAN, load: load === undefined ? LOAD : load},
    week: null,
    actual: [],
    weeks: [],
    details: {},
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.getElementById('picker').textContent.trim());
}

/* Карточка нагрузки на экране «Сезон». */
function loadCard() {
  return [...document.querySelectorAll('#picker .card')]
    .find((node) => node.textContent.includes('Нагрузка'));
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('вкладка «Сезон»: есть карточка нагрузки', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  assert.ok(loadCard(), 'нет карточки нагрузки на вкладке «Сезон»');
});

test('нагрузка: видна суммарная за сезон', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const text = loadCard().textContent;
  assert.match(text, /1691/, 'нет суммарной нагрузки за сезон');
  assert.match(text, /TSS/, 'нет единицы нагрузки');
});

test('нагрузка: видна средняя в неделю', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const text = loadCard().textContent;
  assert.match(text, /338/, 'нет средней нагрузки в неделю');
});

test('нагрузка: видна форма', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const text = loadCard().textContent;
  assert.match(text, /51/, 'нет формы');
  assert.match(text, /VO₂max|VO2max/, 'нет подписи формы');
});

test('нагрузка: видно объём сезона рядом с нагрузкой', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  /* Нагрузка без объёма не читается: 400 TSS — это 40 км лёгкого или
   * 200 км с интервалами. */
  assert.match(loadCard().textContent, /278/, 'нет объёма сезона');
});

test('нагрузка: неделя с фактом показывает свою нагрузку', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const text = loadCard().textContent;
  assert.match(text, /W6/, 'неделя с нагрузкой не помечена');
  assert.match(text, /414/, 'нагрузка недели не показана');
});

test('нагрузка: без факта карточки нет', async () => {
  await loadApp({load: {
    tss_total: 0, tss_avg_week: null, tss_avg_recent: null,
    recent_weeks: 0, weeks_counted: 0, vo2max: null, distance_km: 0,
    weekly: [],
  }});
  click(document.querySelector('#nav [data-screen="season"]'));

  assert.ok(!loadCard(),
    'без факта показана карточка с нулём — ноль читается как «посчитали — ноль»');
});

test('нагрузка: макро-план сезона остался на месте', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Макро-план сезона/, 'пропал макро-план сезона');
  assert.match(text, /Поднимаем базовый объём/, 'пропала фаза');
});

/* Клик по элементу — как настоящий. */
function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

test('нагрузка: незакрытая неделя помечена как незавершённая', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  /* W7 в процессе: 96 TSS вместо ~400. Рядом с закрытыми неделями
   * это читается как «нагрузка рухнула» — надо сказать, что неделя
   * не закончена. */
  const rows = [...document.querySelectorAll('#picker .load-row')];
  const w7 = rows.find((r) => r.textContent.includes('W7'));
  assert.ok(w7, 'нет строки W7');
  assert.match(w7.textContent, /не закончена|незакрыт/i,
    'незакрытая неделя не помечена');
});

test('нагрузка: закрытая неделя не помечена как незавершённая', async () => {
  await loadApp();
  click(document.querySelector('#nav [data-screen="season"]'));

  const rows = [...document.querySelectorAll('#picker .load-row')];
  const w6 = rows.find((r) => r.textContent.includes('W6'));
  assert.ok(w6, 'нет строки W6');
  assert.doesNotMatch(w6.textContent, /не закончена|незакрыт/i,
    'закрытая неделя помечена как незавершённая');
});
