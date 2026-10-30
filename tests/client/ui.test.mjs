/* UI-тесты: обход всех экранов и навигация.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и обработчиками
 * клика. Вместо сети и IndexedDB подставляются заглушки (см. helpers/).
 *
 * Проверяем:
 *  - каждый экран отдаёт разметку и не падает;
 *  - навигация между экранами работает;
 *  - открытие тренировки показывает детали, из них можно вернуться;
 *  - блок факта кликабелен (жалоба: «Дармен не посмотреть»);
 *  - число повторов не дублируется в названии сета;
 *  - конфликт версий не оставляет плашку «Состояние изменилось».
 */
import {test, before} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

import {nameHasReps, repsLabel, setReps} from '../../client/structure.js';

/* ------------------------------------------------------------------ фикстуры */

const WEEK = {
  id: 'W3',
  season_week: 3,
  start: '2026-10-25',
  end: '2026-10-31',
  status: 'proposed',
  focus: 'Развиваем VO2max',
  load_target: {hours: 6.24, sessions: 7, distance_m: 35000},
  requests: [],
  assignments: [],
  unplaced: [],
  workouts: [
    {
      id: 'w-1',
      request_id: 'r1',
      sport: 'run',
      kind: 'quality',
      focus: 'Z6',
      objective: {name: 'Качественная: VO2max', day: 'ПН', time: '18:45'},
      duration_min: 51,
      status: 'planned',
      actual_id: 'a-1',
      steps: [
        {
          id: 's-warm', role: 'warmup', sport: 'run', target_type: 'time',
          target_value: 15, focus: 'none', focus_value: {zone: 'Z1'},
          duration_min: 15, group: null, round: null, label: null, notes: null,
        },
        {
          id: 's-w1', role: 'work', sport: 'run', target_type: 'distance',
          target_value: 800, focus: 'hr',
          focus_value: {set_reps: 3, zone: 'Z5', hr_target: 164, pace_min_per_km: '4:15'},
          duration_min: 4, group: '3×800м с прогрессией 4:15 → 3:50', round: 1,
          label: null, notes: null,
        },
        {
          id: 's-r1', role: 'rest', sport: 'run', target_type: 'distance',
          target_value: 250, focus: 'hr',
          focus_value: {set_reps: 3, zone: 'Z1', hr_target: 115},
          duration_min: 2, group: '3×800м с прогрессией 4:15 → 3:50', round: 1,
          label: null, notes: null,
        },
        {
          id: 's-w2', role: 'work', sport: 'run', target_type: 'distance',
          target_value: 200, focus: 'hr',
          focus_value: {set_reps: 4, zone: 'Z6', hr_target: 172, pace_min_per_km: '3:45'},
          duration_min: 2, group: '4×200м', round: 1, label: null, notes: null,
        },
      ],
    },
    {
      id: 'w-2',
      request_id: 'r2',
      sport: 'ofp',
      kind: 'ofp',
      focus: 'core',
      objective: {name: 'Core 25мин', day: 'ПН', time: '06:30'},
      duration_min: 25,
      status: 'planned',
      actual_id: null,
      steps: [
        {
          id: 's-c1', role: 'work', sport: 'ofp', target_type: 'reps',
          target_value: 3, focus: 'none', focus_value: {reps: '3×45с'},
          duration_min: 5, group: 'Core circuit', round: null,
          label: 'Планка', notes: 'держать кор',
        },
      ],
    },
  ],
  summary: null,
  progress: {
    hours: {planned: 6.24, actual: 6.07},
    sessions: {planned: 7, actual: 7},
    distance_m: {planned: 35000, actual: 47868},
  },
};

const ACTUAL = [
  {
    id: 'a-1', date: '2026-10-26', sport: 'run', duration_min: 63,
    distance_m: 10300, hr_avg: 133, linked_workout_id: 'w-1',
  },
];

