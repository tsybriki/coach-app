/* Экран недели: саммари закреплено, тренировки скроллятся.
 *
 * Кирилл (26.11.2026): «Хочу видеть там два блока — саммари статус, как
 * сейчас, и тренировки. При этом тренировки — скроллящийся блок, отдельно
 * от саммари. Хочу, чтобы саммари всегда был виден, а тренировки
 * скроллились. При этом первое послание на страницу хочу чтобы скроллило в
 * текущую дату. Например — сегодня четверг и я хочу, чтобы тренировки
 * четверга сразу были в видимости».
 *
 * Что проверяется:
 *  - экран разделён на два блока: саммари и тренировки;
 *  - саммари — вне прокручиваемого списка (всегда видно);
 *  - тренировки — в отдельном блоке со своей прокруткой;
 *  - при открытии недели список прокручен к сегодняшнему дню;
 *  - без «сегодня» (другая неделя) — список с начала, без попытки
 *    прокрутить.
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

/* Неделя с тренировками по дням: воскресенье → суббота.
 *
 * Даты — как их отдаёт сервер: у каждой тренировки своя дата, день
 * недели приходит по-русски.
 */
const DAYS = [
  ['ВС', '2026-11-22'], ['ПН', '2026-11-23'], ['ВТ', '2026-11-24'],
  ['СР', '2026-11-25'], ['ЧТ', '2026-11-26'], ['ПТ', '2026-11-27'],
  ['СБ', '2026-11-28'],
];

function makeWorkout(index, day, date) {
  return {
    id: `w-${index}`,
    request_id: `r-${index}`,
    sport: 'run',
    kind: 'easy',
    focus: 'Z2',
    objective: {name: `Тренировка ${index}`, day, date, time: '09:00'},
    duration_min: 40,
    status: 'planned',
    steps: [],
  };
}

