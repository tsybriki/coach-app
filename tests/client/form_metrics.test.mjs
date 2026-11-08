/* UI-тесты метрик формы.
 *
 * Проверяем то, что просил Кирилл: видеть прогресс формы по неделям,
 * а не только километраж. Метрики — над тренировками, и то же самое
 * для закрытых недель.
 *
 * Импортируется настоящий `client/app.js` — с его рендером и обработчиками
 * клика. Вместо сети и IndexedDB подставляются заглушки (см. helpers/).
 */
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';

import {JSDOM} from 'jsdom';

/* ------------------------------------------------------------------ фикстуры */

const WEEK_METRICS = {
  week_id: 'W4',
  z2_min: 142.5,
  z3_min: 61.0,
  z4_min: 22.4,
  hi_min: 18.3,
  tss: 236.7,
  pace_z2_sec_per_km: 305.0,
  pace_z2: '5:05 на км',
  vo2max: 50.5,
  efficiency: 1.02,
  cadence_avg: 81,
  cadence_work: 84,
  workouts_counted: 8,
  per_workout: [
    {actual_id: 'g-1', z2_min: 40.0, pace_z2: '5:10 на км', tss: 60.0,
     cadence_work: 84},
    {actual_id: 'g-2', z2_min: 22.5, pace_z2: '4:55 на км', tss: 45.0,
     cadence_work: 83},
  ],
};

const WORKOUT_METRICS = {
  actual_id: 'a-1',
  z2_min: 40.0,
  z3_min: 15.0,
  z4_min: 5.0,
  hi_min: 3.0,
  pace_z2_sec_per_km: 310.0,
  pace_z2: '5:10 на км',
  tss: 60.0,
  intensity_factor: 0.8,
  normalized_power_w: 200,
  vo2max: 51.0,
  efficiency: 1.01,
  cadence_avg: 82,
  cadence_work: 84,
  workout_counted: true,
  duration_min: 51,
  distance_m: 8000,
  avg_hr: 140,
  zones: {Z1: 5, Z2: 40, Z3: 15, Z4: 5},
};

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
    workouts: [
      {
        id: 'w-1', request_id: 'r1', sport: 'run', kind: 'quality', focus: 'Z6',
        objective: {name: 'Качественная: VO2max', day: 'ПН', time: '18:45'},
        duration_min: 51, status: 'planned', actual_id: 'a-1', steps: [],
      },
    ],
    summary: null,
    metrics: WEEK_METRICS,
    ...extra,
  };
}

const SNAPSHOT = {
  season: {horizon: {start: '2026-10-11', end: '2027-09-18', season_week_count: 49}},
  athlete: {vdot: 48, hr_max: 182, lth: 164, hr_zones: {}},
};

const ACTUAL = [
  {id: 'a-1', date: '2026-11-02', sport: 'run', duration_min: 51,
   distance_m: 8000, hr_avg: 140, moderate_min: 0, vigorous_min: 0,
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

async function loadApp({week, metrics, actual = ACTUAL, athlete, ftpEstimate,
                        onCommand} = {}) {
  setupDom();
  globalThis.__fixture = {
    version: 42,
    seasonWeek: 4,
    currentWeek: 4,
    snapshot: SNAPSHOT,
    week: week || makeWeek('active'),
    actual,
    weeks: [],
    details: {},
    metrics: metrics || {},
    athlete: athlete || SNAPSHOT.athlete,
    ftpEstimate: ftpEstimate || null,
    onCommand,
    seasonPlan: {horizon: SNAPSHOT.season.horizon, plans: [], phases: [],
                 macro_weeks: []},
  };
  const url = new URL('../../client/app.js', import.meta.url).href;
  await import(`${url}?t=${Date.now()}${Math.random()}`);
  await waitFor(() => document.getElementById('nav').children.length > 0);
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

/* ------------------------------------------------------------------ тесты */

beforeEach(() => {
  globalThis.__fixture = undefined;
});

test('экран «Факт»: метрики формы недели показаны', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Метрики формы/, 'нет блока метрик');
  assert.match(text, /142\.5/, 'нет минут в Z2');
  assert.match(text, /5:05 на км/, 'нет темпа в Z2');
  assert.match(text, /236\.7/, 'нет нагрузки');
  assert.match(text, /50\.5/, 'нет VO2max');
});

test('метрики недели — над тренировками, а не под фактом', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="fact"]'));

  const card = [...document.querySelectorAll('.card')]
    .find((c) => c.textContent.includes('Метрики формы'));
  assert.ok(card, 'нет карточки метрик');
  // Внутри карточки — и плитки, и строки по тренировкам.
  assert.ok(card.querySelectorAll('.metric').length > 0, 'нет плиток метрик');
  assert.match(card.textContent, /темп Z2/, 'нет строк по тренировкам');
});

test('метрики недели показывают факт, а не план', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="fact"]'));

  const card = [...document.querySelectorAll('.card')]
    .find((c) => c.textContent.includes('Метрики формы'));
  const labels = [...card.querySelectorAll('.metric .l')].map((n) => n.textContent);
  assert.ok(labels.every((l) => !/план/i.test(l)),
    `в метриках есть план: ${labels.join(', ')}`);
});

