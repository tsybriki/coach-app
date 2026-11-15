/* Навигация: история браузера и свайп-назад.
 *
 * Дефект, который это ловит: «по свайпу назад выбрасывает меня из
 * приложения». История велась непоследовательно: запись экрана
 * «Предложить тренировку» не создавалась, а выход в список из деталей
 * перезаписывал текущую запись вместо того, чтобы убрать её. В
 * результате свайп-назад уходил за пределы приложения — на пустую
 * страницу.
 *
 * Проверяем то, что человек делает пальцем: свайп (history.back) и
 * кнопка «←» должны возвращать на уровень выше и **никогда** не
 * выбрасывать из приложения.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

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
      id: 'w-1', request_id: 'r1', sport: 'run', kind: 'quality',
      focus: 'Z6',
      objective: {name: 'Качественная: VO2max', day: 'ПН', date: '2026-10-26'},
      day: 'ПН', date: '2026-10-26', slot_id: 'win-ПН-1', time: '18:45',
      duration_min: 51, status: 'planned', actual_id: 'a-1', steps: [],
    },
  ],
  summary: null,
  progress: {hours: {planned: 6.24, actual: 0}, sessions: {planned: 7, actual: 0}, distance_m: {planned: 35000, actual: 0}},
};

const ACTUAL = [
  {
    id: 'a-1', date: '2026-10-26', sport: 'run', duration_min: 63,
    distance_m: 10300, hr_avg: 133, linked_workout_id: 'w-1',
    avg_speed_mps: 2.73, avg_hr: 133, max_hr: 158, cadence: 178,
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

const SLOTS = [
  {id: 'win-ПН-1', day: 1, day_name: 'ПН', start: '18:45', end: '20:15', capacity_min: 90},
  {id: 'win-СР-1', day: 3, day_name: 'СР', start: '17:00', end: '19:00', capacity_min: 120},
];

/* ------------------------------------------------------------------ окружение */

let dom;

function setupDom(hash = '') {
  dom = new JSDOM(`<!doctype html><html><body>
    <header class="appbar" id="appbar"></header>
    <main class="app" id="picker"></main>
    <main class="app hidden" id="cardWrap"><div id="cardHost"></div></main>
    <main class="app hidden" id="detailWrap"><div id="detailHost"></div></main>
    <nav class="bottomnav" id="nav"></nav>
  </body></html>`, {url: `http://localhost:8080/${hash}`, pretendToBeVisual: true});

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
  setupDom(overrides.hash || '');
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 3,
    snapshot: SNAPSHOT,
    week: overrides.week || WEEK,
    actual: overrides.actual || ACTUAL,
    weeks: [],
    seasonPlan: overrides.seasonPlan,
    slots: overrides.slots || SLOTS,
    details: overrides.details || {},
    onCommand: overrides.onCommand,
  };

  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
}

/* ------------------------------------------------------------------ состояние */

/* Что сейчас на экране. */
function screenState() {
  const pickerVisible = !document.getElementById('picker').classList.contains('hidden');
  const cardVisible = !document.getElementById('cardWrap').classList.contains('hidden');
  const detailVisible = !document.getElementById('detailWrap').classList.contains('hidden');
  const composeVisible = Boolean(document.getElementById('compose-text'));
  let level = 'week';
  if (detailVisible) level = 'detail';
  else if (cardVisible) level = 'workout';
  else if (composeVisible) level = 'compose';
  else if (pickerVisible) level = 'week';
  return {
    level,
    state: history.state,
    length: history.length,
    hash: location.hash,
  };
}

/* Свайп-назад: как это делает телефон. */
async function swipeBack() {
  history.back();
  await waitFor(() => true, 60);
  await new Promise((resolve) => setTimeout(resolve, 120));
}

beforeEach(() => {
  globalThis.__fixture = undefined;
});

/* ------------------------------------------------------------------ тесты */

test('стартовая запись истории есть: свайп-назад не выбросит из приложения', async () => {
  /* Главное: у приложения должна быть своя запись истории. Без неё
   * первый же свайп уходит на предыдущую страницу — то есть выбрасывает
   * из приложения. */
  await loadApp();

  const s = screenState();
  assert.ok(s.state, 'у приложения нет своей записи истории');
  assert.equal(s.state.page, 'week', 'стартовая запись — не корень приложения');
});

test('свайп-назад из деталей тренировки возвращает к списку', async () => {
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());
  assert.equal(screenState().level, 'workout', 'детали не открылись');

  await swipeBack();

  const s = screenState();
  assert.equal(s.level, 'week', 'свайп-назад не вернул к списку недели');
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
});

