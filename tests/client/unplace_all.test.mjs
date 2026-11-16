/* Кнопка «Отвязать все» — отвязать тренировки без факта от слотов.
 *
 * Нужно, когда хочется поменять дни: тренировки теряют слот и
 * становятся висяками, их можно привязать к другому окну. Неделя
 * при этом остаётся активной, а план не пересобирается.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и
 * обработчиками клика. Вместо сети и IndexedDB подставляются заглушки.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

function makeWeek(status, extra = {}) {
  return {
    id: 'W3',
    season_week: 3,
    start: '2026-10-25',
    end: '2026-10-31',
    status,
    focus: 'Развиваем VO2max',
    load_target: {hours: 6.24, sessions: 7, distance_m: 35000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: [
      {
        id: 'w-1', request_id: 'r1', sport: 'run', kind: 'quality', focus: 'Z6',
        objective: {name: 'Качественная: VO2max', day: 'ПН', time: '18:45'},
        duration_min: 51, status: 'done', actual_id: 'a-1', steps: [],
      },
      {
        id: 'w-2', request_id: 'r2', sport: 'run', kind: 'easy',
        focus: 'Лёгкий бег',
        objective: {name: 'Лёгкий бег', day: 'СР', time: '18:45'},
        duration_min: 45, status: 'planned', actual_id: null, steps: [],
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
  {id: 'a-1', date: '2026-10-26', sport: 'run', duration_min: 51,
   distance_m: 8000, linked_workout_id: 'w-1'},
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
    seasonWeek: 3,
    snapshot: SNAPSHOT,
    week: week || makeWeek('active'),
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

function sentCommands() {
  return globalThis.__fixture.sent || [];
}

/* Загрузка с перехватом отправленных команд. */
async function loadAppWithCommands(week) {
  const sent = [];
  await loadApp({
    week,
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 42, data: {status: 'applied'}});
    },
  });
  globalThis.__fixture.sent = sent;
  return sent;
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('активная неделя: есть кнопка «Отвязать все»', async () => {
  await loadApp({week: makeWeek('active')});

  const btn = document.querySelector('#unplace-all');
  assert.ok(btn, 'нет кнопки «Отвязать все»');
  assert.match(btn.textContent, /Отвязать все/i);
});

test('кнопка «Отвязать все» шлёт команду unplace_all', async () => {
  const sent = await loadAppWithCommands(makeWeek('active'));

  click(document.querySelector('#unplace-all'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'unplace_all');
  assert.equal(sent[0].args.season_week, 3);
  assert.ok(sent[0].reason, 'у команды нет причины');
});

test('кнопка «Отвязать все» не у «Перепланировать остаток»', async () => {
  /* Это разные действия: «Отвязать все» оставляет неделю активной,
   * «Перепланировать остаток» возвращает её в proposed. */
  await loadApp({week: makeWeek('active')});

  assert.ok(document.querySelector('#unplace-all'));
  assert.ok(document.querySelector('#replan'));
  assert.notEqual(document.querySelector('#unplace-all').id,
    document.querySelector('#replan').id);
});

test('у предложенной недели кнопки «Отвязать все» нет', async () => {
  /* У proposed-недели тренировки и так можно переставлять. */
  await loadApp({week: makeWeek('proposed')});

  assert.ok(!document.querySelector('#unplace-all'),
    'у proposed-недели не должно быть «Отвязать все»');
});

test('у закрытой недели кнопки «Отвязать все» нет', async () => {
  await loadApp({week: makeWeek('closed')});

  assert.ok(!document.querySelector('#unplace-all'),
    'у закрытой недели не должно быть «Отвязать все»');
});

test('иконки в шапке не повторяются', async () => {
  /* Два разных действия в шапке — два разных знака. «Отвязать все»
   * кнопкой с текстом: действие нечастое, но спутать его с
   * перепланированием нельзя — и текст читается однозначно. */
  await loadApp({week: makeWeek('active')});

  const icons = [...document.querySelectorAll('.goal-acts .card-act')]
    .map((b) => b.textContent.trim());
  assert.ok(icons.length >= 2, `иконок в шапке мало: ${icons.length}`);
  assert.equal(new Set(icons).size, icons.length,
    `иконки в шапке повторяются: ${icons.join(' ')}`);
});

test('после «Отвязать все» экран не ломается', async () => {
  await loadAppWithCommands(makeWeek('active'));

  click(document.querySelector('#unplace-all'));
  await waitFor(() => sentCommands().length > 0);
  await waitFor(() => document.getElementById('picker').textContent.trim());

  assert.ok(document.querySelectorAll('#picker .slot').length > 0,
    'экран недели не отрисован после команды');
});

test('двойной тап по «Отвязать все» шлёт команду один раз', async () => {
  await loadAppWithCommands(makeWeek('active'));

  click(document.querySelector('#unplace-all'));
  const fresh = document.querySelector('#unplace-all');
  if (fresh) click(fresh);
  await waitFor(() => sentCommands().length > 0);
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.equal(sentCommands().length, 1, 'команда отправлена дважды');
});