const SNAPSHOT = {
  season: {
    id: 'S1',
    horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
    slots: 9, equipment: 3, plans: [],
  },
  athlete: {
    vdot: 51,
    hr_zones: {Z1: {low: 100, high: 118}, Z2: {low: 118, high: 135}},
    hr_max: 182, rhr: 54, lth: 164, weight_kg: 101.7, injuries: [], form: '—',
  },
};

/* ------------------------------------------------------------------ окружение */

function setupDom() {
  const dom = new JSDOM(`<!doctype html><html><body>
    <header class="appbar" id="appbar"></header>
    <main class="app" id="picker"></main>
    <main class="app hidden" id="cardWrap"><div id="cardHost"></div></main>
    <nav class="bottomnav" id="nav"></nav>
  </body></html>`, {url: 'http://localhost:8080/', pretendToBeVisual: true});

  // В Node `navigator` и `location` — свойства с геттером, обычным
  // присваиванием их не заменить: defineProperty.
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

/* Загрузка приложения с заглушками. Каждый вызов — новый экземпляр:
 * модуль с состоянием импортируется один раз, поэтому перезапускаем
 * процесс через уникальный параметр в URL импорта. */
async function loadApp(overrides = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 3,
    snapshot: SNAPSHOT,
    week: WEEK,
    actual: ACTUAL,
    weeks: [],
    details: {},
    onCommand: overrides.onCommand,
  };

  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  // приложение грузится асинхронно: ждём, пока отрисунется неделя
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
}

async function waitFor(predicate, timeout = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return false;
}

/* Клик по элементу — как настоящий. */
function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

/* Вернуться на экран недели: тесты идут по порядку, а состояние
 * приложения общее — после «Факта» плашек тренировок на экране нет. */
function openWeek() {
  click(document.querySelector('#nav [data-screen="week"]'));
}

/* ------------------------------------------------------------------ тесты */

before(async () => {
  await loadApp();
});

test('главный экран: плашки тренировок и прогресс недели', () => {
  const slots = document.querySelectorAll('.slot');
  assert.equal(slots.length, 2);
  assert.ok(document.querySelector('.progress'), 'нет блока прогресса');
  assert.match(document.querySelector('.progress').textContent, /из/);
});

test('все пять экранов открываются и не падают', () => {
  const screens = [...document.querySelectorAll('#nav [data-screen]')];
  assert.equal(screens.length, 5);
  for (const button of screens) {
    click(button);
    const id = button.dataset.screen;
    const picker = document.getElementById('picker');
    assert.ok(picker.innerHTML.length > 0, `экран ${id} пуст`);
    assert.ok(!picker.innerHTML.includes('undefined'), `экран ${id} содержит undefined`);
  }
});

test('навигация: экран меняется, заголовок соответствует', () => {
  const season = document.querySelector('#nav [data-screen="season"]');
  click(season);
  assert.match(document.getElementById('appbar').textContent, /Сезон/);
  const fact = document.querySelector('#nav [data-screen="fact"]');
  click(fact);
  assert.match(document.getElementById('appbar').textContent, /Факт/);
});

test('детали тренировки открываются по тапу на плашку', async () => {
  openWeek();
  click(document.querySelectorAll('.slot')[0]);
  await waitFor(() => !document.getElementById('cardWrap').classList.contains('hidden'));
  const card = document.getElementById('cardHost').textContent;
  assert.match(card, /Качественная/);
  assert.match(card, /Выполнено/);
});

test('из деталей можно вернуться назад', async () => {
  openWeek();
  click(document.querySelectorAll('.slot')[0]);
  await waitFor(() => document.getElementById('backBtn'));

  const back = document.getElementById('backBtn');
  assert.ok(back, 'нет кнопки «назад»');
  click(back);
  await waitFor(() => document.getElementById('cardWrap').classList.contains('hidden'));
  assert.ok(document.querySelectorAll('.slot').length > 0);
});