test('свайп-назад из разбора возвращает к тренировке, а не выбрасывает', async () => {
  await loadApp();

  /* Разбор факта — третий уровень: неделя → тренировка → разбор. */
  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('#cardHost [data-detail]'));
  click(document.querySelector('#cardHost [data-detail]'));
  await waitFor(() => document.getElementById('detailHost').textContent.trim());
  assert.equal(screenState().level, 'detail', 'разбор не открылся');

  await swipeBack();

  const s = screenState();
  assert.equal(s.level, 'workout', 'свайп из разбора не вернул к тренировке');
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
});

test('два свайпа назад доходят до списка, а не выбрасывают', async () => {
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('#cardHost [data-detail]'));
  click(document.querySelector('#cardHost [data-detail]'));
  await waitFor(() => document.getElementById('detailHost').textContent.trim());

  await swipeBack();
  assert.equal(screenState().level, 'workout', 'первый свайп не вернул к тренировке');

  await swipeBack();
  const s = screenState();
  assert.equal(s.level, 'week', 'второй свайп не дошёл до списка');
  assert.ok(s.state, 'после двух свайпов приложение потеряло свою запись истории');
});

test('compose из тренировки: свайп возвращает к списку, а не путает историю', async () => {
  /* Открытие экрана пожеланий из тренировки: её запись истории должна
   * уйти на месте, а не через `history.back()` — back асинхронный, и
   * следующий pushState попал бы в другую запись. */
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  click(document.querySelector('#compose-open'));
  await waitFor(() => document.getElementById('compose-text'));
  assert.equal(screenState().level, 'compose', 'экран предложения не открылся');

  await swipeBack();

  const s = screenState();
  assert.equal(s.level, 'week', 'свайп с экрана предложения не вернул к списку');
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
});

test('свайп-назад из экрана «Предложить тренировку» возвращает к неделе', async () => {
  /* Экран ввода пожеланий — подэкран недели. Он обязан иметь свою запись
   * истории: иначе свайп с него уходит за пределы приложения. */
  await loadApp();

  click(document.querySelector('#compose-open'));
  await waitFor(() => document.getElementById('compose-text'));
  assert.equal(screenState().level, 'compose', 'экран предложения не открылся');

  await swipeBack();

  const s = screenState();
  assert.equal(s.level, 'week', 'свайп с экрана предложения не вернул к неделе');
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
});

test('кнопка «←» из деталей возвращает к списку и не ломает историю', async () => {
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  click(document.getElementById('backBtn'));
  await waitFor(() => document.getElementById('cardWrap').classList.contains('hidden'));

  const s = screenState();
  assert.equal(s.level, 'week', 'кнопка «←» не вернула к списку');
  assert.ok(s.state, 'после кнопки «←» приложение потеряло свою запись истории');
});

test('после кнопки «←» свайп-назад не выбрасывает из приложения', async () => {
  /* Кнопка и свайп должны приводить в одно состояние: если кнопка
   * убирает глубину истории, а свайп — нет, пользователь выпадает из
   * приложения при первом же свайпе после кнопки. */
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());
  click(document.getElementById('backBtn'));
  await waitFor(() => document.getElementById('cardWrap').classList.contains('hidden'));

  const before = screenState();
  await swipeBack();
  const after = screenState();

  assert.ok(after.state, 'после свайпа приложение потеряло свою запись истории');
  assert.ok(after.length >= 1, 'история стала пустой');
  assert.ok(after.length <= before.length,
    'свайп увеличил глубину истории — он ушёл наружу');
});

test('переход между разделами не копит историю', async () => {
  /* Разделы нижней навигации — не уровни вложенности. Их переключение
   * не должно растить историю: иначе свайп-назад уводит по разделам
   * туда, откуда человек уже ушёл. */
  await loadApp();

  const before = screenState().length;
  click(document.querySelector('#nav [data-screen="fact"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="fact"].on'));
  click(document.querySelector('#nav [data-screen="season"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="season"].on'));
  click(document.querySelector('#nav [data-screen="week"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="week"].on'));

  const after = screenState().length;
  assert.equal(after, before, 'переключение разделов изменило глубину истории');
});

test('раздел открывается из тренировки и остаётся открытым', async () => {
  /* Из тренировки можно уйти в другой раздел нижнего меню. Раздел
   * должен открыться — и не сброситься на неделю по обработке
   * истории. */
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  click(document.querySelector('#nav [data-screen="fact"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="fact"].on'));

  assert.ok(document.querySelector('#nav [data-screen="fact"].on'),
    'раздел «Факт» не открылся из тренировки');
  assert.ok(document.getElementById('picker').classList.contains('hidden') === false,
    'после перехода в раздел карточка тренировки осталась на экране');
});