function makeWeek(extra = {}) {
  return {
    id: 'W7',
    season_week: 7,
    start: '2026-11-22',
    end: '2026-11-28',
    status: 'active',
    focus: 'Набираем 57 км за 8 тренировок · работа по плану',
    load_target: {hours: 8.4, sessions: 10, distance_m: 57000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: DAYS.map(([day, date], i) => makeWorkout(i + 1, day, date)),
    progress: {
      hours: {actual: 5.7, planned: 8.4},
      sessions: {actual: 7, planned: 10},
      distance_m: {actual: 42800, planned: 58000},
    },
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 49, hr_max: 182, lth: 164, hr_zones: {}},
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

/* Загрузка приложения.
 *
 * `today` — сегодняшняя дата. Клиент узнаёт её с сервера
 * (`/api/v1/current-week` → `today`).
 */
async function loadApp({week, today} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 7,
    currentWeek: 7,
    today,
    snapshot: SNAPSHOT,
    week: week || makeWeek(),
    actual: [],
    weeks: [],
    details: {},
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
  await waitFor(() => document.querySelector('.week-trainings') !== null);
}

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

function openWeek() {
  click(document.querySelector('#nav [data-screen="week"]'));
}

/* Прокрутка к сегодняшнему дону отложена на кадр после отрисовки:
 * на момент рендера стили ещё не применены. Тест ждёт этого кадра. */
async function openWeekAndSettle() {
  openWeek();
  await waitFor(() => true, 30);
  await new Promise((resolve) => setTimeout(resolve, 30));
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('экран недели: два блока — саммари и тренировки', async () => {
  await loadApp({today: '2026-11-26'});
  openWeek();

  const summary = document.querySelector('.week-summary');
  const trainings = document.querySelector('.week-trainings');
  assert.ok(summary, 'нет блока саммари');
  assert.ok(trainings, 'нет блока тренировок');
});

test('саммари — вне списка тренировок: оно всегда видно', async () => {
  await loadApp({today: '2026-11-26'});
  openWeek();

  const summary = document.querySelector('.week-summary');
  const trainings = document.querySelector('.week-trainings');

  /* Саммари не внутри прокручиваемого блока: прокрутка тренировок не
   * уносит саммари вверх. */
  assert.ok(!trainings.contains(summary),
    'саммари внутри блока тренировок — оно уедет при прокрутке');
  assert.ok(summary.contains(document.querySelector('.goal-head')),
    'в саммари нет карточки фокуса недели');
});

test('блок тренировок — отдельный прокручиваемый контейнер', async () => {
  await loadApp({today: '2026-11-26'});
  openWeek();

  const trainings = document.querySelector('.week-trainings');
  /* Прокрутка — свойства контейнера, а не окна: иначе прокручивалась бы
   * вся страница вместе с саммари, а оно должно стоять на месте. */
  assert.equal(trainings.className.includes('scrolls'), true,
    'у блока тренировок нет признака собственной прокрутки');
  assert.ok(trainings.querySelectorAll('.slot').length > 0,
    'в блоке тренировок нет тренировок');
});

test('при открытии недели список прокручен к сегодняшнему дню', async () => {
  await loadApp({today: '2026-11-26'});
  openWeek();

  const marked = document.querySelectorAll('.slot[data-today="true"]');
  assert.ok(marked.length > 0,
    'сегодняшние тренировки не помечены — не к чему прокручивать');
  assert.ok(marked[0].textContent.includes('ЧТ'),
    `сегодня помечена не четверг: ${marked[0].textContent.slice(0, 40)}`);
});

test('вчерашние и позавчерашние тренировки — не сегодняшние', async () => {
  await loadApp({today: '2026-11-26'});
  openWeek();

  const today = [...document.querySelectorAll('.slot')]
    .filter((s) => s.dataset.today === 'true')
    .map((s) => s.textContent);
  assert.equal(today.length, 1, `сегодняшних тренировок ${today.length}`);
  assert.ok(today[0].includes('ЧТ'), today[0].slice(0, 40));
});

test('на прошлой неделе сегодняшних тренировок нет — прокрутка не нужна', async () => {
  /* Неделя прошлая: ни одной тренировки с сегодняшней датой. Прокрутка
   * к «сегодня» тут была бы прокруткой в пустоту. */
  await loadApp({week: makeWeek({
    start: '2026-11-15',
    end: '2026-11-21',
    workouts: [
      makeWorkout(1, 'ВС', '2026-11-15'),
      makeWorkout(2, 'ПН', '2026-11-16'),
    ],
  }), today: '2026-11-26'});
  openWeek();

  const marked = document.querySelectorAll('.slot[data-today="true"]');
  assert.equal(marked.length, 0,
    'на прошлой неделе помечена тренировка, которой сегодня нет');
  assert.ok(document.querySelector('.week-trainings'),
    'нет блока тренировок');
});

test('на будущей неделе сегодняшних тренировок нет', async () => {
  await loadApp({week: makeWeek({
    start: '2026-11-29',
    end: '2026-12-05',
    workouts: [makeWorkout(1, 'ВС', '2026-11-29')],
  }), today: '2026-11-26'});
  openWeek();

  const marked = document.querySelectorAll('.slot[data-today="true"]');
  assert.equal(marked.length, 0,
    'на будущей неделе помечена тренировка, которой сегодня нет');
});

test('в саммари нет плашки «Сегодня · N тренировок»', async () => {
  /* Кирилл (26.11.2026): «Удали плашку сегодня 2 тренировки. Это
   * мусорная информация.»
   *
   * Плашка дублировала то, что видно и так: прокрутка к сегодняшнему
   * дню и рамка на сегодняшней карточке. Строка в саммари — лишняя.
   */
  await loadApp({today: '2026-11-26'});
  openWeek();

  const summary = document.querySelector('.week-summary');
  assert.ok(summary, 'нет блока саммари');
  assert.doesNotMatch(summary.textContent, /сегодня/i,
    'в саммари осталась плашка про сегодняшний день');
  assert.equal(document.querySelectorAll('.today-line').length, 0,
    'плашка «Сегодня · N тренировок» осталась на экране');
});

test('сегодняшняя тренировка помечена рамкой в списке', async () => {
  /* Рамка остаётся: она говорит, какая тренировка сегодняшняя, и
   * показывает, куда привела прокрутка. */
  await loadApp({today: '2026-11-26'});
  openWeek();

  const marked = document.querySelectorAll('.slot[data-today="true"]');
  assert.ok(marked.length > 0, 'сегодняшняя тренировка не помечена');
});

test('если тренировок нет — блок тренировок на месте и пуст', async () => {
  await loadApp({week: makeWeek({workouts: []}), today: '2026-11-26'});
  openWeek();

  const trainings = document.querySelector('.week-trainings');
  assert.ok(trainings, 'нет блока тренировок');
  assert.match(trainings.textContent, /нет/i,
    'пустой блок тренировок не объясняет, что их нет');
});

test('без даты «сегодня» экран работает — ничего не прокручивает зря', async () => {
  /* Сервер может не отдать дату (старая версия, кэш). Экран не должен
   * падать и не должен искать «сегодня» в пустоте. */
  await loadApp({today: undefined});
  openWeek();

  assert.ok(document.querySelector('.week-summary'), 'нет блока саммари');
  assert.ok(document.querySelector('.week-trainings'), 'нет блока тренировок');
  const marked = document.querySelectorAll('.slot[data-today="true"]');
  assert.equal(marked.length, 0, 'без даты помечено что-то сегодняшнее');
});

/* Прокрутка контейнера — перехват на прототипе.
 *
 * У элемента в jsdom нет `scrollTo` — есть только `scrollTop`, и он
 * определён на `Element.prototype`. Перехватываем на прототипе: при
 * рендере `picker.innerHTML` пересоздаёт элементы, и подмена на
 * конкретном узле потерялась бы.
 *
 * Смотрим и на `scrollTo`, и на `scrollTop`: в браузере клиент
 * использует `scrollTo`, в jsdom — запасной путь через `scrollTop`.
 */
function trackScroll() {
  const calls = [];
  const proto = globalThis.window.Element.prototype;
  const original = Object.getOwnPropertyDescriptor(proto, 'scrollTop');
  Object.defineProperty(proto, 'scrollTop', {
    configurable: true,
    get() {
      return original.get.call(this);
    },
    set(value) {
      calls.push({el: this, top: value});
      return original.set.call(this, value);
    },
  });
  const originalTo = globalThis.window.Element.prototype.scrollTo;
  if (typeof originalTo === 'function') {
    globalThis.window.Element.prototype.scrollTo = function(arg) {
      calls.push({el: this, top: arg && arg.top});
    };
  }
  return {
    calls,
    restore() {
      Object.defineProperty(proto, 'scrollTop', original);
      if (typeof originalTo === 'function') {
        globalThis.window.Element.prototype.scrollTo = originalTo;
      }
    },
  };
}

test('прокрутка к сегодняшнему дню вызывается на списке тренировок', async () => {
  /* Проверяем **факт прокрутки** и то, что она на списке тренировок.
   *
   * Итоговое смещение в jsdom бесполезно: раскладки нет,
   * `getBoundingClientRect` даёт нули. А вот то, что прокрутка была и
   * что она на списке, — говорит о главном: саммари не уедет.
   */
  await loadApp({today: '2026-11-26'});
  /* Перехват — после загрузки: `setupDom` создаёт новый jsdom, и
   * прототип из прошлого окна — не тот. */
  const tracker = trackScroll();
  try {
    await openWeekAndSettle();

    const list = [...document.querySelectorAll('.week-trainings')];
    const onList = tracker.calls.filter((c) => list.includes(c.el));
    assert.ok(onList.length > 0,
      'прокрутка к сегодняшнему дню не вызвана на списке тренировок');
    assert.ok(onList[0].top >= 0, `смещение отрицательное: ${onList[0].top}`);
  } finally {
    tracker.restore();
  }
});

test('прокрутка идёт по списку тренировок, а не по странице', async () => {
  /* Прокрутка страницы унесла бы саммари наверх — а оно должно стоять
   * на месте. Значит прокручивается **список**. */
  await loadApp({today: '2026-11-26'});
  const tracker = trackScroll();
  try {
    await openWeekAndSettle();

    const list = [...document.querySelectorAll('.week-trainings')];
    const onList = tracker.calls.filter((c) => list.includes(c.el));
    const onOther = tracker.calls.filter((c) => !list.includes(c.el));

    assert.ok(onList.length > 0, 'список тренировок не прокручен');
    /* Прокрутка чего-то ещё — значит, прокрутилась не та часть
     * экрана. Страница прокручивается в ноль при смене раздела, и это
     * допустимо; вот прокрутка вниз — нет: саммари уехало бы. */
    const scrolledAway = onOther.filter((c) => c.top > 0);
    assert.equal(scrolledAway.length, 0,
      `прокручено что-то кроме списка: ${scrolledAway.map((c) => c.top)}`);
  } finally {
    tracker.restore();
  }
});

test('смещение прокрутки считается по прямоугольникам, а не по offsetTop', async () => {
  /* Лов��т известный дефект: `offsetTop` у карточки тренировки
  * считается от её `offsetParent` — то есть от самой карточки, а не от
  * прокручиваемого списка. Он всегда 0, и прокрутка уходит не туда.
  *
  * В jsdom раскладки нет, поэтому прямоугольники подставляются
  * вручную: список на 300 px ниже, сегодняшняя тренировка — на 800 px
  * внутри него. Ожидаемое смещение — 500.
  */
  await loadApp({today: '2026-11-26'});
  openWeek();

  /* Прямоугольники подменяются на прототипе: при рендере элементы
   * пересоздаются, и подмена на конкретном узле потерялась бы. */
  const proto = globalThis.window.Element.prototype;
  const originalRect = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function() {
    if (this.classList && this.classList.contains('week-trainings')) {
      return {top: 300, bottom: 752, left: 0, right: 366, width: 366,
        height: 452};
    }
    if (this.dataset && this.dataset.today === 'true') {
      return {top: 800, bottom: 880, left: 12, right: 354, width: 342,
        height: 80};
    }
    return originalRect.call(this);
  };

  const calls = [];
  const original = Object.getOwnPropertyDescriptor(proto, 'scrollTop');
  Object.defineProperty(proto, 'scrollTop', {
    configurable: true,
    get() {
      return original.get.call(this);
    },
    set(value) {
      if (this.classList && this.classList.contains('week-trainings')) {
        calls.push(value);
      }
      return original.set.call(this, value);
    },
  });

  try {
    /* Прокрутка вызывается отложенно — ждём кадра.
     *
     * Раздел меняем на «Сезон» и обратно: экран недели перерисовывается
     * только при смене раздела, клик по активному разделу ничего не
     * делает. */
    click(document.querySelector('#nav [data-screen="season"]'));
    click(document.querySelector('#nav [data-screen="week"]'));
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.ok(calls.length > 0, 'прокрутка не вызвана');
    /* 800 − 300 − 8 = 492. С offsetTop было бы 0 — прокрутки бы не
     * было вовсе. */
    assert.ok(calls[0] > 400,
      `смещение ${calls[0]} — похоже на offsetTop вместо прямоугольников`);
  } finally {
    Object.defineProperty(proto, 'scrollTop', original);
    proto.getBoundingClientRect = originalRect;
  }
});
