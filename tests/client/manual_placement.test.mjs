/* Ручная привязка тренировок к дням недели — на клиенте.
 *
 * Авто-привязка работает плохо, и время тренировки выбирает
 * пользователь. Проверяем:
 *  - висяки показаны списком под размещёнными тренировками;
 *  - тап по висяку открывает выбор окна;
 *  - выбор окна шлёт команду `place_unplaced` с нужными аргументами;
 *  - проверок нет: занятое окно не мешает.
 */
import {test, before} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

const WEEK = {
  id: 'W4',
  season_week: 4,
  start: '2026-11-01',
  end: '2026-11-07',
  status: 'proposed',
  focus: 'Проверяем форму на контрольной точке',
  load_target: {hours: 7.2, sessions: 9, distance_m: 56000},
  requests: [
    {id: 'r4-6', sport: 'run', kind: 'easy', focus: 'Лёгкий бег', duration_min: 43},
  ],
  assignments: [],
  unplaced: [
    {id: 'r4-6', sport: 'run', kind: 'easy', focus: 'Лёгкий бег', duration_min: 43},
    {id: 'r4-7', sport: 'run', kind: 'easy', focus: 'Лёгкий бег', duration_min: 48},
  ],
  workouts: [
    {
      id: 'w-r4-1',
      request_id: 'r4-1',
      sport: 'run',
      kind: 'long',
      focus: 'Длинный бег',
      objective: {name: 'Длинный бег', day: 'СР', date: '2026-11-04'},
      day: 'СР',
      date: '2026-11-04',
      slot_id: 'win-СР-1',
      time: '17:00',
      duration_min: 79,
      status: 'planned',
      actual_id: null,
      steps: [],
    },
    /* Непривязанная тренировка: у неё нет дня. В `week.workouts` она
     * лежит рядом с размещёнными, и без фильтра показывалась бы
     * дважды — и здесь, и в списке висяков. */
    {
      id: 'w-r4-6',
      request_id: 'r4-6',
      sport: 'run',
      kind: 'easy',
      focus: 'Лёгкий бег',
      objective: {name: 'Лёгкий бег'},
      duration_min: 43,
      status: 'planned',
      actual_id: null,
      steps: [],
    },
    {
      id: 'w-r4-7',
      request_id: 'r4-7',
      sport: 'run',
      kind: 'easy',
      focus: 'Лёгкий бег',
      objective: {name: 'Лёгкий бег'},
      duration_min: 48,
      status: 'planned',
      actual_id: null,
      steps: [],
    },
  ],
};

const SLOTS = [
  {id: 'win-ВС-1', day: 0, day_name: 'ВС', start: '11:00', end: '13:00', capacity_min: 120,
   forbidden_sports: []},
  {id: 'win-ПН-1', day: 1, day_name: 'ПН', start: '18:45', end: '20:15', capacity_min: 90,
   forbidden_sports: []},
  {id: 'win-ВТ-2', day: 2, day_name: 'ВТ', start: '18:30', end: '19:45', capacity_min: 75,
   forbidden_sports: ['bike', 'swim']},
  {id: 'win-СР-1', day: 3, day_name: 'СР', start: '17:00', end: '19:00', capacity_min: 120,
   forbidden_sports: ['bike']},
];

/* ------------------------------------------------------------------ окружение */

