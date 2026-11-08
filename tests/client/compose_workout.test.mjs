/* «Предложить тренировку»: ввод текста, разбор, добавление в неделю.
 *
 * И удаление тренировки — доступное только пока неделя не активна.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и обработчиками
 * клика. Вместо сети и IndexedDB подставляются заглушки (см. helpers/).
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

function makeWorkout(extra = {}) {
  return {
    id: 'w1',
    request_id: 'r1',
    sport: 'run',
    kind: 'easy',
    focus: 'Лёгкий бег',
    objective: {name: 'Лёгкий бег', day: 'ВС', date: '2026-11-08'},
    time: '11:00',
    duration_min: 55,
    distance_m: 7600,
    status: 'planned',
    actual_id: null,
    steps: [],
    ...extra,
  };
}

function makeWeek(status = 'proposed', extra = {}) {
  return {
    id: 'W5',
    season_week: 5,
    start: '2026-11-08',
    end: '2026-11-14',
    status,
    focus: 'Набираем 57 км',
    load_target: {hours: 7.7, sessions: 9, distance_m: 57000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: [makeWorkout()],
    can_activate: true,
    activate_blocked_by: null,
    compose_available: true,
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 51, hr_max: 182, lth: 164, hr_zones: {}},
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

async function loadApp({week, onCommand, onCompose, composeResult} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 5,
    currentWeek: 5,
    snapshot: SNAPSHOT,
    // null — недели нет в хранилище: экран «ещё не спланирована».
    week: week === null ? null : (week || makeWeek()),
    actual: [],
    weeks: [],
    details: {},
    seasonPlan: {
      id: 'S1',
      horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
      plans: [], phases: [],
      macro_weeks: [
        {season_week: 5, phase_id: 'p', focus: 'base', goal_text: 'База',
         run_km: 57, total_h: 7.7, sessions_target: 9, deload: false,
         status: 'proposed', has_fact: false,
         start: '2026-11-08', end: '2026-11-14'},
        {season_week: 6, phase_id: 'p', focus: 'base', goal_text: 'База',
         run_km: 57, total_h: 7.6, sessions_target: 9, deload: false,
         status: null, has_fact: false,
         start: '2026-11-15', end: '2026-11-21'},
      ],
    },
    onCommand,
    onCompose,
    composeResult,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.getElementById('nav').children.length > 0);
}

function sentCommands() {
  return globalThis.__fixture.sent || [];
}

beforeEach(() => {
  globalThis.__fixture = undefined;
});

/* ------------------------------------------------------------------ тесты */

test('у неактивной недели есть кнопка «Предложить тренировку»', async () => {
  await loadApp();

  assert.ok(document.querySelector('#compose-open'),
    'нет кнопки предложения тренировки');
});

test('в активной неделе кнопки предложения нет', async () => {
  await loadApp({week: makeWeek('active')});

  assert.ok(!document.querySelector('#compose-open'),
    'в активной неделе кнопка предложения не нужна');
});

test('если разбор недоступен, кнопки нет', async () => {
  await loadApp({week: makeWeek('proposed', {compose_available: false})});

  assert.ok(!document.querySelector('#compose-open'),
    'без ключа модели кнопку показывать нельзя');
});

test('в ещё не спланированной неделе кнопка тоже есть', async () => {
  // Недели нет в хранилище: экран «Неделя ещё не спланирована».
  await loadApp({week: null});

  assert.match(document.getElementById('picker').textContent,
    /ещё не спланирована/);
  assert.ok(document.querySelector('#compose-open'),
    'в неспланированной неделе предложить тренировку тоже можно');
});

test('кнопка открывает поле ввода текста', async () => {
  await loadApp();

  click(document.querySelector('#compose-open'));

  assert.ok(document.querySelector('#compose-text'),
    'нет поля ввода пожеланий');
  assert.ok(document.querySelector('#compose-run'),
    'нет кнопки «Разобрать»');
});

test('пример пожелания подставляется в поле', async () => {
  await loadApp();

  click(document.querySelector('#compose-open'));
  click(document.querySelector('[data-compose-example]'));

  const field = document.querySelector('#compose-text');
  assert.ok(field.value.length > 0, 'пример не подставился в поле');
});

