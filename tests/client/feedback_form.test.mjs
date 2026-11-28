/* Форма субъективной оценки тренировки на клиенте.
 *
 * ТЗ (Кирилл, 26.11.2026): оценка снимается в момент привязки факта к
 * плановой тренировке. Форма зависит от вида работы: лёгкая и длинная
 * спрашивают общее ощущение, интервальная и пороговая — динамику.
 * Всё выбирается в одно нажатие, у состояния тела выбран «Фон».
 *
 * Что проверяется:
 *  - привязка беговой тренировки открывает форму (а не привязывает молча);
 *  - у лёгкой работы — поля «ощущения», у качественной — динамики;
 *  - у не-беговой работы формы нет;
 *  - выбранный чип отмечен, повторное нажатие снимает выбор;
 *  - «Фон» выбран заранее;
 *  - сохранение уходит командой `set_feedback`, привязка — `link_actual`
 *    с оценкой внутри;
 *  - пропуск формы сохраняет пустую оценку;
 *  - оценку привязанной тренировки можно открыть и отредактировать;
 *  - маркеры оценки видны в плашке тренировки недели.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

function makeWorkout(extra = {}) {
  return Object.assign({
    id: 'w-1',
    request_id: 'r-1',
    sport: 'run',
    kind: 'easy',
    focus: 'Z2',
    objective: {name: 'Лёгкий бег', day: 'ВС', date: '2026-11-22', time: '09:00'},
    duration_min: 40,
    status: 'planned',
    actual_id: null,
    steps: [],
    feedback: {},
    feedback_kind: 'easy',
  }, extra);
}

function makeWeek(workouts) {
  return {
    id: 'W7',
    season_week: 7,
    start: '2026-11-22',
    end: '2026-11-28',
    status: 'active',
    focus: 'Набираем 57 км за 8 тренировок',
    load_target: {hours: 8.4, sessions: 10, distance_m: 57000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: workouts || [makeWorkout()],
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 49, hr_max: 182, lth: 164, hr_zones: {}},
};

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
 * `onCommand` — перехватчик команд: он видит, что клиент отправляет.
 */
async function loadApp({week, actual = [], onCommand} = {}) {
  setupDom();
  const commands = [];
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 7,
    currentWeek: 7,
    today: '2026-11-26',
    snapshot: SNAPSHOT,
    week: week || makeWeek(),
    actual,
    weeks: [],
    details: {},
    onCommand: onCommand || ((command) => {
      commands.push(command);
      return Promise.resolve({version: 42, data: {status: 'applied'}});
    }),
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.querySelectorAll('.slot').length > 0);
  return commands;
}

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

function openWeek() {
  click(document.querySelector('#nav [data-screen="week"]'));
}

/* Открыть детали тренировки. */
function openWorkout(workoutId) {
  click(document.querySelector(`.slot[data-slot="${workoutId}"]`));
}

/* Чип по подписи. */
function chip(label) {
  return [...document.querySelectorAll('.chip')]
    .find((element) => element.textContent.trim() === label);
}

/* ------------------------------------------------------------------ тесты */

test('привязка беговой тренировки открывает форму оценки', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  const commands = await loadApp({actual});
  openWeek();
  openWorkout('w-1');

  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  assert.ok(document.querySelector('#fb-save'), 'форма оценки не открылась');
  assert.ok(document.querySelector('#fb-skip'), 'нет кнопки пропуска');
  assert.equal(commands.length, 0,
    'привязка ушла раньше, чем оценка собрана');
});

test('у лёгкой работы — поле ощущения, без полей динамики', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  const labels = [...document.querySelectorAll('.fb-label')]
    .map((element) => element.textContent.trim());
  assert.ok(labels.some((l) => l.includes('Тело')), 'нет поля состояния тела');
  assert.ok(labels.some((l) => l.includes('ощущение')), 'нет поля ощущения');
  assert.ok(!labels.some((l) => l.includes('отрезок')), 'есть поле динамики');
});

test('у качественной работы — три поля динамики', async () => {
  const workout = makeWorkout({
    id: 'w-q', kind: 't', feedback_kind: 'quality',
    objective: {name: 'Работа в пороговом темпе', day: 'ЧТ',
                date: '2026-11-26', time: '10:30'},
  });
  const actual = [{
    id: 'a1', date: '2026-11-26', sport: 'run', duration_min: 62,
    distance_m: 12900, linked_workout_id: null,
  }];
  await loadApp({week: makeWeek([workout]), actual});
  openWeek();
  openWorkout('w-q');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  const labels = [...document.querySelectorAll('.fb-label')]
    .map((element) => element.textContent.trim());
  assert.ok(labels.some((l) => l.includes('Тело')), 'нет поля состояния тела');
  assert.ok(labels.some((l) => l.includes('1-й отрезок')), 'нет 1-го отрезка');
  assert.ok(labels.some((l) => l.includes('2-й отрезок')), 'нет 2-го отрезка');
  assert.ok(labels.some((l) => l.includes('ещё 1')), 'нет поля финиша');
  assert.ok(!labels.some((l) => l.includes('ощущение')),
    'у качественной работы не должно быть поля ощущения');
});

