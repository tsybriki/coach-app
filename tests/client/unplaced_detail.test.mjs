/* Экран деталей непривязанной тренировки.
 *
 * Дефект, который это ловит: висяк был строкой «Лёгкий бег, 46 мин»
 * без деталей. Тап по нему открывал выбор окна, а посмотреть, что
 * внутри тренировки, было нельзя — и куда её поставить, решаешь вслепую.
 *
 * Теперь: тап по висяку — экран деталей, как у размещённой тренировки;
 * кнопка «привязать» — отдельное действие с прежним поведением.
 */
import {test, before, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

const WEEK = {
  id: 'W4',
  season_week: 4,
  start: '2026-11-01',
  end: '2026-11-07',
  status: 'proposed',
  focus: 'Набираем 56 км за 9 тренировок · работа по плану',
  load_target: {hours: 7.7, sessions: 9, distance_m: 56000},
  requests: [
    {id: 'r4-6', sport: 'run', kind: 'easy', focus: 'Лёгкий бег', duration_min: 46},
  ],
  assignments: [],
  /* Висяк приходит с деталями: название, объект, шаги. */
  unplaced: [
    {
      id: 'r4-6',
      /* У висяка два id: запроса (r4-…) и тренировки (w-composed-1).
       * Удалять надо тренировку. */
      workout_id: 'w-composed-1',
      request_id: 'r4-6',
      sport: 'run',
      kind: 'easy',
      focus: 'Лёгкий бег + отрезки',
      name: 'Лёгкий бег + отрезки',
      duration_min: 46,
      objective: {name: 'Лёгкий бег + отрезки'},
      rationale: 'Лёгкий бег + отрезки',
      steps: [
        {
          id: 'run-easy',
          role: 'work',
          sport: 'run',
          target_type: 'distance',
          target_value: 7348,
          focus: 'hr',
          focus_value: {zone: 'Z2', pace_min_per_km: '5:30'},
          duration_min: 40.41,
        },
        {
          id: 'run-stride-1',
          role: 'work',
          sport: 'run',
          target_type: 'distance',
          target_value: 100,
          focus: 'hr',
          focus_value: {zone: 'Z2', pace_min_per_km: '3:35', set_reps: 6,
                        daniels_zone: 'R'},
          duration_min: 0.36,
          group: '6×100м через 100м',
          round: 1,
        },
      ],
    },
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
      duration_min: 77,
      status: 'planned',
      actual_id: null,
      steps: [],
    },
  ],
};

const SLOTS = [
  {id: 'win-ВС-1', day: 0, day_name: 'ВС', start: '11:00', end: '13:00',
   capacity_min: 120, forbidden_sports: []},
  {id: 'win-СР-1', day: 3, day_name: 'СР', start: '17:00', end: '19:00',
   capacity_min: 120, forbidden_sports: ['bike']},
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

const commands = [];

async function loadApp() {
  setupDom();
  commands.length = 0;
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    snapshot: {version: 42, seasonWeek: 4},
    week: WEEK,
    actual: [],
    weeks: [],
    slots: SLOTS,
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

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

before(async () => {
  await loadApp();
});

beforeEach(async () => {
  /* Возврат к списку недели: тесты меняют экран. */
  const back = document.getElementById('backBtn');
  if (back) click(back);
  await waitFor(() => document.querySelectorAll('.unplaced-row').length > 0);
  commands.length = 0;
});

test('тап по висяку открывает экран деталей', async () => {
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /Лёгкий бег \+ отрезки/, `детали висяка: ${text}`);
  assert.match(text, /Структура тренировки/, 'нет структуры');
});

test('детали висяка показывают его шаги', async () => {
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /7\.3 км/, `шаг с дистанцией: ${text}`);
  assert.match(text, /5:30/, `темп шага: ${text}`);
  assert.match(text, /6×100м через 100м/, `сет отрезков: ${text}`);
});

test('детали висяка помечены как непривязанные', async () => {
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const text = document.getElementById('cardHost').textContent;
  assert.match(text, /не привязана/i, `нет пометки: ${text}`);
});

test('на экране деталей висяка кнопки привязки нет', async () => {
  /* Кнопка привязки — на карточке тренировки в списке недели, а не
   * внутри деталей: до неё не надо заходить внутрь тренировки. */
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  assert.ok(!document.querySelector('#cardHost [data-bind-pick]'),
    'в деталях висяка осталась кнопка привязки');
});

test('кнопки деталей — иконки в шапке: корзина и привязка', async () => {
  /* Кирилл: «кнопки деталей — иконки в шапке: корзина и привязка».
   * Позже уточнил: обе кнопки — на карточке тренировки на странице
   * недели. Поэтому в деталях их больше нет. */
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const header = document.querySelector('#cardHost .card-header');
  assert.ok(header, 'нет шапки карточки');

  assert.ok(!header.querySelector('[data-remove-workout]'),
    'удаление осталось внутри деталей тренировки');
  assert.ok(!header.querySelector('[data-bind-pick]'),
    'привязка осталась внутри деталей тренировки');

  /* Отдельной карточки «Удалить тренировку» больше нет. */
  const cardText = document.getElementById('cardHost').textContent;
  assert.doesNotMatch(cardText, /Удалить тренировку/,
    'старая карточка удаления осталась');
});