test('неделя без разборов — понятное сообщение, а не нули', async () => {
  const metrics = {...WEEK_METRICS, workouts_counted: 0};
  await loadApp({week: makeWeek('active', {metrics})});

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Метрики формы/);
  assert.match(text, /нет разбора/i);
});

test('карточка тренировки: метрики фактической тренировки', async () => {
  await loadApp({metrics: {'a-1': WORKOUT_METRICS}});

  click(document.querySelector('.slot[data-slot="w-1"]'));
  await waitFor(() => document.querySelector('.metrics-block'));

  const block = document.querySelector('.metrics-block');
  assert.ok(block, 'нет блока метрик на карточке тренировки');
  assert.match(block.textContent, /Метрики формы/);
  assert.match(block.textContent, /40/, 'нет минут в Z2');
  assert.match(block.textContent, /5:10 на км/, 'нет темпа в Z2');
  assert.match(block.textContent, /60/, 'нет нагрузки');
});

test('карточка тренировки: без разбора — сообщение', async () => {
  await loadApp({metrics: {'a-1': {...WORKOUT_METRICS, workout_counted: false}}});

  click(document.querySelector('.slot[data-slot="w-1"]'));
  await waitFor(() => document.querySelector('.metrics-note'));

  const note = document.querySelector('.metrics-note');
  assert.ok(note, 'нет сообщения о разборе');
  assert.match(note.textContent, /нет разбора/i);
});

test('закрытая неделя: метрики видны из плана', async () => {
  const summary = {
    week_id: 'W4',
    closed_at: '2026-11-07T12:00:00+00:00',
    totals: {planned_minutes: 391, actual_minutes: 424, planned_sessions: 9,
             actual_sessions: 9},
    verdict: {done: 8, missed: 1, extra: 1},
    per_session: [], missed: [], extra: [], deviations: [],
    intensity: {actual_moderate: 424, actual_vigorous: 0, contributions: []},
    metrics: WEEK_METRICS,
  };
  await loadApp({week: makeWeek('closed', {summary})});

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Метрики формы/, 'у закрытой недели нет метрик');
  assert.match(text, /142\.5/, 'нет минут в Z2');
  assert.match(text, /236\.7/, 'нет нагрузки');
});

test('неделя, закрытая до появления метрик: берём посчитанные сервером', async () => {
  // Неделя закрыта, когда метрик ещё не было: в саммари их нет.
  const summary = {
    week_id: 'W4',
    closed_at: '2026-11-07T12:00:00+00:00',
    totals: {planned_minutes: 391, actual_minutes: 424, planned_sessions: 9,
             actual_sessions: 9},
    verdict: {done: 8, missed: 1, extra: 1},
    per_session: [], missed: [], extra: [], deviations: [],
    intensity: {actual_moderate: 424, actual_vigorous: 0, contributions: []},
    metrics: {},
  };
  await loadApp({week: makeWeek('closed', {summary})});

  click(document.querySelector('#nav [data-screen="fact"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /142\.5/, 'метрики не показаны');
  assert.ok(!/Нет разбора FIT/.test(text),
    'неделя должна брать метрики с сервера, а не из пустого саммари');
});

test('экран закрытия недели: метрики формы на месте', async () => {
  await loadApp();

  click(document.querySelector('#nav [data-screen="close"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Метрики формы/, 'на экране закрытия нет метрик');
  assert.match(text, /142\.5/);
});

test('экран атлета: без FTP показана оценка и кнопка', async () => {
  await loadApp({ftpEstimate: {estimated_ftp_w: 380, current_ftp_w: null,
                              workouts_used: 12}});

  click(document.querySelector('#nav [data-screen="athlete"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /Порог мощности/, 'нет блока FTP');
  assert.match(text, /380/, 'нет оценки FTP');
  assert.match(text, /12 тренировкам/, 'не сказано, по чему оценка');
  assert.ok(document.querySelector('#set-ftp'), 'нет кнопки подтверждения');
});

test('экран атлета: подтверждение оценки шлёт update_athlete', async () => {
  const sent = [];
  await loadApp({
    ftpEstimate: {estimated_ftp_w: 380, current_ftp_w: null, workouts_used: 12},
    onCommand: (command) => {
      sent.push(command);
      return Promise.resolve({version: 43, data: {status: 'applied'}});
    },
  });

  click(document.querySelector('#nav [data-screen="athlete"]'));
  const button = document.querySelector('#set-ftp');
  assert.ok(button, 'нет кнопки подтверждения');
  click(button);
  await waitFor(() => sent.length > 0);

  assert.equal(sent[0].type, 'update_athlete');
  assert.equal(sent[0].args.ftp_w, 380);
});

test('экран атлета: заданный FTP показан, кнопки нет', async () => {
  await loadApp({athlete: {...SNAPSHOT.athlete, ftp_w: 411}});

  click(document.querySelector('#nav [data-screen="athlete"]'));

  const text = document.getElementById('picker').textContent;
  assert.match(text, /411/, 'не виден заданный FTP');
  assert.ok(!document.querySelector('#set-ftp'),
    'при заданном FTP кнопки быть не должно');
});
