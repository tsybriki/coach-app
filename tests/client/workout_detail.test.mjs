/* Внутренность тренировки на клиенте: описание шага и склонения.
 *
 * Дефекты, которые это ловит:
 *  - шаг показывался как «14000м» (метры без разделителя) и рядом
 *    повторялся в описании: «14000м @ 5:30/км» + «14.0 км · @ 5:30/км»;
 *  - счётчик шагов писал «1 шагов» — одна тренировка, один шаг.
 */
import {test, before} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

const WORKOUT = {
  id: 'w-r4-1',
  request_id: 'r4-1',
  sport: 'run',
  kind: 'long',
  focus: 'Длинный бег',
  objective: {name: 'Длинный бег', day: 'СР', date: '2026-11-04'},
  time: '17:00',
  duration_min: 77,
  status: 'planned',
  actual_id: null,
  steps: [
    {
      id: 'run-easy',
      role: 'work',
      sport: 'run',
      target_type: 'distance',
      target_value: 14000,
      focus: 'hr',
      focus_value: {zone: 'Z2', pace_min_per_km: '5:30'},
      duration_min: 77,
    },
  ],
};

const WEEK = {
  id: 'W4',
  season_week: 4,
  start: '2026-11-01',
  end: '2026-11-07',
  status: 'proposed',
  focus: 'Набираем 56 км за 9 тренировок · работа по плану',
  load_target: {hours: 7.7, sessions: 9, distance_m: 56000},
  requests: [],
  assignments: [],
  unplaced: [],
  workouts: [WORKOUT],
};

const SLOTS = [
  {id: 'win-СР-1', day: 3, day_name: 'СР', start: '17:00', end: '19:00',
   capacity_min: 120, forbidden_sports: []},
];

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

async function loadApp(overrides = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    snapshot: {version: 42, seasonWeek: 4},
    week: overrides.week || WEEK,
    actual: [],
    weeks: [],
    slots: overrides.slots || SLOTS,
    details: {},
    onCommand: () => ({status: 'applied', new_version: 43}),
  };

  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('button.slot').length > 0);
}

before(async () => {
  await loadApp();
});

test('объём шага — в километрах, а не в метрах', () => {
  document.querySelector('button.slot').click();
  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /14\.0 км/, `объём шага: ${text}`);
  assert.doesNotMatch(text, /14000м/, 'объём в метрах без разделителя');
});

test('объём и темп не повторяются дважды', () => {
  document.querySelector('button.slot').click();
  const text = document.getElementById('cardHost').textContent;
  const km = text.match(/14\.0 км/g) || [];
  assert.equal(km.length, 1,
    `объём показан ${km.length} раза: ${text}`);
});

test('счётчик шагов склоняется правильно', () => {
  document.querySelector('button.slot').click();
  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /1 шаг/, `счётчик шагов: ${text}`);
  assert.doesNotMatch(text, /1 шагов/, '«1 шагов» вместо «1 шаг»');
});

test('описание недели — про объём', () => {
  const text = document.getElementById('picker').textContent;
  assert.match(text, /Набираем 56 км/, `фокус недели: ${text}`);
  assert.doesNotMatch(text, /контрольной точке/,
    'в описании недели осталась цель тренировки');
});

/* Дата тренировки: в карточке деталей её не было вообще — был день
 * недели и время, а когда именно это было — непонятно. Дата короткая
 * («4.11»), отдельным мелким элементом: в строку «СР · 17:00 · 77 мин»
 * она не влезает, а рядом — в самый раз.
 */
test('в карточке тренировки есть дата — коротко и мелко', () => {
  document.querySelector('button.slot').click();

  const date = document.querySelector('#cardHost .when-date');
  assert.ok(date, 'в карточке тренировки нет даты');
  assert.equal(date.textContent.trim(), '4.11',
    'дата в карточке не в сокращённом виде');
  assert.ok(date.className.includes('when-date'),
    'нет класса .when-date');
});

test('в шапке тренировки дата рядом с днём недели', () => {
  document.querySelector('button.slot').click();

  const sub = document.getElementById('appbar').textContent;
  assert.match(sub, /СР/, 'в шапке нет дня недели');
  assert.match(sub, /4\.11/, 'в шапке нет даты');
});

test('показаны все шаги без названия группы', async () => {
  /* Дефект: у контрольной точки три шага без группы (разминка,
   * работа, заминка), и блок показывал только первый. В шапке
   * «3 шага», а в структуре — один. */
  const cp = {
    ...WEEK,
    workouts: [
      {
        id: 'w-cp',
        request_id: 'r4-cp',
        sport: 'run',
        kind: 'quality',
        focus: 'Темповый тест 3К',
        objective: {name: 'Темповый тест 3К', day: 'ПН'},
        time: '18:45',
        duration_min: 41,
        status: 'planned',
        actual_id: null,
        steps: [
          {id: 's1', role: 'work', sport: 'run', target_type: 'time',
           target_value: 15, focus: 'hr', focus_value: {zone: 'Z1'},
           duration_min: 15},
          {id: 's2', role: 'work', sport: 'run', target_type: 'distance',
           target_value: 3000, focus: 'pace',
           focus_value: {zone: 'Z4', pace_min_per_km: '4:40'},
           duration_min: 14},
          {id: 's3', role: 'work', sport: 'run', target_type: 'time',
           target_value: 12, focus: 'hr', focus_value: {zone: 'Z1'},
           duration_min: 12},
        ],
      },
    ],
  };
  await loadApp({week: cp});

  click(document.querySelector('button.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /15 мин/, `нет разминки: ${text}`);
  assert.match(text, /3\.0 км/, `нет работы на 3К: ${text}`);
  assert.match(text, /4:40/, `нет темпа теста: ${text}`);
  assert.match(text, /12 мин/, `нет заминки: ${text}`);
});
