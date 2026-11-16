/* Иконки действий недели в шапке карточки фокуса.
 *
 * Три действия живут иконками в шапке: предложить следующую неделю,
 * перепланировать остаток, закрыть неделю. Иконки должны быть разными:
 * одинаковые иконки у разных действий читаются как одно.
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

/* Макроплан — чтобы была следующая неделя, которую можно предложить. */
const SEASON_PLAN = {
  macro_weeks: [
    {season_week: 3, phase_id: 'base', status: 'active'},
    {season_week: 4, phase_id: 'base'},
  ],
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
    currentWeek: 3,
    snapshot: SNAPSHOT,
    week: week || makeWeek('active'),
    actual: ACTUAL,
    weeks: [],
    seasonPlan: SEASON_PLAN,
    details: {},
    sent: [],
    onCommand,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
}

/* Иконка действия — текст кнопки. */
function iconOf(selector) {
  const el = document.querySelector(selector);
  return el ? el.textContent.trim() : '';
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('иконка «предложить следующую неделю» отличается от иконки раздела «Неделя»', async () => {
  /* Одинаковые иконки у разных действий читаются как одно действие:
   * 📅 у «следующей недели» совпадала с 📅 в нижней навигации. */
  await loadApp({week: makeWeek('active')});

  const nextIcon = iconOf('#plan-next-week');
  const weekSectionIcon = iconOf('#nav [data-screen="week"] .ico');

  assert.ok(nextIcon, 'нет кнопки «предложить следующую неделю»');
  assert.ok(weekSectionIcon, 'нет иконки раздела «Неделя»');
  assert.notEqual(nextIcon, weekSectionIcon,
    'иконка «следующей недели» совпадает с иконкой раздела «Неделя»');
  /* Календарь у «следующей недели» читался как «текущая неделя»:
   * 📅 означает «сейчас», а не «вперёд». */
  assert.doesNotMatch(nextIcon, /📅/,
    'у «следующей недели» календарь 📅 — он читается как текущая неделя');
});

test('у трёх действий недели разные иконки', async () => {
  /* Следующая неделя, перепланирование остатка, закрытие недели —
   * три разных действия и три разных знака. */
  await loadApp({week: makeWeek('active')});

  const icons = [
    iconOf('#plan-next-week'),
    iconOf('#replan'),
    iconOf('#close'),
  ];

  assert.ok(icons.every((icon) => icon), 'какое-то из действий без иконки');
  assert.equal(new Set(icons).size, 3,
    `иконки действий недели повторяются: ${icons.join(' ')}`);
});

test('«Перепланировать остаток» — иконка в шапке, а не кнопка внизу', async () => {
  /* Кнопка под текстом занимает много места на телефоне, а действие
   * нечастое: его место — в шапке, среди других иконок. */
  await loadApp({week: makeWeek('active')});

  const btn = document.querySelector('#replan');
  assert.ok(btn, 'нет кнопки «Перепланировать остаток»');
  assert.ok(btn.closest('.goal-acts'),
    'кнопка перепланирования не в шапке карточки фокуса');
  assert.ok(!btn.classList.contains('action'),
    'перепланирование осталось широкой кнопкой — она занимает место');
});

test('иконка перепланирования — не та же, что у следующей недели', async () => {
  await loadApp({week: makeWeek('active')});

  assert.notEqual(iconOf('#replan'), iconOf('#plan-next-week'),
    'перепланирование и следующая неделя подписаны одинаковой иконкой');
});

test('у иконок есть подписи: title и aria-label', async () => {
  /* У иконки без подписи нет имени: человек не знает, что она делает.
   * Подпись обязательна и человеку, и тесту. */
  await loadApp({week: makeWeek('active')});

  for (const selector of ['#plan-next-week', '#replan', '#close']) {
    const el = document.querySelector(selector);
    assert.ok(el, `нет кнопки ${selector}`);
    assert.ok(el.getAttribute('title'), `у ${selector} нет title`);
    assert.ok(el.getAttribute('aria-label'), `у ${selector} нет aria-label`);
  }
});

test('иконка перепланирования говорит, что это остаток недели', async () => {
  await loadApp({week: makeWeek('active')});

  const label = document.querySelector('#replan').getAttribute('aria-label');
  assert.match(label, /остат/i,
    'подпись не говорит, что перепланируется остаток');
});

test('нажатие по иконке перепланирования шлёт команду', async () => {
  const sent = [];
  await loadApp({
    week: makeWeek('active'),
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 42, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#replan'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'replan_remainder');
});