test('у висяка в списке недели есть иконки корзины и скрепки', async () => {
  /* Висяк — тоже тренировка: действия живут на её карточке в списке
   * недели, а не внутри деталей. */
  const card = document.querySelector('#picker .unplaced-row');
  assert.ok(card, 'нет строки висяка');

  const remove = card.querySelector('[data-remove-workout]');
  assert.ok(remove, 'у висяка нет кнопки удаления');
  assert.match(remove.textContent, /🗑/, 'удаление — не иконка корзины');
  assert.equal(remove.getAttribute('aria-label'), 'Удалить тренировку');

  const bind = card.querySelector('[data-bind-pick]');
  assert.ok(bind, 'у висяка нет кнопки привязки');
  assert.match(bind.textContent, /🔗/, 'привязка — не иконка');
  assert.equal(bind.getAttribute('aria-label'), 'Привязать к окну');
});

test('кнопка удаления у висяка шлёт remove_workout', async () => {
  click(document.querySelector('#picker .unplaced-row [data-remove-workout]'));
  await waitFor(() => commands.some((c) => c.type === 'remove_workout'));

  const command = commands.find((c) => c.type === 'remove_workout');
  assert.ok(command, 'команда удаления не отправлена');
  /* У висяка id запроса (r4-6), а удалять надо тренировку (w-composed-1). */
  assert.equal(command.args.workout_id, 'w-composed-1');
});

test('выбор окна открывается сразу под строкой висяка', async () => {
  /* Кирилл: «карточка с доступными слотами должна открываться сразу под
   * тренировкой, а не внизу экрана». Выбор окон — ответ на нажатую
   * скрепку, и он открывается под строкой тренировки. */
  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  const row = document.querySelector('#picker .unplaced-row');
  const picker = document.querySelector('#picker .slot-picker');
  assert.ok(picker, 'выбор окна не открылся');

  /* Выбор окон — внутри обёртки строки, то есть сразу под ней. */
  const wrap = row.closest('.unplaced-row-wrap');
  assert.ok(wrap, 'нет обёртки строки висяка');
  assert.ok(wrap.querySelector('.slot-picker'),
    'выбор окон не под строкой висяка');
  assert.ok(row.compareDocumentPosition(picker) & Node.DOCUMENT_POSITION_FOLLOWING,
    'выбор окон не после строки');

  /* И не в самом низу списка: он внутри обёртки этой строки. */
  assert.equal(picker.closest('.unplaced-row-wrap'), wrap);
});

test('кнопка привязки открывает выбор окна', async () => {
  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  const choices = document.querySelectorAll('#picker .slot-choice');
  assert.equal(choices.length, SLOTS.length, 'выбор окна не открылся');
});

test('выбор окна в списке недели шлёт place_unplaced', async () => {
  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  click(document.querySelector('#picker .slot-choice[data-bind-slot="win-СР-1"]'));
  await waitFor(() => commands.some((c) => c.type === 'place_unplaced'));

  const command = commands.find((c) => c.type === 'place_unplaced');
  assert.ok(command, 'команда не отправлена');
  assert.equal(command.args.request_id, 'r4-6');
  assert.equal(command.args.slot_id, 'win-СР-1');
});

test('кнопка «привязать» в списке висяков работает как раньше', async () => {
  /* Поведение кнопки «привязать» в списке прежнее: открывает выбор
   * окна. */
  click(document.querySelector('#picker .unplaced-row [data-bind-pick]'));
  await waitFor(() => document.querySelectorAll('#picker .slot-choice').length > 0);

  const choices = document.querySelectorAll('#picker .slot-choice');
  assert.equal(choices.length, SLOTS.length, 'выбор окна не открылся');
  assert.ok(document.querySelector('#picker').textContent.includes('Куда привязать'),
    'выбор окна не на экране недели');
});

test('из экрана деталей можно вернуться к неделе', async () => {
  click(document.querySelector('.unplaced-open'));
  await waitFor(() => document.getElementById('cardHost').textContent.trim());

  const back = document.getElementById('backBtn');
  assert.ok(back, 'нет кнопки «назад»');
  click(back);
  /* Ждём именно закрытия экрана деталей: список недели и при этом
   * остаётся в DOM, так что по нему ждать бессмысленно. */
  await waitFor(() => document.getElementById('cardWrap')
    .classList.contains('hidden'));

  assert.ok(document.querySelectorAll('.unplaced-row').length > 0,
    'после возврата список висяков не на месте');
});
