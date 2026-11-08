/* UI-тесты планирования следующей недели до закрытия текущей.
 *
 * Проверяем то, что просил Кирилл: закрыл неделю, а следующей
 * планировать негде — кнопки нет. Теперь она есть: карточка на экране
 * недели и кликабельная строка в «Сезоне».
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
    id: 'W4',
    season_week: 4,
    start: '2026-11-01',
    end: '2026-11-07',
    status,
    focus: 'Развиваем VO2max',
    load_target: {hours: 6.24, sessions: 7, distance_m: 35000},
    requests: [],
    assignments: [],
    unplaced: [],
    workouts: [],
    summary: null,
    can_activate: true,
    activate_blocked_by: null,
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

/* Текущая неделя — W4, планируется вперёд W5. */
const SEASON_PLAN = {
  id: 'S1',
  horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49},
  plans: [{id: 'g1', status: 'active', goal: '40:00',
           race_date: '2027-04-18', venue: 'S25 Berlin 10K'}],
  phases: [{id: 'run_base', objective: 'Поднимаем базовый объём',
            week_from: 1, week_to: 5}],
  macro_weeks: [
    {season_week: 4, phase_id: 'run_base', focus: 'vo2max',
     goal_text: 'Развиваем VO2max', run_km: 35, total_h: 6.24,
     sessions_target: 7, deload: false, status: 'active', has_fact: false,
     start: '2026-11-01', end: '2026-11-07'},
    {season_week: 5, phase_id: 'run_base', focus: 'threshold',
     goal_text: 'Порог', run_km: 38, total_h: 6.8,
     sessions_target: 7, deload: false, status: null, has_fact: false,
     start: '2026-11-08', end: '2026-11-14'},
    {season_week: 6, phase_id: 'run_base', focus: 'tempo',
     goal_text: 'Темп', run_km: 40, total_h: 7.0,
     sessions_target: 7, deload: false, status: null, has_fact: false,
     start: '2026-11-15', end: '2026-11-21'},
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

async function loadApp({week, onCommand, currentWeek = 4, selectedWeek,
                        weeks = [], pinned = false, weeksByNumber} = {}) {
  setupDom();
  // Ручной выбор недели живёт в localStorage: клиент читает его при
  // загрузке. Без него берётся неделя по календарю.
  if (selectedWeek) {
    localStorage.setItem('coach-app-week', String(selectedWeek));
  }
  if (pinned) {
    localStorage.setItem('coach-app-week-pinned', '1');
  }
  globalThis.__fixture = {
    version: 42,
    seasonWeek: selectedWeek ?? currentWeek,
    currentWeek,
    snapshot: SNAPSHOT,
    week: week === null ? null : (week || makeWeek('active')),
    weeksByNumber,
    actual: [],
    weeks,
    details: {},
    seasonPlan: SEASON_PLAN,
    onCommand,
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.getElementById('nav').children.length > 0);
}

/* Что видно на экране: шапка (номер недели) + содержимое. */
function screenText() {
  const bar = document.getElementById('appbar').textContent;
  const picker = document.getElementById('picker').textContent;
  return `${bar} ${picker}`.replace(/\s+/g, ' ');
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

function sentCommands() {
  return globalThis.__fixture.sent || [];
}

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('на экране недели есть карточка следующей недели', async () => {
  await loadApp();

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Следующая неделя/, 'нет карточки следующей недели');
  assert.match(text, /W5/, 'не указан номер следующей недели');
  assert.ok(document.querySelector('#plan-next-week'),
    'нет кнопки «Спланировать неделю» для следующей недели');
});

test('карточка показывает объём следующей недели из макро-плана', async () => {
  await loadApp();

  const card = document.querySelector('#plan-next-week').closest('.card');
  const text = card.textContent;
  assert.match(text, /38/, 'нет километража следующей недели');
  assert.match(text, /6\.8/, 'нет часов следующей недели');
});

test('нажатие шлёт propose_week для следующей недели', async () => {
  const sent = [];
  await loadApp({
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#plan-next-week'));
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'propose_week');
  assert.equal(sent[0].args.season_week, 5, 'планироваться должна следующая неделя');
  assert.ok(sent[0].reason, 'у команды нет причины');
});

test('на своей следующей неделе карточки нет', async () => {
  await loadApp({week: makeWeek('active'), currentWeek: 4, selectedWeek: 5});

  const text = document.getElementById('picker').textContent;
  assert.ok(!text.includes('Следующая неделя'),
    'на самой следующей неделе карточка не нужна');
});

test('спланированная следующая неделя открывается, а не планируется заново',
  async () => {
    const plan = {
      ...SEASON_PLAN,
      macro_weeks: SEASON_PLAN.macro_weeks.map((w) => (
        w.season_week === 5 ? {...w, status: 'proposed'} : w)),
    };
    setupDom();
    globalThis.__fixture = {
      version: 42,
      seasonWeek: 4,
      currentWeek: 4,
      snapshot: SNAPSHOT,
      week: makeWeek('active'),
      actual: [],
      weeks: [],
      details: {},
      seasonPlan: plan,
    };
    const url = new URL('../../client/app.js', import.meta.url).href;
    await import(`${url}?t=${Date.now()}${Math.random()}`);
    await waitFor(() => document.getElementById('nav').children.length > 0);

    const card = document.querySelector('#plan-next-week')?.closest('.card')
      || [...document.querySelectorAll('.card')]
        .find((c) => c.textContent.includes('Следующая неделя'));
    assert.ok(card, 'нет карточки следующей недели');
    const open = card.querySelector('[data-week="5"]');
    assert.ok(open, 'нет кнопки открытия запланированной недели');
    assert.ok(!document.querySelector('#plan-next-week'),
      'запланированную неделю не планируют заново');
    assert.match(card.textContent, /предложена/);
  });

test('кнопка активации заблокирована, пока предыдущая неделя не закрыта',
  async () => {
    await loadApp({
      week: makeWeek('proposed', {can_activate: false, activate_blocked_by: 'W3'}),
      currentWeek: 3,
    });

    const activate = document.querySelector('#activate');
    assert.ok(activate, 'нет кнопки активации');
    assert.ok(activate.disabled, 'активация должна быть недоступна');
    const text = document.getElementById('picker').textContent;
    assert.match(text, /W3/, 'не сказано, после закрытия какой недели');
  });

test('после закрытия предыдущей активация доступна', async () => {
  await loadApp({
    week: makeWeek('proposed', {can_activate: true, activate_blocked_by: null}),
    currentWeek: 3,
  });

  const activate = document.querySelector('#activate');
  assert.ok(activate, 'нет кнопки активации');
  assert.ok(!activate.disabled, 'активация должна быть доступна');
});

test('в «Сезоне» следующая неделя кликабельна, дальняя — нет', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="season"]'));

  const next = [...document.querySelectorAll('.macro-week')]
    .find((row) => row.textContent.includes('W5'));
  assert.ok(next, 'следующая неделя не найдена');
  assert.equal(next.tagName, 'BUTTON', 'следующая неделя должна быть кликабельна');

  const far = [...document.querySelectorAll('.macro-week')]
    .find((row) => row.textContent.includes('W6'));
  assert.ok(far, 'дальняя неделя не найдена');
  assert.equal(far.tagName, 'DIV', 'дальняя неделя не кликабельна');
});