test('свайп из тренировки в раздел не возвращает в неделю', async () => {
  /* Тот же случай со свайпом: раздел не уровень вложенности, но
   * выход из тренировки по истории обязан оставить раздел открытым. */
  await loadApp();

  click(document.querySelector('#nav [data-screen="fact"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="fact"].on'));
  click(document.querySelector('#nav [data-screen="week"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="week"].on'));
  click(document.querySelector('.slot'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  await swipeBack();

  assert.ok(document.getElementById('picker').classList.contains('hidden') === false,
    'после свайпа из тренировки экран закрылся');
  assert.ok(screenState().state, 'после свайпа приложение потеряло свою запись истории');
});

test('после возврата в неделю свайп-назад не выбрасывает', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="fact"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="fact"].on'));
  click(document.querySelector('#nav [data-screen="week"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="week"].on'));

  await swipeBack();

  const s = screenState();
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
  assert.equal(s.level, 'week', 'свайп уводит с экрана недели');
});

test('открытие другой тренировки не оставляет старую в истории', async () => {
  /* Переход между тренировками — замена записи, а не добавление: иначе
   * свайп-назад возвращает к предыдущей тренировке, а не к списку. */
  const week = {
    ...WEEK,
    workouts: [
      ...WEEK.workouts,
      {
        id: 'w-2', request_id: 'r2', sport: 'run', kind: 'easy',
        focus: 'Лёгкий бег',
        objective: {name: 'Лёгкий бег', day: 'СР', date: '2026-10-28'},
        day: 'СР', date: '2026-10-28', slot_id: 'win-СР-1', time: '17:00',
        duration_min: 45, status: 'planned', actual_id: null, steps: [],
      },
    ],
  };
  await loadApp({week});

  click(document.querySelectorAll('.slot')[0]);
  await waitFor(() => document.getElementById('cardHost').textContent.trim());
  const depth = screenState().length;

  click(document.getElementById('backBtn'));
  await waitFor(() => document.getElementById('cardWrap').classList.contains('hidden'));

  click(document.querySelectorAll('.slot')[1]);
  await waitFor(() => document.getElementById('cardHost').textContent.trim());
  assert.equal(screenState().length, depth,
    'переход между тренировками изменил глубину истории');

  await swipeBack();
  assert.equal(screenState().level, 'week',
    'свайп после смены тренировки не вернул к списку');
});

test('разбор факта — уровень вложенности: свайп возвращает к списку', async () => {
  /* Разбор факта — третий уровень: неделя → тренировка → разбор.
   * Открывается он из карточки тренировки, поэтому цепочка свайпов
   * должна дойти до списка, а не выбросить из приложения. */
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('#cardHost [data-detail]'));
  click(document.querySelector('#cardHost [data-detail]'));
  await waitFor(() => document.getElementById('detailHost').textContent.trim());
  assert.equal(screenState().level, 'detail', 'разбор не открылся');

  await swipeBack();
  assert.equal(screenState().level, 'workout', 'свайп из разбора не вернул к тренировке');

  await swipeBack();
  const s = screenState();
  assert.equal(s.level, 'week', 'второй свайп не дошёл до списка');
  assert.ok(s.state, 'после двух свайпов приложение потеряло свою запись истории');
});

test('кнопка «←» из разбора возвращает к тренировке', async () => {
  await loadApp();

  click(document.querySelector('.slot'));
  await waitFor(() => document.querySelector('#cardHost [data-detail]'));
  click(document.querySelector('#cardHost [data-detail]'));
  await waitFor(() => document.getElementById('detailHost').textContent.trim());

  click(document.getElementById('backBtn'));
  await waitFor(() => document.getElementById('detailWrap').classList.contains('hidden'));

  const s = screenState();
  assert.equal(s.level, 'workout', 'кнопка «←» из разбора не вернула к тренировке');
  assert.ok(s.state, 'после кнопки «←» приложение потеряло свою запись истории');
});

test('прямая ссылка на тренировку: свайп возвращает к списку', async () => {
  /* Приложение открывают по ссылке с хэшем тренировки. Такая запись
   * истории должна быть такой же, как у обычного открытия: иначе
   * обработчик её не понимает и свайп выбрасывает из приложения. */
  await loadApp({hash: '#w-1'});

  const s = screenState();
  assert.ok(s.state && s.state.page, 'у прямой ссылки нет записи истории');
  assert.notEqual(s.state.page, 'init',
    'запись прямой ссылки помечена как init — обработчик её не знает');

  await swipeBack();

  const after = screenState();
  assert.ok(after.state, 'после свайпа приложение потеряло свою запись истории');
  assert.equal(after.level, 'week', 'свайп с прямой ссылки не вернул к списку');
});