test('у не-беговой работы формы нет — привязка идёт сразу', async () => {
  const workout = makeWorkout({
    id: 'w-bike', sport: 'bike', kind: 'bike', feedback_kind: 'other',
    objective: {name: 'Велосипед', day: 'ВС', date: '2026-11-22', time: '12:00'},
  });
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'bike', duration_min: 60,
    distance_m: 25000, linked_workout_id: null,
  }];
  const commands = await loadApp({week: makeWeek([workout]), actual});
  openWeek();
  openWorkout('w-bike');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => commands.length > 0);

  assert.equal(commands.length, 1, 'привязка не ушла');
  assert.equal(commands[0].type, 'link_actual');
  assert.equal(document.querySelector('#fb-save'), null,
    'у велосипеда форма оценки не показывается');
});

test('состояние тела выбрано заранее — «Фон»', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  const фон = chip('Фон');
  assert.ok(фон, 'нет варианта «Фон»');
  assert.ok(фон.classList.contains('on'),
    '«Фон» не выбран заранее — в обычный день это лишний тап');
});

test('нажатый чип отмечен, повторное нажатие снимает выбор', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  const тянет = chip('Тянет');
  click(тянет);
  await waitFor(() => chip('Тянет') && chip('Тянет').classList.contains('on'));
  assert.ok(chip('Тянет').classList.contains('on'), 'чип не отмечен');
  assert.ok(!chip('Фон').classList.contains('on'),
    '«Фон» остался отмеченным — выбраны два значения сразу');

  click(chip('Тянет'));
  await waitFor(() => chip('Тянет') && !chip('Тянет').classList.contains('on'));
  assert.ok(!chip('Тянет').classList.contains('on'),
    'повторное нажатие не сняло выбор');
});

test('сохранение уходит одной командой link_actual с оценкой', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  const commands = await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  click(chip('Ноги свежие'));
  await waitFor(() => chip('Ноги свежие').classList.contains('on'));
  click(document.querySelector('#fb-save'));
  await waitFor(() => commands.length > 0);

  assert.equal(commands.length, 1, 'команд больше одной');
  assert.equal(commands[0].type, 'link_actual');
  assert.equal(commands[0].args.workout_id, 'w-1');
  assert.equal(commands[0].args.actual_id, 'a1');
  assert.equal(commands[0].args.feedback.easy_feel, 1);
  assert.equal(commands[0].args.feedback.body_status, 0);
});

test('пропуск формы сохраняет пустую оценку', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  const commands = await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-skip') !== null);

  click(document.querySelector('#fb-skip'));
  await waitFor(() => commands.length > 0);

  assert.equal(commands.length, 1);
  assert.equal(commands[0].type, 'link_actual');
  assert.deepEqual(commands[0].args.feedback, {},
    'пропуск должен сохранять пустую оценку, а не предыдущую');
});

test('комментарий уходит в оценку', async () => {
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: null,
  }];
  const commands = await loadApp({actual});
  openWeek();
  openWorkout('w-1');
  click(document.querySelector('[data-actual="a1"]'));
  await waitFor(() => document.querySelector('#fb-save') !== null);

  const comment = document.getElementById('fb-comment');
  comment.value = 'новые кроссовки';
  click(document.querySelector('#fb-save'));
  await waitFor(() => commands.length > 0);

  assert.equal(commands[0].args.feedback.comment, 'новые кроссовки');
});

test('у привязанной тренировки оценку можно открыть и отредактировать',
  async () => {
    const workout = makeWorkout({
      actual_id: 'a1',
      status: 'done',
      feedback: {body_status: -1, easy_feel: 1},
      feedback_kind: 'easy',
    });
    const actual = [{
      id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
      distance_m: 7000, linked_workout_id: 'w-1',
    }];
    const commands = await loadApp({week: makeWeek([workout]), actual});
    openWeek();
    openWorkout('w-1');

    const edit = document.querySelector('[data-fb-edit="w-1"]');
    assert.ok(edit, 'нет кнопки правки оценки');
    click(edit);
    await waitFor(() => document.querySelector('#fb-save') !== null);

    /* Уже отмеченное — отмечено в форме. */
    assert.ok(chip('Тянет').classList.contains('on'),
      'сохранённая оценка не подхвачена формой');

    click(document.querySelector('#fb-save'));
    await waitFor(() => commands.length > 0);
    assert.equal(commands[0].type, 'set_feedback',
      'правка оценки — это set_feedback, а не link_actual');
    assert.equal(commands[0].args.workout_id, 'w-1');
    assert.equal(commands[0].args.feedback.body_status, -1);
  });

test('маркеры оценки видны в плашке тренировки недели', async () => {
  const workout = makeWorkout({
    actual_id: 'a1', status: 'done',
    feedback: {body_status: -1, easy_feel: 1, want_one_more: 'enough'},
    feedback_kind: 'easy',
  });
  const actual = [{
    id: 'a1', date: '2026-11-22', sport: 'run', duration_min: 39,
    distance_m: 7000, linked_workout_id: 'w-1',
  }];
  await loadApp({week: makeWeek([workout]), actual});
  openWeek();

  const badges = [...document.querySelectorAll('.slot-badges .fb-badge')]
    .map((element) => element.textContent.trim());
  assert.ok(badges.includes('Тело -1'), 'нет маркера состояния тела');
  assert.ok(badges.includes('Ноги +1'), 'нет маркера ощущения');
});

test('без оценки маркеров в плашке нет', async () => {
  await loadApp({});
  openWeek();
  assert.equal(document.querySelectorAll('.slot-badges').length, 0,
    'у тренировки без оценки маркеры показаны');
});