test('разбор показывает структуру шагов и «что я додумал»', async () => {
  await loadApp();

  click(document.querySelector('#compose-open'));
  document.querySelector('#compose-text').value = '12 км, фартлек';
  click(document.querySelector('#compose-run'));
  await waitFor(() => document.querySelector('#compose-add'));

  const text = document.getElementById('picker').textContent.replace(/\s+/g, ' ');
  assert.match(text, /Фартлек/, 'нет названия тренировки');
  assert.match(text, /3,0 км/, 'нет объёма разминки');
  assert.match(text, /Z5/, 'нет зоны пульса');
  assert.match(text, /4:11\/км/, 'нет темпа');
  assert.match(text, /Что я додумал/, 'не показано, что модель додумала');
  assert.match(text, /12,0 км/, 'нет итогового километража');
});

test('добавление в неделю шлёт команду с намерениями', async () => {
  const sent = [];
  await loadApp({
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#compose-open'));
  document.querySelector('#compose-text').value = '12 км, фартлек';
  click(document.querySelector('#compose-run'));
  await waitFor(() => document.querySelector('#compose-add'));
  click(document.querySelector('#compose-add'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'add_composed_workout');
  assert.equal(sent[0].args.season_week, 5);
  assert.equal(sent[0].args.name, 'Фартлек');
  assert.ok(sent[0].args.intents.length >= 2, 'намерения не переданы');
  assert.ok(sent[0].reason, 'у команды нет причины');
});

test('после добавления возвращаемся к неделе', async () => {
  await loadApp({
    onCommand: () => Promise.resolve({version: 43, data: {status: 'applied'}}),
  });

  click(document.querySelector('#compose-open'));
  document.querySelector('#compose-text').value = '12 км, фартлек';
  click(document.querySelector('#compose-run'));
  await waitFor(() => document.querySelector('#compose-add'));
  click(document.querySelector('#compose-add'));
  await waitFor(() => document.querySelector('#compose-open'));

  assert.ok(document.querySelector('#compose-open'),
    'не вернулись к неделе после добавления');
});

test('пустой текст — понятная ошибка, без запроса к модели', async () => {
  let called = false;
  await loadApp({
    onCompose: () => {
      called = true;
      return Promise.resolve({data: {}});
    },
  });

  click(document.querySelector('#compose-open'));
  document.querySelector('#compose-text').value = '   ';
  click(document.querySelector('#compose-run'));
  await waitFor(() => document.querySelector('#compose-error'));

  assert.ok(!called, 'модель не должна вызываться с пустым текстом');
  assert.match(document.getElementById('picker').textContent,
    /Опиши тренировку/);
});

test('ошибка разбора показывается пользователю', async () => {
  await loadApp({
    onCompose: () => Promise.reject(new Error('модель недоступна')),
  });

  click(document.querySelector('#compose-open'));
  document.querySelector('#compose-text').value = '12 км';
  click(document.querySelector('#compose-run'));
  await waitFor(() => document.querySelector('#compose-error'));

  assert.match(document.getElementById('picker').textContent,
    /модель недоступна/);
});

/* ------------------------------------------------------------------ удаление */

test('у неактивной недели тренировку можно удалить', async () => {
  const sent = [];
  await loadApp({
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('[data-remove-workout]'));

  const remove = document.querySelector('[data-remove-workout]');
  assert.ok(remove, 'нет кнопки удаления в карточке тренировки');
  click(remove);
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'remove_workout');
  assert.equal(sent[0].args.workout_id, 'w1');
  assert.equal(sent[0].args.season_week, 5);
});

test('в активной неделе кнопки удаления нет', async () => {
  await loadApp({week: makeWeek('active')});

  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('#cardHost .name'));

  assert.ok(!document.querySelector('[data-remove-workout]'),
    'в активной неделе удалять нельзя');
});

/* У висяка id — это id запроса, а у тренировки свой. Удалять надо
 * тренировку: по id запроса сервер её не найдёт. */
test('у непривязанной тренировки удаляется именно тренировка', async () => {
  const sent = [];
  await loadApp({
    week: makeWeek('proposed', {
      workouts: [],
      unplaced: [{
        id: 'r-composed-1', workout_id: 'w-composed-1', request_id: 'r-composed-1',
        sport: 'run', kind: 'composed', focus: 'Фартлек',
        duration_min: 54, distance_m: 12000, name: 'Фартлек',
        objective: {}, steps: [],
      }],
    }),
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.querySelector('[data-remove-workout]'));

  click(document.querySelector('[data-remove-workout]'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'remove_workout');
  assert.equal(sent[0].args.workout_id, 'w-composed-1',
    'удалять надо тренировку, а не запрос');
});
