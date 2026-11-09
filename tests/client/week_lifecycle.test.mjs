/* UI-тесты жизненного цикла недели: propose → activate → close.
 *
 * Проверяем то, что сломалось у пользователя: кнопка «Закрыть неделю»
 * не сработала, и на экране не появилось ничего — ни ошибки, ни отказа.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и обработчиками
 * клика. Вместо сети и IndexedDB подставляются заглушки (см. helpers/).
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
        duration_min: 51, status: 'planned', actual_id: 'a-1', steps: [],
      },
    ],
    summary: status === 'closed' ? {
      week_id: 'W3',
      closed_at: '2026-10-31T12:00:00+00:00',
      totals: {planned_minutes: 391, actual_minutes: 424, planned_sessions: 9,
               actual_sessions: 9},
      verdict: {done: 8, missed: 1, extra: 1},
      per_session: [], missed: [], extra: [], deviations: [],
      intensity: {actual_moderate: 424, actual_vigorous: 0, contributions: []},
    } : null,
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

const ACTUAL = [
  {id: 'a-1', date: '2026-10-26', sport: 'run', duration_min: 51,
   distance_m: 8000, hr_avg: 160, moderate_min: 0, vigorous_min: 0,
   linked_workout_id: 'w-1'},
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
    onCommand,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
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

function click(element) {
  element.dispatchEvent(new global.window.MouseEvent('click', {
    bubbles: true, cancelable: true,
  }));
}

function openWeek() {
  click(document.querySelector('#nav [data-screen="week"]'));
}

/* Команда, которую клиент отправил на сервер. */
function sentCommands() {
  return globalThis.__fixture.sent || [];
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('предложенная неделя: есть «Активировать», закрыть ещё нельзя', async () => {
  await loadApp({week: makeWeek('proposed')});

  assert.ok(document.querySelector('#activate'), 'нет кнопки «Активировать неделю»');
  assert.ok(document.querySelector('#propose'), 'нет кнопки «Предложить заново»');
  assert.ok(!document.querySelector('#close'), 'у proposed-недели не должно быть «Закрыть»');
});

test('активная неделя: есть «Закрыть неделю»', async () => {
  await loadApp({week: makeWeek('active')});

  assert.ok(document.querySelector('#close'), 'нет кнопки «Закрыть неделю»');
  assert.ok(!document.querySelector('#activate'), 'активную неделю активировать нельзя');
});

/* Закрытие — замок в шапке карточки «Фокус недели»: действие
 * необратимое, и отдельная маленькая кнопка не нажимается случайно. */
test('кнопка закрытия — в шапке карточки «Фокус недели»', async () => {
  await loadApp({week: makeWeek('active')});

  const head = document.querySelector('.goal-head');
  assert.ok(head, 'нет шапки карточки фокуса');
  const close = head.querySelector('#close');
  assert.ok(close, 'в шапке карточки фокуса нет кнопки закрытия');
  // Иконка замка: по ней понятно, что это закрыть.
  assert.match(close.textContent, /🔒/, 'нет иконки замка');
  assert.ok(close.getAttribute('title'),
    'у кнопки закрытия нет подсказки');
});

test('кнопка закрытия не вынесена в отдельную карточку', async () => {
  await loadApp({week: makeWeek('active')});

  // Кнопка стоит в шапке карточки фокуса, а не в карточке, где она
  // была бы единственным содержимым.
  const ownCard = [...document.querySelectorAll('.card')].find((c) => {
    const close = c.querySelector('#close');
    if (!close) return false;
    // В карточке фокуса есть заголовок и текст — кнопка не одна.
    return !c.querySelector('.goal-head');
  });
  assert.ok(!ownCard, 'кнопка закрытия стоит отдельной карточкой');
});

/* Графики прогресса — выполнение цели недели. Кирилл попросил их
 * вернуть после того, как плитки плана убрали: прогресс и план были
 * разными вещами, просто стояли рядом. */
test('графики прогресса в карточке фокуса', async () => {
  await loadApp({
    week: makeWeek('active', {
      progress: {
        hours: {planned: 6.24, actual: 3.1},
        sessions: {planned: 7, actual: 3},
        distance_m: {planned: 35000, actual: 15000},
      },
    }),
  });

  const card = document.querySelector('.card.goal');
  assert.ok(card, 'нет карточки фокуса');
  const progress = card.querySelector('.progress');
  assert.ok(progress, 'графики прогресса не в карточке фокуса');
  assert.equal(progress.querySelectorAll('.prog-row').length, 3,
    'ожидались часы, сессии и километраж');
  assert.match(progress.textContent, /из 6\.2/, 'нет плана по часам');
});

test('закрытая неделя: плашки статуса нет, статус в заголовке', async () => {
  await loadApp({week: makeWeek('closed')});

  assert.ok(!document.querySelector('#close'), 'закрытую неделю закрывать нельзя');
  assert.ok(!document.querySelector('#activate'), 'закрытую неделю активировать нельзя');

  /* Плашки со статусом на экране больше нет: статус живёт в
   * заголовке, цветным словом. */
  const picker = document.getElementById('picker').textContent;
  assert.ok(!picker.includes('Неделя закрыта'),
    'плашка статуса всё ещё на экране');

  const badge = document.querySelector('#appbar .week-status');
  assert.ok(badge, 'в заголовке нет статуса недели');
  assert.match(badge.textContent, /закрыта/i);
  assert.ok(badge.classList.contains('bad'),
    'закрытая неделя должна быть красной');
});

test('закрытая неделя: итоги видны на экране «План vs факт»', async () => {
  await loadApp({week: makeWeek('closed')});

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /391|6\.5|424|7\.1/, 'не видно итогов недели');
});

