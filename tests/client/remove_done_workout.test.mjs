/* Удаление тренировки с фактом — нельзя.
 *
 * Репорт Кирилла (22.11.2026): после перепланирования остатка в неделе
 * оказалось 10 тренировок вместо 8 — две с одинаковыми id. «Когда я
 * попробовал удалить дубликат из списка планирования, он удалил ещё и
 * сделанную тренировку.»
 *
 * Две стороны дефекта:
 *
 *   - на экране у выполненной тренировки стояла корзина, и её нажатие
 *     сносило сделанную работу вместе с фактом;
 *   - удаление идёт по запросу, а у дубликата и у выполненной запрос
 *     один — поэтому «удалить дубликат» и означало «удалить выполненную».
 *
 * Здесь проверяется клиент: корзины у выполненной тренировки быть не
 * должно, а у тренировки без факта — должна.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

function makeWeek(status, extra = {}) {
  return {
    id: 'W7',
    season_week: 7,
    start: '2026-11-22',
    end: '2026-11-28',
    status,
    focus: 'Набираем 57 км за 8 тренировок',
    load_target: {hours: 7.71, sessions: 10, distance_m: 57618},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: [
      {
        id: 'w-r7-4', request_id: 'r7-4', sport: 'run', kind: 'long',
        focus: 'Длинный бег',
        objective: {name: 'Длинный бег', day: 'ВС', time: '11:00'},
        duration_min: 81, status: 'done', actual_id: 'a-1', steps: [],
      },
      {
        id: 'w-ofp-1', request_id: 'r7-other-3', sport: 'ofp', kind: 'ofp',
        focus: 'Общая физическая подготовка',
        objective: {name: 'Общая физическая подготовка', day: 'ВС', time: '11:00'},
        duration_min: 30, status: 'done', actual_id: 'a-2', steps: [],
      },
      {
        id: 'w-r7-1', request_id: 'r7-1', sport: 'run', kind: 'r',
        focus: 'Работа в повторном темпе',
        objective: {name: 'Работа в повторном темпе', day: 'ПН', time: '18:45'},
        duration_min: 52, status: 'planned', actual_id: null, steps: [],
      },
    ],
    summary: null,
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

const ACTUAL = [
  {id: 'a-1', date: '2026-11-22', sport: 'run', duration_min: 80,
   distance_m: 14534, linked_workout_id: 'w-r7-4'},
  {id: 'a-2', date: '2026-11-22', sport: 'hiit', duration_min: 15,
   distance_m: 0, linked_workout_id: 'w-ofp-1'},
];

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

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

async function loadApp({week, onCommand} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 7,
    snapshot: SNAPSHOT,
    week: week || makeWeek('proposed'),
    actual: ACTUAL,
    weeks: [],
    details: {},
    sent: [],
    onCommand,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
}

/* Корзина у конкретной тренировки. */
function removeButtonFor(workoutId) {
  return document.querySelector(`[data-remove-workout="${workoutId}"]`);
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('у выполненной тренировки нет кнопки удаления', async () => {
  await loadApp({week: makeWeek('proposed')});

  assert.ok(!removeButtonFor('w-r7-4'),
    'у выполненной тренировки стоит корзина — её нажатие снесёт факт');
  assert.ok(!removeButtonFor('w-ofp-1'),
    'у выполненного ОФП стоит корзина');
});

test('у тренировки без факта кнопка удаления есть', async () => {
  await loadApp({week: makeWeek('proposed')});

  assert.ok(removeButtonFor('w-r7-1'),
    'у невыполненной тренировки нет корзины — её нечем убрать');
});

test('после переплана у выполненной по-прежнему нет корзины', async () => {
  /* Неделя после переплана — proposed, и корзины там есть. Но у
   * выполненной — нет: сделанную тренировку удалить нельзя. */
  await loadApp({week: makeWeek('proposed')});

  assert.ok(!removeButtonFor('w-r7-4'),
    'у выполненной тренировки появилась корзина после переплана');
  assert.ok(removeButtonFor('w-r7-1'),
    'у невыполненной тренировки пропала корзина');
});

test('у висяка без факта корзина есть, у висяка с фактом — нет', async () => {
  await loadApp({week: makeWeek('proposed', {
    unplaced: [
      {id: 'r7-5', request_id: 'r7-5', sport: 'run', kind: 'easy',
       focus: 'Лёгкий бег', duration_min: 28, workout_id: 'w-r7-5'},
      {id: 'r7-other-3', request_id: 'r7-other-3', sport: 'ofp',
       kind: 'ofp', focus: 'ОФП', duration_min: 30, workout_id: 'w-ofp-1',
       actual_id: 'a-2'},
    ],
    workouts: [
      {
        id: 'w-r7-5', request_id: 'r7-5', sport: 'run', kind: 'easy',
        focus: 'Лёгкий бег', objective: {name: 'Лёгкий бег'},
        duration_min: 28, status: 'planned', actual_id: null, steps: [],
      },
    ],
  })});

  assert.ok(removeButtonFor('w-r7-5'),
    'у висяка без факта нет корзины');
  assert.ok(!removeButtonFor('w-ofp-1'),
    'у висяка с фактом есть корзина — её нажатие снесёт выполненное');
});