test('блок факта кликабелен: у Garmin-факта есть обработчик разбора', () => {
  openWeek();
  click(document.querySelectorAll('.slot')[0]);
  const block = document.querySelector('.actual-block');
  assert.ok(block, 'нет блока факта');
  assert.equal(block.dataset.detail, 'a-1', 'блок факта не привязан к разбору');
  // кнопка внутри — тоже
  assert.ok(document.querySelector('[data-detail="a-1"]'));
});

test('название сета не дублирует число повторов', () => {
  openWeek();
  click(document.querySelectorAll('.slot')[0]);
  const set = document.querySelector('.step-set');
  assert.ok(set, 'нет блока сета');
  const group = set.querySelector('.step-phase').textContent;
  const reps = set.querySelector('.step-reps');
  assert.match(group, /3×800/);
  assert.equal(reps, null, 'число повторов продублировано рядом с названием');
});

test('плашка «Состояние изменилось» не остаётся после конфликта версий', async () => {
  // Команда отвечает конфликтом версий один раз, потом проходит.
  let calls = 0;
  await loadApp({
    onCommand: (command) => {
      calls += 1;
      if (calls === 1) {
        const error = new Error('версия разошлась');
        error.code = 'version_conflict';
        return Promise.reject(error);
      }
      return Promise.resolve({version: 42, data: {status: 'applied'}});
    },
  });

  openWeek();
  click(document.querySelectorAll('.slot')[0]);
  await waitFor(() => document.querySelector('.actual-block'));

  const unlink = document.querySelector('[data-unlink]');
  click(unlink);
  await waitFor(() => !document.querySelector('.msg'), 3000);

  const message = document.querySelector('.msg');
  assert.equal(message, null, 'плашка про состояние осталась на экране');
});

test('структура: сет собирается из шагов с номерами повтора', () => {
  const steps = WEEK.workouts[0].steps.filter((step) => step.round !== null);
  assert.equal(setReps(steps), 3);
});

test('название сета: повторы распознаются', () => {
  assert.equal(nameHasReps('3×800м с прогрессией 4:15 → 3:50'), true);
  assert.equal(nameHasReps('4×200м'), true);
  assert.equal(nameHasReps('Core circuit'), false);
  assert.equal(nameHasReps(''), false);
  assert.equal(nameHasReps(null), false);
});

test('число повторов — из плана, а не из числа шагов', () => {
  const steps = [{focus_value: {set_reps: 3}}, {focus_value: {set_reps: 3}}];
  assert.equal(setReps(steps), 3);
  assert.equal(setReps([{focus_value: {}}, {focus_value: {}}]), 2);
  assert.equal(setReps([]), 0);
});

test('склонение числа повторов', () => {
  assert.equal(repsLabel(1), '1 повтор');
  assert.equal(repsLabel(3), '3 повтора');
  assert.equal(repsLabel(5), '5 повторов');
  assert.equal(repsLabel(11), '11 повторов');
  assert.equal(repsLabel(21), '21 повтор');
});

test('информационная плашка гаснет сама', async () => {
  await loadApp();
  openWeek();
  click(document.querySelectorAll('.slot')[1]);
  await waitFor(() => document.getElementById('backBtn'));

  // «Загрузить факт из Garmin» — информационное сообщение
  const pull = document.getElementById('pull');
  assert.ok(pull, 'нет кнопки загрузки факта');
  click(pull);
  await waitFor(() => document.querySelector('.msg'));

  const kind = document.querySelector('.msg').className;
  assert.ok(!kind.includes('error'), 'информационное сообщение помечено как ошибка');

  // через 4 секунды плашка исчезает сама
  await waitFor(() => !document.querySelector('.msg'), 6000);
  assert.equal(document.querySelector('.msg'), null, 'плашка не исчезла сама');
});

test('плашку можно закрыть тапом', async () => {
  await loadApp();
  openWeek();
  click(document.querySelectorAll('.slot')[1]);
  await waitFor(() => document.getElementById('backBtn'));

  click(document.getElementById('pull'));
  await waitFor(() => document.querySelector('.msg'));

  click(document.getElementById('msg'));
  assert.equal(document.querySelector('.msg'), null, 'тап по плашке не закрыл её');
});