function setupDom() {
  const dom = new JSDOM(`<!doctype html><html><body>
    <header class="appbar" id="appbar"></header>
    <main class="app" id="picker"></main>
    <main class="app hidden" id="cardWrap"><div id="cardHost"></div></main>
    <main class="app hidden" id="detailWrap"><div id="detailHost"></div></main>
    <nav class="bottomnav" id="nav"></nav>
  </body></html>`, {url: 'http://localhost:8080/', pretendToBeVisual: true});

  const put = (name, value) => {
    Object.defineProperty(globalThis, name, {
      value, writable: true, configurable: true, enumerable: true,
    });
  };

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

const commands = [];

async function loadApp(overrides = {}) {
  setupDom();
  commands.length = 0;
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    snapshot: {version: 42, seasonWeek: 4},
    week: overrides.week || WEEK,
    actual: [],
    weeks: [],
    slots: overrides.slots || SLOTS,
    details: {},
    onCommand: (command) => {
      commands.push(command);
      return {status: 'applied', new_version: 43};
    },
  };

  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.unplaced-row').length > 0);
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

/* ------------------------------------------------------------------ тесты */

before(async () => {
  await loadApp();
});

test('название тренировки — по-русски, а не ключ', () => {
  const names = [...document.querySelectorAll('button.slot .name')]
    .map((n) => n.textContent.trim());
  for (const name of names) {
    assert.doesNotMatch(name, /^(easy|long|quality|bike|swim|ofp)$/,
      `в названии тренировки внутренний ключ: ${name}`);
  }
});

test('описание тренировки — по-русски, а не ключ вида спорта', () => {
  const focuses = [...document.querySelectorAll('button.slot .focus')]
    .map((n) => n.textContent.trim());
  for (const focus of focuses) {
    assert.doesNotMatch(focus, /^(bike|swim|ofp|run)$/,
      `в описании тренировки внутренний ключ: ${focus}`);
  }
});

test('висяки показаны списком под тренировками', () => {
  const rows = document.querySelectorAll('.unplaced-row');
  assert.equal(rows.length, 2, 'висяки не показаны');
  const text = document.getElementById('picker').textContent;
  assert.match(text, /Не привязано/, 'нет заголовка списка висяков');
  assert.match(text, /Лёгкий бег/, 'нет описания висяка');
});

test('непривязанная тренировка не показана дважды', () => {
  /* Дефект: в `week.workouts` лежат все тренировки недели, включая
   * непривязанные. Без фильтра каждая показывалась дважды: в списке
   * размещённых и в списке висяков — и неделя читалась как «18
   * тренировок» вместо девяти. */
  const placed = document.querySelectorAll('button.slot');
  assert.equal(placed.length, 1,
    `в списке размещённых ${placed.length} тренировок, а размещена одна`);

  const unplaced = document.querySelectorAll('.unplaced-row');
  assert.equal(unplaced.length, 2, 'висяки показаны не все');

  /* Счётчик — «размещено из всех», а не «всего». */
  const header = document.querySelector('.slots-header');
  assert.match(header.textContent, /1 из 3/,
    `счётчик тренировок: ${header.textContent.trim()}`);
});

test('висяки идут после размещённых тренировок', () => {
  const picker = document.getElementById('picker');
  const slotPos = picker.innerHTML.indexOf('slots-list');
  const unplacedPos = picker.innerHTML.indexOf('unplaced-list');
  assert.ok(slotPos >= 0, 'нет списка тренировок');
  assert.ok(unplacedPos > slotPos, 'висяки показаны выше тренировок');
});

test('тап по висяку открывает выбор окна', async () => {
  const row = document.querySelector('.unplaced-row');
  click(row);
  await waitFor(() => document.querySelectorAll('.slot-choice').length > 0);
  const choices = document.querySelectorAll('.slot-choice');
  assert.equal(choices.length, SLOTS.length, 'выбор окна не открылся');
});

test('выбор окна шлёт команду place_unplaced', async () => {
  const row = document.querySelector('.unplaced-row');
  click(row);
  await waitFor(() => document.querySelectorAll('.slot-choice').length > 0);

  const choice = document.querySelector('.slot-choice[data-bind-slot="win-ПН-1"]');
  assert.ok(choice, 'нет кнопки выбора окна понедельника');
  click(choice);
  await waitFor(() => commands.some((c) => c.type === 'place_unplaced'));

  const command = commands.find((c) => c.type === 'place_unplaced');
  assert.ok(command, 'команда place_unplaced не отправлена');
  assert.equal(command.args.request_id, 'r4-6');
  assert.equal(command.args.slot_id, 'win-ПН-1');
  assert.equal(command.args.start, '18:45');
  assert.equal(command.args.season_week, 4);
});

test('привязка не проверяет занятость окна', async () => {
  /* Окно win-СР-1 уже занято длинным бегом. Привязка к нему —
   * решение пользователя, и клиент его не отменяет. */
  commands.length = 0;
  const row = document.querySelector('.unplaced-row');
  click(row);
  await waitFor(() => document.querySelectorAll('.slot-choice').length > 0);

  const busy = document.querySelector('.slot-choice[data-bind-slot="win-СР-1"]');
  assert.ok(busy, 'занятого окна нет в списке');
  click(busy);
  await waitFor(() => commands.some((c) => c.type === 'place_unplaced'));

  const command = commands.find((c) => c.type === 'place_unplaced');
  assert.ok(command, 'занятое окно не предложено');
  assert.equal(command.args.slot_id, 'win-СР-1');
});

test('окно без велосипеда помечено «не подходит»', async () => {
  /* Базовый висяк — бег, и для бега подходят все окна. */
  const row = document.querySelector('.unplaced-row');
  click(row);
  await waitFor(() => document.querySelectorAll('.slot-choice').length > 0);

  const bad = [...document.querySelectorAll('.slot-choice.slot-bad')];
  assert.equal(bad.length, 0, 'для бега все окна подходят');
});

test('окно без велосипеда помечено для велосипеда', async () => {
  /* Висяк-велосипед: окно на асфальте не подходит. */
  const bike = {
    ...WEEK,
    unplaced: [
      {id: 'r4-bike', sport: 'bike', kind: 'bike', focus: 'Велосипед',
       duration_min: 60},
    ],
  };
  await loadApp({week: bike});

  const row = document.querySelector('.unplaced-row');
  click(row);
  await waitFor(() => document.querySelectorAll('.slot-choice').length > 0);

  const bad = [...document.querySelectorAll('.slot-choice.slot-bad')]
    .map((b) => b.dataset.bindSlot);
  assert.deepEqual(bad, ['win-ВТ-2', 'win-СР-1'],
    'окна без велосипеда помечены');

  const warn = document.querySelector('.slot-choice.slot-bad .warn');
  assert.ok(warn, 'нет пометки «не подходит»');
  assert.match(warn.textContent, /не подходит/);
});