/* ------------------------------------------------------------------ регрессы */

/* Кирилл: «воскресенье, вижу закрытую неделю на главном экране, и нет
 * никакой возможности предложить следующую». Воскресенье — первый день
 * новой недели: текущая неделя только началась, а открыта прошала.
 *
 * Этот тест повторяет ровно эту ситуацию: currentWeek = 5 (началась),
 * открыта закрытая W4, плана у W5 нет. Кнопка «Спланировать неделю»
 * обязана быть на главном экране.
 */
test('воскресенье: на главном экране есть кнопка спланировать текущую неделю',
  async () => {
    await loadApp({
      week: makeWeek('closed', {id: 'W4', season_week: 4}),
      currentWeek: 5,
      selectedWeek: 4,
    });

    const text = document.getElementById('picker').textContent;
    assert.ok(document.querySelector('#plan-next-week'),
      `нет кнопки «Спланировать неделю» на главном экране (текст: ${text.slice(0, 120)})`);
    assert.match(text, /W5/, 'не указан номер планируемой недели');
  });

test('воскресенье: планируется та неделя, что только началась, а не следующая за ней',
  async () => {
    const sent = [];
    await loadApp({
      week: makeWeek('closed', {id: 'W4', season_week: 4}),
      currentWeek: 5,
      selectedWeek: 4,
      onCommand: (command) => {
        sent.push(command);
        return Promise.resolve({version: 43, data: {status: 'applied'}});
      },
    });

    click(document.querySelector('#plan-next-week'));
    await waitFor(() => sent.length > 0);

    assert.equal(sent[0].type, 'propose_week');
    assert.equal(sent[0].args.season_week, 5,
      'планироваться должна начавшаяся неделя, а не следующая за ней');
  });