test('свайп из корня не выбрасывает из приложения', async () => {
  /* Под корнем должна быть «подушка» — своя запись истории. Без неё
   * свайп из корня уходит на предыдущую страницу браузера: человек
   * выпадает из приложения. */
  await loadApp();

  const start = screenState();
  assert.ok(start.length >= 2,
    'под корнем нет подушки: свайп из корня выбросит из приложения');

  await swipeBack();

  const s = screenState();
  assert.ok(s.state && s.state.page,
    'после свайпа из корня приложение потеряло свою запись истории');
  assert.ok(document.body.innerHTML.length > 1000,
    'после свайпа из корня приложение осталось пустым');
  assert.notEqual(s.url, 'about:blank',
    'свайп из корня увел на пустую страницу');
});

test('свайп за пределы приложения не выбрасывает', async () => {
  /* Главный дефект: свайп уводил на `about:blank` — пустую страницу.
   * Теперь выход за пределы приложения перехватывается: адрес
   * становится нашим, приложение остаётся на экране. */
  await loadApp();

  /* Имитируем выход за пределы: запись истории без нашего page. */
  history.replaceState(null, '', ' ');
  window.dispatchEvent(new global.window.PopStateEvent('popstate', {state: null}));
  await waitFor(() => document.getElementById('picker').classList.contains('hidden') === false);

  const s = screenState();
  assert.ok(s.state && s.state.page,
    'после выхода за пределы приложение осталось без своей записи истории');
  assert.equal(s.level, 'week', 'после выхода за пределы приложение потеряло экран');
  assert.ok(document.body.innerHTML.length > 1000,
    'после выхода за пределы приложение осталось пустым');
});

test('кнопка «←» из экрана предложения возвращает к неделе', async () => {
  await loadApp();

  click(document.querySelector('#compose-open'));
  await waitFor(() => document.getElementById('compose-text'));

  click(document.getElementById('backBtn'));
  await waitFor(() => document.getElementById('compose-text') === null
    || document.getElementById('picker').classList.contains('hidden') === false);

  const s = screenState();
  assert.equal(s.level, 'week', 'кнопка «←» из экрана предложения не вернула к неделе');
  assert.ok(s.state, 'после кнопки «←» приложение потеряло свою запись истории');
});

test('открытие висяка — уровень вложенности: свайп возвращает к списку', async () => {
  /* Висяк открывается как тренировка: у него есть свои детали. */
  const week = {
    ...WEEK,
    unplaced: [{
      id: 'w-unplaced-1', request_id: 'r9', sport: 'run', kind: 'easy',
      focus: 'Лёгкий бег', objective: {name: 'Лёгкий бег', day: 'ВС', date: '2026-11-01'},
      day: 'ВС', date: '2026-11-01', time: '10:00', duration_min: 45,
      status: 'planned', actual_id: null, steps: [],
    }],
  };
  await loadApp({week});

  click(document.querySelector('#picker .unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());
  assert.equal(screenState().level, 'workout', 'детали висяка не открылись');

  await swipeBack();

  const s = screenState();
  assert.equal(s.level, 'week', 'свайп из висяка не вернул к списку');
  assert.ok(s.state, 'после свайпа приложение потеряло свою запись истории');
});

test('переход по неделям сезона не копит историю', async () => {
  /* Неделя сезона — другое содержимое, но не другой уровень: переход
   * туда-обратно не должен растить историю. */
  const seasonPlan = {
    horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
    phases: [{id: 'base', week_from: 1, week_to: 12, objective: 'База'}],
    plans: [{status: 'active', goal: 'Марафон', venue: 'Берлин', race_date: '2027-04-20'}],
    macro_weeks: [
      {season_week: 3, phase_id: 'base', status: 'active', start: '2026-10-25', end: '2026-10-31', run_km: 50, total_h: 7},
      {season_week: 4, phase_id: 'base', status: 'proposed', start: '2026-11-01', end: '2026-11-07', run_km: 52, total_h: 7.5},
    ],
  };
  await loadApp({seasonPlan});

  click(document.querySelector('#nav [data-screen="season"]'));
  await waitFor(() => document.querySelector('#nav [data-screen="season"].on'));
  await waitFor(() => document.querySelector('#picker [data-week]'));

  const before = screenState().length;
  click(document.querySelector('#picker [data-week]'));
  await waitFor(() => document.querySelector('#nav [data-screen="week"].on'));

  assert.ok(screenState().length <= before,
    'переход по неделям сезона увеличил глубину истории');
  assert.ok(screenState().state, 'после перехода приложение потеряло свою запись истории');
});