/* Статус недели — в заголовке, цветным словом.
 *
 * Активна — зелёный, предложена — оранжевый, закрыта — красный. Плашки
 * со статусом на экране нет: она была шумом, а статус принадлежит
 * заголовку.
 */
test('активная неделя: плашки статуса нет, в заголовке зелёный статус',
  async () => {
    await loadApp({week: makeWeek('active')});

    const picker = document.getElementById('picker').textContent;
    assert.ok(!picker.includes('Неделя активна'),
      'плашка статуса всё ещё на экране');

    const badge = document.querySelector('#appbar .week-status');
    assert.ok(badge, 'в заголовке нет статуса недели');
    assert.match(badge.textContent, /активна/i);
    assert.ok(badge.classList.contains('good'),
      'активная неделя должна быть зелёной');
  });

test('предложенная неделя: в заголовке оранжевый статус', async () => {
  await loadApp({week: makeWeek('proposed')});

  const badge = document.querySelector('#appbar .week-status');
  assert.ok(badge, 'в заголовке нет статуса недели');
  assert.match(badge.textContent, /предложена/i);
  assert.ok(badge.classList.contains('warn'),
    'предложенная неделя должна быть оранжевой');
});

test('статус в заголовке стоит рядом с диапазоном недели', async () => {
  await loadApp({week: makeWeek('active')});

  const sub = document.querySelector('#appbar .sub').textContent;
  assert.match(sub, /25 окт|25\s+окт/, 'нет диапазона недели');
  assert.match(sub, /активна/i, 'нет статуса в заголовке');
});

test('нажатие «Активировать» отправляет команду activate_week', async () => {
  const sent = [];
  await loadApp({
    week: makeWeek('proposed'),
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#activate'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'activate_week');
  assert.equal(sent[0].args.season_week, 3);
  assert.ok(sent[0].reason, 'у команды нет причины');
});

test('нажатие «Предложить заново» отправляет propose_week', async () => {
  const sent = [];
  await loadApp({
    week: makeWeek('proposed'),
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#propose'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'propose_week');
});

test('отказ сервера виден на экране, а не молчит', async () => {
  await loadApp({
    week: makeWeek('active'),
    onCommand: () => {
      const error = new Error('закрыть можно только active, а не proposed');
      error.code = 'invalid_command';
      return Promise.reject(error);
    },
  });

  click(document.querySelector('#close'));
  await waitFor(() => {
    const msg = document.querySelector('#msg');
    return msg && msg.textContent.includes('закрыть можно только');
  });

  const msg = document.querySelector('#msg');
  assert.ok(msg, 'сообщения об отказе нет на экране');
  assert.match(msg.textContent, /закрыть можно только/);
  assert.match(msg.className, /error/, 'отказ должен быть помечен как ошибка');
});

test('экран «Факт» у proposed-недели объясняет, что сначала активировать',
  async () => {
    await loadApp({week: makeWeek('proposed')});

    click(document.querySelector('#nav [data-screen="fact"]'));
    // Экран перерисовывается сразу — ждать нечего, только текст.
    const text = document.getElementById('picker').textContent;
    assert.match(text, /активировать/i);
    assert.ok(!document.querySelector('#close'), 'не должно быть кнопки закрытия');
  });

test('экран «Факт» у закрытой недели показывает итог', async () => {
  await loadApp({week: makeWeek('closed')});

  click(document.querySelector('#nav [data-screen="fact"]'));
  const text = document.getElementById('picker').textContent;
  assert.match(text, /закрыта/i);
  assert.ok(!document.querySelector('#close'), 'не должно быть кнопки закрытия');
});

/* Раздела «Закрыть» больше нет: он был мусором — отдельный экран с
 * тремя счётчиками, которые и так есть рядом. Закрытие относится к
 * факту: посчитать итог можно только когда факт вытянут. */
test('раздела «Закрыть» в меню нет', async () => {
  await loadApp();

  assert.ok(!document.querySelector('#nav [data-screen="close"]'),
    'в меню остался раздел «Закрыть»');
});

test('кнопка закрытия — внизу экрана «Факт»', async () => {
  await loadApp({week: makeWeek('active')});

  click(document.querySelector('#nav [data-screen="fact"]'));

  const btn = document.querySelector('#close');
  assert.ok(btn, 'на экране «Факт» нет кнопки закрытия');
  assert.match(btn.textContent, /Закрыть неделю/);

  /* Кнопка — в самом низу: сначала факт и метрики, потом закрытие. */
  const children = [...document.getElementById('picker').children];
  assert.ok(children.length > 1, 'на экране «Факт» один блок');
  assert.ok(btn.closest('#picker'),
    'кнопка закрытия вне экрана «Факт»');
});

test('пока идёт команда, кнопки заблокированы и плашка не гаснет', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await loadApp({
    week: makeWeek('proposed'),
    onCommand: () => gate.then(() => ({version: 43, data: {status: 'applied'}})),
  });

  click(document.querySelector('#activate'));
  await waitFor(() => document.querySelector('#activate')?.disabled === true);

  const activate = document.querySelector('#activate');
  assert.ok(activate.disabled, 'кнопка не заблокирована во время команды');
  const msg = document.querySelector('#msg');
  assert.ok(msg, 'нет плашки о выполняемой команде');
  assert.match(msg.textContent, /Активирую/);

  release();
  await waitFor(() => document.querySelector('#activate') === null
    || document.querySelector('#activate').disabled === false);
});