test('кнопка есть и на экране «Факт» открытой прошлой недели', async () => {
  await loadApp({
    week: makeWeek('closed', {id: 'W4', season_week: 4}),
    currentWeek: 5,
    selectedWeek: 4,
  });

  click(document.querySelector('#nav [data-screen="fact"]'));

  assert.ok(document.querySelector('#plan-next-week'),
    'на экране «Факт» нет кнопки спланировать неделю');
});

test('на своей неделе карточки нет — там и так видно, что с ней делать',
  async () => {
    await loadApp({
      week: makeWeek('proposed', {id: 'W5', season_week: 5}),
      currentWeek: 5,
      selectedWeek: 5,
    });

    const text = document.getElementById('picker').textContent;
    assert.ok(!text.includes('Следующая неделя'),
      'на самой планируемой неделе карточка не нужна');
  });

/* Метрики формы — списком, а не плитками: числа без пояснений не читаются. */
test('метрики формы показаны списком с пояснениями, а не плитками', async () => {
  const metrics = {
    week_id: 'W5',
    z2_min: 142.5, z3_min: 34.1, z4_min: 17.9, hi_min: 12,
    pace_z2: '5:20 на км',
    tss: 391.9,
    efficiency: 0.726,
    form_pace: '4:22 на км',
    vo2max: 51,
    cadence_work: 72, cadence_avg: 71,
    workouts_counted: 9,
    per_workout: [],
  };
  await loadApp({
    currentWeek: 5,
    selectedWeek: 5,
    week: makeWeek('active', {metrics}),
  });

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Минуты в зонах/, 'нет строки «Минуты в зонах»');
  assert.match(text, /Темп в Z2/, 'нет строки «Темп в Z2»');
  assert.match(text, /Нагрузка/, 'нет строки «Нагрузка»');
  assert.match(text, /73%/, 'эффективность без расшифровки в процентах');
  assert.match(text, /форма 4:22/, 'нет пояснения, что такое эффективность');
  // Плитки остались у итогов недели («ч план / ч факт / дельта») —
  // там три числа с подписями, и они читаются. Метрики формы — нет.
  const tiles = document.querySelectorAll('#picker .metrics .metric');
  assert.ok(tiles.length <= 3,
    `плитки метрик формы вернулись: ${tiles.length}`);
  assert.ok(document.querySelector('#picker .metrics-list .mrow'),
    'нет списка метрик');
});

/* ------------------------------------------------------------------ главный экран */

/* Кирилл: «сейчас уже идёт пятая неделя, показано всё ещё четвёртое.
 * Четвёртая неделя закрыта, а пятая не запланирована. Остатки
 * четвёртой недели на главном экране видеть не хочу».
 *
 * Правило: главный экран — это «сейчас». Закрытая прошлая неделя
 * уступает место текущей.
 */
