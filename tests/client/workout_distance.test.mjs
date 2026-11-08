/* Километраж тренировки в плашке недели.
 *
 * Кирилл: «в плашке тренировки минуты, а не километры. Мне не хватает
 * километража основной работы — длинные тренировки хочу видеть в
 * километрах, а не только в минутах. Но чтобы это не раздуло карточки
 * тренировок».
 *
 * Проверяем: километраж есть в плашке и в карточке тренировки, рядом с
 * длительностью; тренировка без дистанции километров не показывает;
 * плашка не растёт — километраж стоит в правой колонке под временем.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

function makeWorkout(extra = {}) {
  return {
    id: 'w-long',
    request_id: 'r-long',
    sport: 'run',
    kind: 'long',
    focus: 'Длинный бег',
    objective: {name: 'Длинный бег', day: 'СР', date: '2026-11-04'},
    time: '17:00',
    duration_min: 77,
    distance_m: 14000,
    status: 'planned',
    actual_id: null,
    steps: [
      {
        id: 'run-long', role: 'work', sport: 'run',
        target_type: 'distance', target_value: 14000,
        focus: 'hr', focus_value: {zone: 'Z2', pace_min_per_km: '5:30'},
        duration_min: 77,
      },
    ],
    ...extra,
  };
}

const SLOTS = [
  {id: 'win-СР-1', day: 3, day_name: 'СР', start: '17:00', end: '19:00',
   capacity_min: 120, forbidden_sports: []},
];

function makeWeek(workouts) {
  return {
    id: 'W4',
    season_week: 4,
    start: '2026-11-01',
    end: '2026-11-07',
    status: 'proposed',
    focus: 'Набираем 56 км за 9 тренировок',
    load_target: {hours: 7.7, sessions: 9, distance_m: 56000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts,
  };
}

/* ------------------------------------------------------------------ dom */

let dom;

function setupDom() {
  dom = new JSDOM(`<!doctype html><html><body>
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

async function loadApp({workouts = [makeWorkout()], unplaced = []} = {}) {
  setupDom();
  const week = makeWeek(workouts);
  week.unplaced = unplaced;
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    currentWeek: 4,
    snapshot: {
      version: 42, seasonWeek: 4,
      season: {horizon: {start: '2026-10-11', end: '2027-09-18',
                         season_week_count: 49}},
      athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
    },
    week,
    actual: [],
    weeks: [],
    slots: SLOTS,
    details: {},
    seasonPlan: {
      id: 'S1',
      horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
      plans: [], phases: [],
      macro_weeks: [
        {season_week: 4, phase_id: 'p', focus: 'long', goal_text: 'Длинный',
         run_km: 56, total_h: 7.7, sessions_target: 9, deload: false,
         status: 'proposed', has_fact: false,
         start: '2026-11-01', end: '2026-11-07'},
        {season_week: 5, phase_id: 'p', focus: 'long', goal_text: 'Длинный',
         run_km: 57, total_h: 7.7, sessions_target: 9, deload: false,
         status: null, has_fact: false,
         start: '2026-11-08', end: '2026-11-14'},
      ],
    },
    onCommand: () => ({status: 'applied', new_version: 43}),
  };

  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('button.slot').length > 0);
}

beforeEach(() => {
  globalThis.__fixture = undefined;
});

/* ------------------------------------------------------------------ тесты */

test('в плашке тренировки километраж есть рядом с длительностью', async () => {
  await loadApp();

  const slot = document.querySelector('button.slot');
  const text = slot.textContent.replace(/\s+/g, ' ');

  assert.match(text, /1 ч 17 мин/, `нет длительности: ${text}`);
  assert.match(text, /14 км/, `нет километража: ${text}`);
});

test('километраж стоит в правой колонке под временем, а не в строке дня',
  async () => {
    await loadApp();

    const slot = document.querySelector('button.slot');
    const box = slot.querySelector('.dur-box');
    assert.ok(box, 'нет правой колонки с длительностью');
    assert.ok(box.querySelector('.dur'), 'в колонке нет длительности');
    assert.ok(box.querySelector('.km'), 'в колонке нет километража');

    // Километраж — внутри колонки, а не отдельным блоком рядом с
    // заголовком: плашка не растёт по высоте.
    const head = slot.querySelector('.slot-head');
    assert.equal(head.children.length, 3,
      `в шапке плашки лишние элементы: ${head.children.length}`);
  });

test('тренировка без дистанции километров не показывает', async () => {
  await loadApp({
    workouts: [makeWorkout({distance_m: 0, kind: 'bike', sport: 'bike'})],
  });

  const slot = document.querySelector('button.slot');
  assert.ok(!slot.querySelector('.km'),
    'тренировка без дистанции показала километраж');
  assert.doesNotMatch(slot.textContent, /0 км/,
    'показан ноль километров');
});

test('в карточке тренировки километраж есть рядом с длительностью',
  async () => {
    await loadApp();

    click(document.querySelector('button.slot'));
    await waitFor(() => document.getElementById('cardHost').textContent);

    const subtitle = document.querySelector('#cardHost .subtitle')
      .textContent.replace(/\s+/g, ' ');
    assert.match(subtitle, /1 ч 17 мин/, `нет длительности: ${subtitle}`);
    assert.match(subtitle, /14 км/, `нет километража: ${subtitle}`);
  });

test('непривязанная тренировка тоже показывает километраж', async () => {
  await loadApp({
    workouts: [],
    unplaced: [{
      id: 'r-long', sport: 'run', kind: 'long', focus: 'Длинный бег',
      duration_min: 77, distance_m: 14000, name: 'Длинный бег',
      objective: {}, steps: [],
    }],
  });

  const row = document.querySelector('.unplaced-row');
  assert.ok(row, 'нет строки непривязанной тренировки');
  const text = row.textContent.replace(/\s+/g, ' ');
  assert.match(text, /1 ч 17 мин/, `нет длительности: ${text}`);
  assert.match(text, /14 км/, `нет километража: ${text}`);
});

/* Формат километража: дробная часть не теряется. «14 км» вместо 14,3 —
 * это округление вниз, и оно врёт. */
test('километраж с дробной частью не округляется вниз', async () => {
  await loadApp({
    workouts: [makeWorkout({distance_m: 14300})],
  });

  const text = document.querySelector('button.slot').textContent
    .replace(/\s+/g, ' ');
  assert.match(text, /14,3 км/, `дробная часть потеряна: ${text}`);
});

test('целый километраж показывается без дробной части', async () => {
  await loadApp({
    workouts: [makeWorkout({distance_m: 14000})],
  });

  const text = document.querySelector('button.slot').textContent
    .replace(/\s+/g, ' ');
  assert.match(text, /14 км/, `лишняя дробная часть: ${text}`);
  assert.doesNotMatch(text, /14,0 км/, 'целый километраж с «,0»');
});
