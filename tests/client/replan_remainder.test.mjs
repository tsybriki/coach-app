/* Кнопка «Перепланировать остаток» на активной неделе.
 *
 * Команда `replan_remainder`: тренировки без факта возвращаются в
 * план, неделя — в `proposed`, и дальше работает обычный режим
 * propose (пересборка, ручная правка, активация).
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

/* Команды, которые клиент отправил серверу.
 *
 * Перехват — в `sendCommand` заглушки: она зовёт `onCommand` из
 * фикстуры, а та кладёт команду в `fixture.sent`.
 */
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

test('активная неделя: есть кнопка «Перепланировать остаток»', async () => {
  await loadApp({week: makeWeek('active')});

  const btn = document.querySelector('#replan');
  assert.ok(btn, 'нет кнопки «Перепланировать остаток»');
  assert.match(btn.textContent, /Перепланировать/i);
});

test('предложенная неделя: кнопки перепланирования нет', async () => {
  /* Перепланировать остаток — действие для недели в процессе.
   * У proposed-недели есть «Предложить заново»: это то же самое. */
  await loadApp({week: makeWeek('proposed')});

  assert.ok(!document.querySelector('#replan'),
    'у proposed-недели не должно быть «Перепланировать остаток»');
});

test('закрытая неделя: кнопки перепланирования нет', async () => {
  await loadApp({week: makeWeek('closed')});

  assert.ok(!document.querySelector('#replan'),
    'у закрытой недели не должно быть «Перепланировать остаток»');
});

test('нажатие шлёт команду replan_remainder', async () => {
  const sent = await loadAppWithCommands(makeWeek('active'));

  click(document.querySelector('#replan'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent.length, 1, 'команда отправлена не один раз');
  assert.equal(sent[0].type, 'replan_remainder');
  assert.equal(sent[0].args.season_week, 3);
  assert.ok(sent[0].reason, 'у команды нет причины');
});

test('после нажатия неделя остаётся на экране', async () => {
  /* Команда уходит, экран перерисовывается — но не должен ломаться. */
  await loadAppWithCommands(makeWeek('active'));

  click(document.querySelector('#replan'));
  await waitFor(() => sentCommands().length > 0);
  await waitFor(() => document.getElementById('picker').textContent.trim());

  assert.ok(document.querySelectorAll('#picker .slot').length > 0,
    'экран недели не отрисован после команды');
  assert.ok(document.querySelector('#replan'),
    'кнопка перепланирования пропала с экрана');
});

test('двойной тап отправляет команду один раз', async () => {
  /* Пока команда в полёте, кнопка не нажимается: вторая команда
   * пошла бы по устаревшей версии и потеряла бы первую.
   *
   * Клики — подряд, без ожидания: между ними команда ещё в очереди. */
  await loadAppWithCommands(makeWeek('active'));

  const btn = document.querySelector('#replan');
  click(btn);
  click(btn);
  await waitFor(() => sentCommands().length > 0);
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.equal(sentCommands().length, 1, 'команда отправлена дважды');
});