test('закрытая прошлая неделя уступает главный экран текущей', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    weeks: [
      {id: 'W3', season_week: 3, status: 'closed'},
      {id: 'W4', season_week: 4, status: 'closed'},
    ],
    weeksByNumber: {
      4: makeWeek('closed', {id: 'W4', season_week: 4}),
      5: null,
    },
  });

  const text = screenText();
  assert.match(text, /Неделя 5/, 'главный экран показывает не текущую неделю');
  assert.ok(!text.includes('Неделя 4'),
    'на главном экране остались остатки закрытой недели');
});

test('незакрытая прошлая неделя остаётся на главном экране', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    weeks: [{id: 'W4', season_week: 4, status: 'active'}],
    weeksByNumber: {
      4: makeWeek('active', {id: 'W4', season_week: 4}),
      5: makeWeek('active', {id: 'W5', season_week: 5}),
    },
  });

  const text = screenText();
  assert.match(text, /Неделя 4/,
    'незакрытая неделя должна оставаться на главном экране');
});

test('неделя, выбранная руками в «Сезоне», не переключается', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    pinned: true,
    weeks: [{id: 'W4', season_week: 4, status: 'closed'}],
    weeksByNumber: {
      4: makeWeek('closed', {id: 'W4', season_week: 4}),
      5: makeWeek('active', {id: 'W5', season_week: 5}),
    },
  });

  const text = screenText();
  assert.match(text, /Неделя 4/,
    'ручной выбор недели должен уважаться: человек сам её открыл');
});

test('текущая неделя без плана: кнопка «Спланировать неделю»', async () => {
  // Недели W5 в хранилище нет: сервер отдаёт 404, клиент показывает
  // пустое состояние с кнопкой.
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    weeks: [{id: 'W4', season_week: 4, status: 'closed'}],
    weeksByNumber: {
      4: makeWeek('closed', {id: 'W4', season_week: 4}),
      5: null,
    },
  });

  const text = screenText();
  assert.match(text, /Неделя 5/, 'показана не текущая неделя');
  assert.match(text, /ещё не спланирована/i,
    'нет сообщения о незапланированной неделе');
  assert.ok(document.querySelector('#plan-week'),
    'нет кнопки «Спланировать неделю»');
});

test('на просмотренной прошлой неделе есть кнопка «сейчас»', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    pinned: true,
    weeks: [{id: 'W4', season_week: 4, status: 'closed'}],
    weeksByNumber: {
      4: makeWeek('closed', {id: 'W4', season_week: 4}),
      5: makeWeek('active', {id: 'W5', season_week: 5}),
    },
  });

  assert.ok(document.querySelector('#go-current'),
    'нет кнопки возврата на текущую неделю');
});

test('на текущей неделе кнопки «сейчас» нет', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 5,
    weeksByNumber: {5: makeWeek('active', {id: 'W5', season_week: 5})},
  });

  assert.ok(!document.querySelector('#go-current'),
    'на текущей неделе кнопка «сейчас» не нужна');
});

test('кнопка «сейчас» возвращает на текущую неделю', async () => {
  await loadApp({
    currentWeek: 5,
    selectedWeek: 4,
    pinned: true,
    weeks: [{id: 'W4', season_week: 4, status: 'closed'}],
    weeksByNumber: {
      4: makeWeek('closed', {id: 'W4', season_week: 4}),
      5: makeWeek('active', {id: 'W5', season_week: 5}),
    },
  });

  click(document.querySelector('#go-current'));
  await waitFor(() => screenText().includes('Неделя 5'));

  assert.match(screenText(), /Неделя 5/,
    'после «сейчас» должна быть текущая неделя');
  assert.equal(localStorage.getItem('coach-app-week-pinned'), null,
    'закрепление должно сняться');
});
