/* Иконка привязки не должна открывать детали тренировки.
 *
 * Дефект (Кирилл): «Жмукаю на иконку, а попадаю в детали тренировки.
 * Когда возвращаюсь назад, развернут список слотов, куда тренировку
 * можно положить».
 *
 * Причина: обработчик `popstate` при возврате к списку не сбрасывал
 * `state.openWorkoutId`. Карточка скрывалась, но состояние продолжало
 * считать тренировку открытой — и клик по иконке уходил в
 * `showWorkout(state.openWorkoutId)`, то есть снова в детали.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и
 * обработчиками клика. Вместо сети и IndexedDB подставляются заглушки.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

const WEEK = {
  id: 'W4',
  season_week: 4,
  start: '2026-11-08',
  end: '2026-11-14',
  status: 'proposed',
  focus: 'Набираем 57 км',
  load_target: {hours: 7.7, sessions: 9, distance_m: 57000},
  requests: [],
  assignments: [],
  unplaced: [
    {
      id: 'r4-6', request_id: 'r4-6', workout_id: 'w-composed-1',
      sport: 'run', kind: 'easy', focus: 'Лёгкий бег',
      name: 'Лёгкий бег', duration_min: 46, objective: {}, steps: [],
    },
  ],
  workouts: [
    {
      id: 'w-1', request_id: 'r4-1', sport: 'run', kind: 'easy',
      focus: 'Лёгкий бег', objective: {name: 'Лёгкий бег', day: 'ПН'},
      duration_min: 55, status: 'planned', actual_id: null, steps: [],
    },
  ],
  summary: null,
};

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

const ACTUAL = [];
const SLOTS = [
  {id: 'win-ПН-1', day: 1, day_name: 'ПН', start: '18:45', end: '20:15', capacity_min: 90},
  {id: 'win-ВТ-1', day: 2, day_name: 'ВТ', start: '18:45', end: '20:15', capacity_min: 90},
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

async function loadApp({week} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    snapshot: SNAPSHOT,
    week: week || WEEK,
    actual: ACTUAL,
    weeks: [],
    slots: SLOTS,
    details: {},
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('#picker .slot, #picker .unplaced-row').length > 0);
}

/* Открыт ли экран деталей тренировки. */
function detailsOpen() {
  return !document.getElementById('cardWrap').classList.contains('hidden');
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('тап по иконке привязки не открывает детали тренировки', async () => {
  await loadApp();

  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  assert.ok(!detailsOpen(), 'иконка привязки открыла детали тренировки');
});

test('после возврата из деталей тап по иконке не открывает детали снова', async () => {
  /* Дефект Кирилла: «Жмукаю на иконку, а попадаю в детали тренировки.
   * Когда возвращаюсь назад, развернут список слотов».
   *
   * Сценарий: открыли тренировку, вернулись назад (свайп или кнопка),
   * потом нажали иконку привязки — и снова попали в детали.
   */
  await loadApp();

  /* Открываем тренировку из списка. */
  click(document.querySelector('#picker .slot'));
  await waitFor(() => detailsOpen());
  assert.ok(detailsOpen(), 'детали не открылись');

  /* Возвращаемся назад — так, как человек: кнопкой «←». */
  click(document.getElementById('backBtn'));
  await waitFor(() => !detailsOpen());
  assert.ok(!detailsOpen(), 'не вернулись к списку');

  /* Теперь тап по иконке привязки. */
  const bind = document.querySelector('#picker .unplaced-row [data-bind-pick]');
  assert.ok(bind, 'нет иконки привязки у висяка');
  click(bind);
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  assert.ok(!detailsOpen(),
    'после возврата из деталей тап по иконке снова открыл детали');
});

test('после свайпа назад из деталей тап по иконке не открывает детали', async () => {
  /* Тот же сценарий, но возврат — свайпом: обработчик popstate тоже
   * обязан сбрасывать открытую тренировку. */
  await loadApp();

  click(document.querySelector('#picker .slot'));
  await waitFor(() => detailsOpen());

  history.back();
  await waitFor(() => !detailsOpen());
  assert.ok(!detailsOpen(), 'свайп не вернул к списку');

  const bind = document.querySelector('#picker .unplaced-row [data-bind-pick]');
  assert.ok(bind, 'нет иконки привязки у висяка');
  click(bind);
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  assert.ok(!detailsOpen(),
    'после свайпа тап по иконке снова открыл детали');
});

test('иконка привязки после возврата открывает выбор окон под строкой', async () => {
  /* Не только «не открывает детали»: выбор окон должен открыться там,
   * где человек его ждёт — под строкой висяка. */
  await loadApp();

  click(document.querySelector('#picker .slot'));
  await waitFor(() => detailsOpen());
  click(document.getElementById('backBtn'));
  await waitFor(() => !detailsOpen());

  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  const wrap = document.querySelector('#picker .unplaced-row-wrap');
  assert.ok(wrap, 'нет обёртки строки висяка');
  assert.ok(wrap.querySelector('.slot-picker'),
    'выбор окон не под строкой висяка');
});
