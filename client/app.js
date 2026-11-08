/* Coach App — клиент.
 *
 * Одностраничное приложение. Экраны — проекции из снапшота, UI не знает,
 * как считается план.
 *
 * Офлайн: показываем кэш с отметкой «данные на <время>». Команды без сети
 * уходят в очередь и применяются при появлении сети.
 */

import * as api from './api.js';
import {
  getCache, putCache, enqueue, pendingCommands, removeCommand, markAttempt,
} from './store.js';
import { linkCandidates } from './link.js';
import { axisLabels, polyline, timeLabels, toPoints, zoneBands } from './chart.js';
import {
  groupBlocks,
  isExerciseBlock,
  isSetBlock,
  nameHasReps,
  repsLabel,
  setReps,
} from './structure.js';

const state = {
  screen: 'week',
  seasonWeek: Number(localStorage.getItem('coach-app-week')) || null,
  currentWeek: null,     // неделя сезона по календарю — её считает сервер
  // Неделя выбрана руками в «Сезоне» — её не переключаем на текущую
  // автоматически: человек сам открыл прошлую неделю, чтобы её посмотреть.
  seasonWeekPinned: localStorage.getItem('coach-app-week-pinned') === '1',
  version: 0,
  week: null,
  season: null,
  athlete: null,
  actual: [],
  metrics: null,         // метрики формы недели
  ftpEstimate: null,     // оценка FTP по тренировкам
  detail: null,
  detailId: null,        // разбор какой факта открыт
  workoutMetrics: null,  // метрики открытой фактической тренировки
  compose: null,         // разбор текста: что получилось из пожеланий
  composeText: '',       // исходный текст пожеланий
  composeBusy: false,    // идёт разбор: ждём модель
  composeError: null,    // разбор не удался
  composeAvailable: true, // доступен ли разбор (есть ли ключ модели)
  weeks: [],
  summary: null,
  seasonPlan: null,      // макро-план сезона: фазы и недели целиком
  slots: [],            // окна тренировок: расписание среды, куда попадает неделя
  stale: false,
  cachedAt: null,
  online: navigator.onLine,
  outbox: [],
  openWorkoutId: null,
  pickUnplaced: null,     // id висяка, для которого выбираем окно
  message: null,
  messageKind: 'info',   // 'info' — гаснет само, 'error' — ждёт действия
  messageTimer: null,
  busy: false,           // идёт команда: плашка не гаснет и экран не мигает
  base: localStorage.getItem('coach-app-base') || location.origin,
};

/* ------------------------------------------------------------------ рендер */

const picker = document.getElementById('picker');
const nav = document.getElementById('nav');
const bar = document.getElementById('appbar');
const cardWrap = document.getElementById('cardWrap');
const cardHost = document.getElementById('cardHost');
const detailWrap = document.getElementById('detailWrap');
const detailHost = document.getElementById('detailHost');

/* Нижняя навигация: иконка + подпись. Шесть экранов — в две строки нет,
 * поэтому нижняя навигация показывает пять, а шестой экран («Связывание»)
 * живёт внутри недели: факт — часть работы с неделей.
 */
const SCREENS = [
  ['week', 'Неделя', '📅'],
  ['fact', 'Факт', '📊'],
  ['season', 'Сезон', '🏆'],
  ['close', 'Закрыть', '🔒'],
  ['athlete', 'Атлет', '👤'],
];

function render() {
  renderNav();
  bar.innerHTML = chromeBar();
  renderScreen();
}

/* Шапка зависит от уровня вложенности:
 *   разбор  → «←» + название разбора
 *   тренировка → «←» + название тренировки
 *   раздел  → заголовок раздела
 */
function chromeBar() {
  if (state.detailId) {
    const fact = state.actual.find((a) => a.id === state.detailId);
    const title = fact
      ? `${((fact.distance_m || 0) / 1000).toFixed(1)} км · ${SPORT_NAME[fact.sport] || fact.sport}`
      : 'Разбор тренировки';
    return detailBar(title, fact ? fact.date : '');
  }
  // Разбор тренировки — подэкран недели: кнопка «назад» возвращает
  // в неё, а не вниз по истории приложения.
  if (state.screen === 'compose') {
    return detailBar('Предложить тренировку',
                     state.week ? `Неделя ${state.week.season_week}` : '');
  }
  if (state.openWorkoutId && state.week) {
    /* Тренировка может быть непривязанной — тогда у неё нет дня, и
     * в шапке это видно по подписи «не привязано». */
    const workout = findWorkout(state.openWorkoutId);
    if (workout) {
      const objective = workout.objective || {};
      const placed = objective.day !== undefined && objective.day !== null
        && objective.day !== '';
      const subtitle = placed ? (objective.day || '')
        : 'не привязано';
      return detailBar(objective.name || workout.kind || 'Тренировка',
                       subtitle);
    }
  }
  return appBar();
}

/* Кнопка «сейчас» — вернуться на текущую неделю.
 *
 * Пока человек смотрит прошлую неделю, главный экран остаётся на ней:
 * он сам её открыл. Но вернуться к «сейчас» должно быть можно в один
 * тап, иначе придётся перезапускать приложение.
 */
function backToCurrentButton() {
  const current = state.currentWeek;
  if (!current || !state.seasonWeek || state.seasonWeek === current) return '';
  return `<button class="now-btn" id="go-current">сейчас</button>`;
}

/* Шапка приложения: заголовок, счётчик версии, кнопка обновить. */
function appBar() {
  const stale = state.stale
    ? `<span class="stale">данные на ${timeOf(state.cachedAt)}</span>`
    : '';
  const queued = state.outbox.length
    ? `<span class="queued">в очереди: ${state.outbox.length}</span>`
    : '';
  return `<div class="title">
        <div>${escapeHtml(screenTitle())}</div>
        <div class="sub">${screenSubtitle()}</div>
      </div>
      <div class="right">
        ${stale}${queued}
        ${backToCurrentButton()}
        <span class="ver">v${state.version}</span>
        <button class="refresh" id="refresh">↻</button>
      </div>`;
}

function screenTitle() {
  if (state.screen === 'week') {
    return state.week ? `Неделя ${state.week.season_week}` : 'Неделя';
  }
  // Разбор тренировки — подэкран недели, в нижней навигации его нет.
  if (state.screen === 'compose') {
    return 'Предложить тренировку';
  }
  const found = SCREENS.find(([id]) => id === state.screen);
  return found ? found[1] : 'Coach';
}

/* Статус недели — цветным словом в подзаголовке заголовка.
 *
 * Цвет по статусу: активна — зелёный, предложена — оранжевый, закрыта —
 * красный. Отдельной плашкой статус показывать не надо: он принадлежит
 * заголовку, а не экрану.
 */
const WEEK_STATUS_COLOR = {
  active: 'good',
  proposed: 'warn',
  closed: 'bad',
};

function weekStatusBadge() {
  const status = (state.week && state.week.status) || 'proposed';
  const label = WEEK_STATUS[status] || status;
  const color = WEEK_STATUS_COLOR[status] || 'warn';
  return `<span class="week-status ${color}">${escapeHtml(label)}</span>`;
}

function screenSubtitle() {
  if (state.screen === 'week' && state.week) {
    // Диапазон недели: даты по-русски, иначе «11-01 — 11-07».
    const from = formatDate(state.week.start);
    const to = formatDate(state.week.end);
    const range = (!from || !to)
      ? `${state.week.start.slice(5)} — ${state.week.end.slice(5)}`
      : `${from} — ${to}`;
    return `${escapeHtml(range)} · ${weekStatusBadge()}`;
  }
  if (state.screen === 'fact' && state.week) {
    return `${state.actual.length} сессий в факте`;
  }
  if (state.screen === 'season' && state.season) {
    return `${state.season.horizon.season_week_count} недель`;
  }
  return '';
}

/* Основной экран — по выбранному разделу. */
function renderScreen() {
  const body = state.screen === 'week' ? screenWeek()
    : state.screen === 'season' ? screenSeason()
    : state.screen === 'fact' ? screenFact()
    : state.screen === 'close' ? screenClose()
    : state.screen === 'compose' ? screenCompose()
    : screenAthlete();
  picker.innerHTML = body;
}

function barInner() {
  const stale = state.stale
    ? `<span class="stale">данные на ${timeOf(state.cachedAt)}</span>`
    : '';
  const queued = state.outbox.length
    ? `<span class="queued">в очереди: ${state.outbox.length}</span>`
    : '';
  return `<span class="ver">v${state.version}</span>
      ${stale}${queued}
      <button class="refresh" id="refresh">обновить</button>`;
}

/* Сообщение — под шапкой, отдельным блоком. */
function messageBlock() {
  return state.message
    ? `<div class="msg ${escapeHtml(state.messageKind)}" id="msg">${escapeHtml(state.message)}</div>`
    : '';
}

/* Статус недели по-русски. */
const WEEK_STATUS = {
  proposed: 'предложена',
  active: 'активна',
  closed: 'закрыта',
};

/* Итог саммари — одной строкой: что сделано против плана. */
function summaryLine(summary) {
  if (!summary) return '';
  const totals = summary.totals || {};
  const verdicts = Object.entries(summary.verdict || {})
    .filter(([, count]) => count)
    .map(([name, count]) => `${count} ${name}`)
    .join(' · ');
  const parts = [];
  if (totals.planned_minutes) {
    parts.push(`${formatHours(totals.planned_minutes)} ч план · `
      + `${formatHours(totals.actual_minutes)} ч факт`);
  }
  if (verdicts) parts.push(verdicts);
  return parts.join(' · ');
}

/* Показать сообщение. Информационное гаснет само через несколько секунд —
 * иначе плашка висит и закрывает половину экрана. Ошибка ждёт действия:
 * её закрывают вручную. */
function showMessage(text, kind = 'info') {
  state.message = text;
  state.messageKind = kind;
  if (state.messageTimer) {
    clearTimeout(state.messageTimer);
    state.messageTimer = null;
  }
  // Пока идёт команда, плашка не гаснет: выкачка Garmin занимает
  // полминуты, и «Закрываю неделю…» должно её пережить.
  if (kind === 'info' && !state.busy) {
    state.messageTimer = setTimeout(() => {
      state.message = null;
      state.messageTimer = null;
      render();
    }, 4000);
  }
}

/* Иконка вида спорта — как в эталонном plan-wN.html. */
const SPORT_NAME = {
  run: 'Бег', bike: 'Велосипед', swim: 'Плавание', hiit: 'HIIT',
  strength: 'Силовая', ofp: 'ОФП', mobility: 'Мобильность',
};

const KIND_ICON = {
  run: '🏃', bike: '🚴', swim: '🏊', ofp: '💪',
  strength: '🏋️', mobility: '🧘', hiit: '⚡', brick: '🔄',
};

/* Вид тренировки — по-русски. Ключ `easy` читателю ничего не
 * говорит: «Лёгкий бег» и «Длинный бег» говорят. */
const WORKOUT_KIND_RU = {
  easy: 'Лёгкий бег',
  long: 'Длинный бег',
  quality: 'Качественная работа',
  key_run: 'Ключевая работа',
  bike: 'Велосипед',
  swim: 'Плавание',
  ofp: 'ОФП',
  mobility: 'Мобильность',
  strength: 'Силовая',
  brick: 'Брикет',
};

/* Название тренировки: своё, если есть, иначе вид по-русски. */
function workoutTitle(workout) {
  const objective = workout.objective || {};
  if (objective.name) return objective.name;
  return WORKOUT_KIND_RU[workout.kind] || workout.kind;
}

function kindTag(sport) {
  return `<span class="kind kind-${escapeHtml(sport)}">${escapeHtml(sport)}</span>`;
}

/* Роль шага — по-русски. */
const ROLE_RU = {
  warmup: 'разминка',
  work: 'работа',
  rest: 'отдых',
  cooldown: 'заминка',
  transition: 'переход',
};

/* Порядок дней тренировочной недели: вс→сб. */
const DAY_ORDER = ['ВС', 'ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ'];

/* Месяцы коротко — для дат в плашке тренировки. */
const MONTHS_SHORT = [
  'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
];

/* Плашка тренировки в списке недели. По нажатию — детали.
 *
 * В шапке — день недели, дата и время: без них тренировку нельзя
 * положить в календарь. Дата приходит из окна, в которое попала
 * тренировка (сервер считает), клиент её только показывает.
 *
 * **Километраж рядом с длительностью.** «55 мин» ничего не говорит о
 * том, длинная это тренировка или нет; «55 мин · 6,2 км» говорит. Чтобы
 * не раздувать плашку, оба числа стоят в одной правой колонке, а
 * километраж — под временем, мельче.
 */
function slotButton(workout, actual) {
  const objective = workout.objective || {};
  const title = workoutTitle(workout);
  const day = dayName(objective.day || workout.day);
  const date = objective.date || workout.date || '';
  const focus = workout.focus && workout.focus !== 'core'
    ? workout.focus : '';
  const done = actual ? ' <span class="done-mark">✓</span>' : '';

  const when = [
    day,
    date ? `<span class="date">${escapeHtml(formatDate(date))}</span>` : '',
    workout.time || '',
  ].filter((part) => part).join(' · ');

  /* Километраж плана — по шагам с дистанцией (сервер считает). Нет
   * дистанции — не показываем: «0 км» враньё, а тренировки без
   * дистанции (силовая, бассейн) её не имеют. */
  const km = plannedKm(workout);
  const durBlock = `<span class="dur-box">
      <span class="dur">${formatDuration(workout.duration_min)}${done}</span>
      ${km ? `<span class="km">${km}</span>` : ''}
    </span>`;

  const actualLine = actual
    ? `<div class="done-line">${((actual.distance_m || 0) / 1000).toFixed(1)} км · ${formatDuration(actual.duration_min)}${actual.hr_avg ? ` · HR ${actual.hr_avg}` : ''}</div>`
    : '';

  return `<button class="slot${actual ? ' done' : ''}" data-slot="${escapeHtml(workout.id)}">
      <div class="slot-head">
        <span class="ico">${KIND_ICON[workout.sport] || '🎯'}</span>
        <span class="day">${when}</span>
        ${durBlock}
      </div>
      <div class="name">${escapeHtml(title)}</div>
      ${focus ? `<div class="focus">🎯 ${escapeHtml(focus)}</div>` : ''}
      ${actualLine}
    </button>`;
}

/* Километраж тренировки — строкой «14,3 км» или пусто, если дистанции нет.
 *
 * Метры приходят с сервера (по шагам с дистанцией). Планка: меньше
 * километра показывать нечего — «0,3 км» это шум, а не объём.
 *
 * Разряды: до 10 км — всегда с десятой («8,0 км»), дальше — с десятой
 * только если дробная часть есть («14,3 км»), иначе целое («14 км»).
 * Округлять вниз до целых врало бы: «14 км» вместо 14,3.
 */
function plannedKm(workout) {
  const meters = Number(workout.distance_m || 0);
  if (!meters || meters < 1000) return '';
  const km = meters / 1000;
  const withTenth = km < 10 || Math.abs(km - Math.round(km)) > 0.05;
  const text = withTenth ? km.toFixed(1) : String(Math.round(km));
  return `${text.replace('.', ',')} км`;
}

/* День недели по-русски. Приходит либо названием («ПН»), либо номером
 * (0 — воскресенье): на экране нужен один вид, а не два. */
function dayName(value) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'number') {
    return DAY_ORDER[value] || '';
  }
  const text = String(value);
  if (/^\d+$/.test(text)) {
    return DAY_ORDER[Number(text)] || '';
  }
  return text;
}

/* День недели по-русски, полным названием: «воскресенье».
 *
 * Дата приходит из факта в ISO-формате («2026-11-08»). Разбирается
 * как дата, а не как строка: «2026-11-08» — это 8 ноября 2026 года,
 * и день недели из неё считается по календарю, а не выводится из
 * номера месяца.
 */
const WEEKDAY_FULL = [
  'воскресенье', 'понедельник', 'вторник', 'среда',
  'четверг', 'пятница', 'суббота',
];

function weekdayFull(iso) {
  const parts = String(iso || '').split('-');
  if (parts.length !== 3) return '';
  const [year, month, day] = parts.map(Number);
  if (!year || !month || !day) return '';
  const date = new Date(Date.UTC(year, month - 1, day));
  if (Number.isNaN(date.getTime())) return '';
  return WEEKDAY_FULL[date.getUTCDay()] || '';
}

/* Дата недели — компактно: «5 ноя» или «5 ноя 2027», если год другой. */
function formatDate(iso) {
  if (!iso) return '';
  const parts = String(iso).split('-');
  if (parts.length !== 3) return '';
  const month = MONTHS_SHORT[Number(parts[1]) - 1];
  if (!month) return '';
  const year = Number(parts[0]);
  const current = new Date().getFullYear();
  return year === current
    ? `${Number(parts[2])} ${month}`
    : `${Number(parts[2])} ${month} ${year}`;
}

/* Тренировки в порядке дней недели, внутри дня — по времени.
 *
 * День сравнивается по названию («ВС»…«СБ»), а не по тому, что пришло:
 * в данных это может быть и номер, и название, а порядок должен быть
 * один. Иначе тренировка с номером дня уезжает в конец списка.
 */
function sortedWorkouts(workouts) {
  return [...workouts].sort((a, b) => {
    const dayA = DAY_ORDER.indexOf(dayName((a.objective || {}).day || a.day));
    const dayB = DAY_ORDER.indexOf(dayName((b.objective || {}).day || b.day));
    if (dayA !== dayB) return (dayA < 0 ? 99 : dayA) - (dayB < 0 ? 99 : dayB);
    const timeA = String(a.time || '99:99');
    const timeB = String(b.time || '99:99');
    if (timeA !== timeB) return timeA.localeCompare(timeB);
    return String((a.objective || {}).name || '').localeCompare(
      String((b.objective || {}).name || ''), 'ru');
  });
}

/* Размещённые тренировки недели.
 *
 * В `week.workouts` лежат **все** тренировки недели, включая
 * непривязанные: планировщик создаёт тренировку для каждого запроса, а
 * запрос уходит в `unplaced`. Показывать все — значит показать каждую
 * дважды: один раз в списке размещённых и один раз в списке висяков.
 *
 * Размещённая тренировка — та, у которой есть окно: `objective.day`
 * проставлен при привязке.
 */
function placedWorkouts(week) {
  return (week.workouts || []).filter((w) => {
    const objective = w.objective || {};
    return objective.day !== undefined && objective.day !== null
      && objective.day !== '';
  });
}

/* Главный экран недели.
 *
 * **Плана-плиток здесь нет.** Раньше стоял блок из трёх плиток (часы,
 * сессии, километраж) с планом, а под ним — те же три величины с
 * прогрессом: «7,5 ч · план» рядом с «0 из 7,5 ч». Два блока об одном
 * и том же — шум. Плитки убраны, графики прогресса вернулись: они
 * показывают выполнение цели недели, а не план второй раз.
 *
 * В шапке карточки «Фокус недели» — две маленькие иконки справа: замок
 * (закрыть неделю) и календарь со стрелкой (предложить следующую
 * неделю). Обе — необратимые или меняющие состояние действия, обе
 * маленькие, чтобы не нажимались случайно.
 */
function screenWeek() {
  if (!state.week) return screenWeekMissing();
  const week = state.week;
  const placed = placedWorkouts(week);
  const unplaced = week.unplaced || [];

  const slots = sortedWorkouts(placed).map((w) => {
    const actual = state.actual.find((a) => a.id === w.actual_id);
    return slotButton(w, actual);
  }).join('');

  /* Счётчик — по всем тренировкам недели: «9 тренировок», из них
   * 3 размещены. Считать только размещённые — значит спрятать от
   * читателя неделю, в которой половина тренировок ещё не расставлена. */
  const total = (week.workouts || []).length;
  const placedCount = placed.length;

  return `${messageBlock()}
    ${focusCard(week)}
    ${weekActions(week)}
    <h2 class="slots-header">Тренировки · ${placedCount} из ${total}</h2>
    <div class="slots-list">${slots || '<p class="empty">Размещённых тренировок нет.</p>'}</div>
    ${unplacedBlock(week)}`;
}

/* Карточка фокуса недели: заголовок, действия справа и прогресс.
 *
 * Иконки в шапке:
 *   - замок — закрыть неделю (только у активной: закрывают активную);
 *   - календарь со стрелкой — предложить следующую неделю.
 *
 * Кнопка «предложить следующую» ведёт туда же, куда большая карточка,
 * что была на главном экране: в неделю, которую ещё можно предложить.
 * Если предложение уже есть — открывает её.
 */
function focusCard(week) {
  const focus = week.focus || '';
  const status = week.status || 'proposed';

  const closeBtn = status === 'active'
    ? `<button class="card-act" id="close" title="Закрыть неделю"
         aria-label="Закрыть неделю">🔒</button>`
    : '';

  // Следующая неделя — только если её есть чем предложить или открыть.
  const nextBtn = nextWeekButton();

  return `<div class="card goal">
      <div class="goal-head">
        <h3>Фокус недели</h3>
        <div class="goal-acts">${nextBtn}${closeBtn}</div>
      </div>
      ${focus ? `<p class="lead">${escapeHtml(focus)}</p>` : ''}
      ${progressBlock(week.progress)}
    </div>`;
}

/* Следующая неделя, которую можно планировать.
 *
 * Это **первая неделя, с которой ещё надо что-то сделать**, начиная с
 * текущей. Не «текущая + 1»:
 *
 *   - воскресенье: началась W5, плана у неё нет — планировать надо её;
 *   - вторник: W4 активна и запланирована — планировать W5.
 *
 * Если у текущей недели плана нет — предлагаем её. Если есть — берём
 * следующую по календарю: там уже может быть предложение (тогда её
 * открывают) или не быть (тогда её планируют).
 */
function nextPlannableWeek() {
  const macro = (state.seasonPlan && state.seasonPlan.macro_weeks) || [];
  const current = state.currentWeek;
  if (!current) return null;

  const byNumber = new Map(macro.map((w) => [w.season_week, w]));
  const currentMacro = byNumber.get(current);
  if (currentMacro && !currentMacro.status) return current;

  const next = current + 1;
  return byNumber.has(next) ? next : null;
}

/* Неделя макро-плана — по номеру. В ней и объём, и состояние: планы
 * хранятся в макро-плане сезона, а не в отдельном списке. */
function macroWeekOf(seasonWeek) {
  const weeks = (state.seasonPlan && state.seasonPlan.macro_weeks) || [];
  return weeks.find((w) => w.season_week === seasonWeek) || null;
}

/* Карточка следующей недели.
 *
 * Планировать следующую можно и до закрытия текущей — активировать
 * нельзя. Карточка ведёт в следующую неделю: спланировать её, если её
 * ещё нет, или открыть, если она уже запланирована.
 *
 * **Показывается всегда**, кроме одного случая: когда открыта сама
 * следующая неделя — там она тавто, и так видно, что с ней делать.
 *
 * Раньше карточка жила только на экране текущей недели, и в воскресенье
 * (когда текущая неделя только началась, а открыта была прошлая) кнопки
 * «Спланировать неделю» не было вообще. Планировать следующую можно
 * независимо от того, какая неделя открыта.
 */

/* Непривязанные тренировки — под размещёнными.
 *
 * Авто-привязка работает плохо, и решение о времени тренировки
 * принимает пользователь. Поэтому висяки показаны списком, и тап по
 * висяку открывает список окон недели: выбрал — привязал.
 *
 * Проверок нет: если пользователь решил поставить тренировку в это
 * окно — значит, она там и стоит. Даже если окно уже занято или
 * тренировка в него не влезает: план мягкий, и «нельзя» здесь было бы
 * ровно тем, от чего мы уходим.
 */
function unplacedBlock(week) {
  const unplaced = week.unplaced || [];
  if (!unplaced.length) return '';

  const windows = state.slots || [];
  const picked = unplaced.find((u) => u.id === state.pickUnplaced);
  const pickedSport = picked ? picked.sport : null;
  const rows = unplaced.map((u) => {
    const icon = KIND_ICON[u.sport] || '🎯';
    const label = u.name || u.focus || u.kind || 'Тренировка';
    /* Строка висяка — два действия.
     *
     * Тап по самой строке открывает детали тренировки: то же, что
     * открывает тап по размещённой. Иначе про висяк известно только
     * «Лёгкий бег, 46 мин» — и куда его поставить, решаешь вслепую.
     *
     * Кнопка «привязать» — отдельная: она открывает выбор окна. Так
     * оба действия не мешают друг другу, и привязка остаётся ровно
     * такой, какой была.
     */
    const km = plannedKm(u);
    return `<div class="unplaced-row">
        <button class="unplaced-open" data-unplaced="${escapeHtml(u.id)}">
          <span class="ico">${icon}</span>
          <span class="body">
            <span class="name">${escapeHtml(label)}</span>
            <span class="meta">${escapeHtml(formatDuration(u.duration_min))}${km ? ` · ${escapeHtml(km)}` : ''}</span>
          </span>
        </button>
        <button class="unplaced-bind" data-bind-pick="${escapeHtml(u.id)}">
          привязать
        </button>
      </div>`;
  }).join('');

  const picker = state.pickUnplaced
    ? slotPicker(state.pickUnplaced, windows, pickedSport)
    : '';

  return `<h2 class="slots-header">Не привязано · ${unplaced.length}</h2>
    <div class="unplaced-list">${rows}</div>
    ${picker}`;
}

/* Выбор окна для висяка — на экране деталей.
 *
 * Тот же выбор окон, что и в списке недели: окна и правило «не
 * подходит» — одни и те же. Отличается только то, где список стоит.
 */
function slotPickerFor(requestId, sport) {
  if (state.pickUnplaced !== requestId) return '';
  return slotPicker(requestId, state.slots || [], sport);
}

/* Выбор окна для висяка.
 *
 * У окна есть место: в асфальтовом окне велосипеда нет, станок стоит
 * дома. Поэтому у каждого окна показано, что в него можно положить —
 * иначе пользователь кладёт вел туда, где его нет.
 */
function slotPicker(requestId, windows, sport) {
  if (!windows.length) {
    return '<div class="card warn"><div class="chead">Окна недели неизвестны</div></div>';
  }
  const rows = windows.map((slot) => {
    const day = slot.day_name || dayName(slot.day);
    const time = slot.start && slot.end
      ? `${slot.start}–${slot.end}` : (slot.start || '');
    const cap = slot.capacity_min ? `${slot.capacity_min} мин` : '';
    const fits = slotFitsSport(slot, sport);
    return `<button class="slot-choice${fits ? '' : ' slot-bad'}"
        data-bind-slot="${escapeHtml(slot.id)}"
        data-bind-request="${escapeHtml(requestId)}"
        data-bind-start="${escapeHtml(slot.start || '')}"
        data-bind-day="${escapeHtml(slot.day ?? '')}">
        <span class="day">${escapeHtml(day)}</span>
        <span class="win-time">${escapeHtml(time)}</span>
        <span class="num">${escapeHtml(cap)}</span>
        ${fits ? '' : '<span class="warn">не подходит</span>'}
      </button>`;
  }).join('');
  return `<div class="card">
      <div class="chead">Куда привязать</div>
      <div class="slot-choices">${rows}</div>
    </div>`;
}

/* Подходит ли тренировка по виду спорта в это окно. */
function slotFitsSport(slot, sport) {
  if (!sport) return true;
  const forbidden = slot.forbidden_sports || [];
  return !forbidden.includes(sport);
}

/* Недели ещё нет — её можно спланировать.
 *
 * Неделя создаётся из макро-плана сезона и правил Дэниэлса: объём по
 * видам спорта — из макро, качественная работа бега — из правил, раскладка
 * по слотам — из среды. Команда `propose_week` создаёт неделю, если её
 * ещё нет в хранилище.
 */
function screenWeekMissing() {
  const disabled = state.busy ? ' disabled' : '';
  const week = state.seasonWeek;
  const macro = (state.seasonPlan?.macro_weeks || [])
    .find((w) => w.season_week === week);
  /* Кнопка предложения — и здесь.
   *
   * Неделя ещё не спланирована, и предложить ей тренировку из текста
   * как раз и нужно: пользователь описал тренировку, а неделю планировать
   * целиком он не хочет. Тренировка станет висяком внутри ещё не
   * спланированной недели — а неделя при этом появится.
   */
  const composeBtn = state.composeAvailable === false
    ? ''
    : `<button class="action secondary" id="compose-open">Предложить тренировку</button>`;
  const plan = macro
    ? `<div class="totals-card">
        <div class="metrics">
          <div class="metric"><div class="v">${macro.run_km.toFixed(0)}</div><div class="l">км</div></div>
          <div class="metric"><div class="v">${formatHours(macro.total_h * 60)}</div><div class="l">ч · план</div></div>
          <div class="metric"><div class="v">${macro.sessions_target || 0}</div><div class="l">сессий</div></div>
        </div>
      </div>`
    : '';
  return `${messageBlock()}
    <h2>Неделя ${week}</h2>
    ${plan}
    <div class="card">
      <div class="chead">Неделя ещё не спланирована</div>
      <p class="lead">Объём взят из макро-плана сезона, качественная работа —
      по правилам Дэниэлса, время — по твоим окнам тренировок.</p>
    </div>
    <button class="action primary" id="plan-week"${disabled}>Спланировать неделю</button>
    ${composeBtn}`;
}

/* Действия недели.
 *
 * Жизненный цикл: proposed → active → closed. Каждый переход — команда
 * пользователя, ничего не инициируется само (I19). У закрытой недели
 * действий нет: она не меняется (I23).
 *
 * Плашки со статусом («Неделя активна · 9 тренировок · 0 сессий в
 * факте») больше нет: статус живёт в заголовке — цветным словом, а
 * счётчики тренировок и факта и так видны на экране. Карточка осталась
 * только у предложенной недели: там есть что делать — предложить
 * тренировку, пересобрать план, активировать.
 */
function weekActions(week) {
  const status = week.status || 'proposed';

  if (status !== 'proposed') {
    // Активная и закрытая неделя: отдельного блока действий у них нет.
    return '';
  }

  const label = WEEK_STATUS[status] || status;

  // proposed: неделю можно пересобрать, оживить или дополнить тренировкой.
  //
  // Активация — только после закрытия предыдущей недели (I45). Пока
  // предыдущая неделя не закрыта, активировать нельзя: неделя ждёт очереди.
  // Правило решает сервер, клиент только показывает его ответ.
  const blockedBy = week.activate_blocked_by;
  const canActivate = week.can_activate !== false && !blockedBy;
  const disabled = state.busy ? ' disabled' : '';
  // Кнопка активации заблокирована и во время команды, и пока активация закрыта
  // правилом: активировать нельзя, пока предыдущая неделя не закрыта.
  const activateAttr = (state.busy || !canActivate) ? ' disabled' : '';
  const blockedNote = blockedBy
    ? `<p class="lead">Активация — после закрытия недели ${escapeHtml(blockedBy)}</p>`
    : '';
  /* Кнопка «Предложить тренировку» — только пока неделя не активна.
   *
   * В активной неделе план уже исполняется: добавлять тренировки и
   * удалять их — значит менять то, что уже начали делать. В proposed
   * неделе план ещё можно переделать — это и есть время предлагать и
   * убирать лишнее.
   */
  const composeBtn = state.composeAvailable === false
    ? ''
    : `<button class="action secondary" id="compose-open">Предложить тренировку</button>`;
  return `<div class="card"><div class="chead">Неделя ${escapeHtml(label)}</div>
    <p class="lead">${(week.workouts || []).length} тренировок · `
    + `${state.actual.length} сессий в факте</p>
    ${blockedNote}
    ${composeBtn}
    <div class="action-row">
      <button class="action" id="propose"${disabled}>Предложить заново</button>
      <button class="action primary" id="activate"${activateAttr}>Активировать неделю</button>
    </div></div>`;
}

/* Факт против плана: «N из M».
 *
 * Три величины недели — часы, сессии, километраж — и полоска выполнения
 * по каждой. Показываются по всем трём: в неделе может быть 12 сессий
 * из 9, и одна цифра это не покажет.
 */
function progressBlock(progress) {
  if (!progress) return '';
  const rows = [];

  const hours = progress.hours || {};
  if (hours.planned) {
    rows.push(progressRow('ч', formatHours(hours.actual * 60),
      formatHours(hours.planned * 60), hours.actual / hours.planned));
  }

  const sessions = progress.sessions || {};
  if (sessions.planned) {
    rows.push(progressRow('сессий', String(sessions.actual), String(sessions.planned),
      sessions.actual / sessions.planned));
  }

  const distance = progress.distance_m || {};
  if (distance.planned) {
    rows.push(progressRow('км', (distance.actual / 1000).toFixed(1),
      (distance.planned / 1000).toFixed(0),
      distance.actual / distance.planned));
  }

  if (!rows.length) return '';
  return `<div class="progress">${rows.join('')}</div>`;
}

/* Одна строка прогресса: факт, план и доля выполнения. */
function progressRow(label, actual, planned, share) {
  const pct = Math.round(Math.min(share, 1.5) * 100);
  const over = share > 1.02;
  const width = Math.min(100, pct);
  return `<div class="prog-row">
      <span class="prog-label">${escapeHtml(label)}</span>
      <span class="prog-value ${over ? 'over' : ''}">${escapeHtml(actual)}</span>
      <span class="prog-plan">из ${escapeHtml(planned)}</span>
      <span class="prog-bar"><i style="width:${width}%"${over ? ' class="over"' : ''}></i></span>
    </div>`;
}

/* Список факта недели — для выбора: что связать с этой тренировкой. */
function factList(workout) {
  const facts = linkCandidates(workout, state.actual).map((a) => {
    return `<button class="fact" data-actual="${escapeHtml(a.id)}"
        data-workout="${escapeHtml(workout.id)}">
        <span class="ico">${KIND_ICON[a.sport] || '🎯'}</span>
        <span class="body">
          <span class="date">${a.date}</span>
          <span class="meta">${SPORT_NAME[a.sport] || a.sport} · ${((a.distance_m || 0) / 1000).toFixed(1)} км · ${formatDuration(a.duration_min)}${a.hr_avg ? ` · HR ${a.hr_avg}` : ''}</span>
        </span>
        <span class="act">связать</span>
      </button>`;
  }).join('');
  return facts || `<p>${SPORT_NAME[workout.sport] || workout.sport}: активностей нет</p>`;
}

/* Цвета фаз — по фокусу недели. Читаемая шкала, а не украшение:
 * по вертикали сезона видно, что тренируется. */
const PHASE_COLOR = {
  run_base: '#7ec8e3',
  run_build: '#f0c674',
  run_specific: '#d8a0ff',
  run_taper: '#ff9b6a',
  tri_base: '#5cd6c0',
  tri_build: '#7ee787',
  tri_specific: '#7aa2ff',
  tri_taper: '#d8a0ff',
  transition: '#9aa3b2',
  race_run: '#ff6b5a',
  race_tri: '#ff6b5a',
};

const PHASE_NAME = {
  run_base: 'База',
  run_build: 'Порог',
  run_specific: 'Специфика',
  run_taper: 'Тапер',
  tri_base: 'База триатлона',
  tri_build: 'Связки',
  tri_specific: 'Специфика триатлона',
  tri_taper: 'Тапер триатлона',
  transition: 'Переход',
  race_run: 'Гонка',
  race_tri: 'Гонка',
};

/* Экран сезона: макро-план целиком.
 *
 * Что видно: фазы сезона, а в каждой — недели с фокусом и объёмом.
 * Закрытые недели — с фактом; тап по неделе открывает её.
 */
function screenSeason() {
  const plan = state.seasonPlan;
  if (!plan || !plan.macro_weeks || !plan.macro_weeks.length) {
    return `${messageBlock()}<h2>Сезон</h2>`
      + empty('Макро-план сезона ещё не загружен');
  }

  const goal = (plan.plans || []).find((p) => p.status === 'active') || {};
  const race = goal.race_date
    ? `<div class="card goal"><h3>Цель сезона</h3>
        <p class="lead">${escapeHtml(goal.goal || '')}</p>
        <p class="lead">${escapeHtml(goal.venue || '')} · ${escapeHtml(goal.race_date)}</p>
      </div>`
    : '';

  // Недели по фазам — в порядке фаз плана, недели внутри фазы по номеру.
  const byPhase = new Map();
  for (const week of plan.macro_weeks) {
    if (!byPhase.has(week.phase_id)) byPhase.set(week.phase_id, []);
    byPhase.get(week.phase_id).push(week);
  }

  const phaseBlocks = (plan.phases || []).map((phase) => {
    const weeks = byPhase.get(phase.id) || [];
    if (!weeks.length) return '';
    const color = PHASE_COLOR[phase.id] || '#9aa3b2';
    const rows = weeks.map((week) => macroWeekRow(week, color)).join('');
    const range = phase.week_from && phase.week_to
      ? `недели ${phase.week_from}–${phase.week_to}`
      : '';
    return `<div class="card phase-block">
      <div class="phase-head">
        <span class="dot" style="background:${color}"></span>
        <span class="phase-name">${escapeHtml(PHASE_NAME[phase.id] || phase.id)}</span>
        <span class="phase-range">${escapeHtml(range)}</span>
      </div>
      <p class="lead">${escapeHtml(phase.objective || '')}</p>
      ${rows}
    </div>`;
  }).join('');

  return `${messageBlock()}<h2>Макро-план сезона</h2>
    <div class="sub">${plan.horizon.start} — ${plan.horizon.end} ·
      ${plan.macro_weeks.length} недель в плане ·
      ${plan.horizon.season_week_count} недель в сезоне</div>
    ${race}
    ${phaseBlocks}`;
}

/* Неделя макро-плана: фокус, объём, состояние.
 *
 * Закрытая неделя — с фактом; тап открывает её. Текущая и будущие —
 * без факта: план ещё не исполнен, и выдумывать итог нельзя.
 *
 * Следующая неделя (та, что после текущей) — кликабельна: её можно
 * спланировать до закрытия текущей. Дальние недели — нет: наперёд
 * планируется одна неделя.
 */
function macroWeekRow(week, color) {
  const closed = week.status === 'closed';
  // «Сейчас» — неделя по календарю, а не та, которую смотрим: открыв
  // прошлую из «Сезона», отметка не должна переезжать на неё.
  const current = week.season_week === state.currentWeek;
  const next = week.season_week === nextPlannableWeek();
  const badge = closed
    ? `<span class="badge done">факт</span>`
    : (week.status
      ? `<span class="badge">${escapeHtml(WEEK_STATUS[week.status] || week.status)}</span>`
      : (current ? '<span class="badge current">сейчас</span>' : ''));
  const volume = week.run_km
    ? `<span class="vol">${Math.round(week.run_km)} км · ${formatHours(week.total_h * 60)} ч</span>`
    : '';
  const clickable = closed || week.status || next;
  const tag = clickable ? 'button' : 'div';
  const attrs = clickable
    ? ` data-week="${week.season_week}" id="season-week-${week.season_week}"`
    : '';
  const cls = `macro-week${closed ? ' closed' : ''}${current ? ' current' : ''}`;
  return `<${tag} class="${cls}"${attrs}>
      <span class="wk">W${week.season_week}</span>
      <span class="wk-body">
        <span class="wk-focus">${escapeHtml(week.goal_text || week.focus || '')}</span>
        <span class="wk-meta">${volume}</span>
      </span>
      ${badge}
    </${tag}>`;
}

/* Открыть неделю из макро-плана.
 *
 * Неделя выбирается и грузится: у клиента один снимок недели, и
 * переключение на другую неделю должно её подтянуть. Возврат на сезон —
 * кнопка «назад» в шапке: неделя → сезон.
 */
async function openSeasonWeek(seasonWeek) {
  localStorage.setItem('coach-app-week', String(seasonWeek));
  // Выбор руками — приложение не будет переключать эту неделю на
  // текущую само: человек открыл её специально.
  localStorage.setItem('coach-app-week-pinned', '1');
  state.seasonWeek = seasonWeek;
  state.seasonWeekPinned = true;
  state.screen = 'week';
  await load();
  showPicker();
}

/* Иконка «предложить следующую неделю» (или открыть уже предложенную).
 *
 * Одна кнопка на два случая: неделя ещё не предложена — предлагаем,
 * предложена — открываем. Иконка маленькая и в заголовке, чтобы не
 * превращать экран в карточку с объёмом.
 */
function nextWeekButton() {
  const next = nextPlannableWeek();
  if (!next) return '';
  /* На экране самой следующей недели иконка не нужна: там и так видно,
   * что с ней делать. */
  if (state.seasonWeek === next) return '';
  const macro = macroWeekOf(next);
  if (!macro) return '';
  const planned = Boolean(macro.status);
  const label = planned ? 'Открыть предложенную неделю' : 'Предложить следующую неделю';
  const hint = `${label} · W${next}`;
  return `<button class="card-act" id="plan-next-week"
      title="${hint}" aria-label="${hint}">📅</button>`;
}

/* Заголовок экрана с иконкой справа — как в карточке фокуса. */
function headWithNext(icon) {
  return `<div class="goal-head"><h2>План vs факт</h2>
    <div class="goal-acts">${icon}</div></div>`;
}

function screenFact() {
  if (!state.week) return empty('Неделя ещё не загружена');
  const summary = state.summary;
  const sessions = state.actual.length;
  // Метрики закрытой недели лежат в саммари: они посчитаны при
  // закрытии. Но неделя могла быть закрыта до появления метрик — тогда
  // в саммари их нет, и берём посчитанные сервером на лету.
  const metrics = (summary && summary.metrics && summary.metrics.workouts_counted)
    ? summary.metrics : state.metrics;
  const metricsBlock = weekMetricsBlock(metrics);
  const head = headWithNext(nextWeekButton());

  if (!summary) {
    return `${messageBlock()}${head}
      <div class="card">
        <div class="chead">Факт без саммари</div>
        <div class="metrics">
          <div class="metric"><div class="v">${sessions}</div><div class="l">сессий</div></div>
          <div class="metric"><div class="v">${(state.actual.reduce((sum, a) => sum + (a.distance_m || 0), 0) / 1000).toFixed(1)}</div><div class="l">км</div></div>
          <div class="metric"><div class="v">${formatHours(state.actual.reduce((sum, a) => sum + (a.duration_min || 0), 0))}</div><div class="l">ч · время</div></div>
        </div>
        <p>Итога ещё нет: неделя не закрыта.</p>
      </div>
      ${metricsBlock}`;
  }

  const totals = summary.totals || {};
  const rows = Object.entries(summary.verdict || {})
    .filter(([, count]) => count)
    .map(([name, count]) =>
      `<li><div class="row"><span>${escapeHtml(name)}</span><span class="num">${count}</span></div></li>`)
    .join('');

  const planned = totals.planned_minutes || 0;
  const actual = totals.actual_minutes || 0;
  const delta = actual - planned;

  return `${messageBlock()}${head}
    <div class="card">
      <div class="chead">Итоги недели</div>
      <div class="metrics">
        <div class="metric"><div class="v">${formatHours(planned)}</div><div class="l">ч · план</div></div>
        <div class="metric ${actual >= planned ? 'good' : 'warn'}"><div class="v">${formatHours(actual)}</div><div class="l">ч · факт</div></div>
        <div class="metric ${delta >= 0 ? 'good' : 'warn'}"><div class="v">${delta >= 0 ? '+' : ''}${formatHours(delta)}</div><div class="l">ч · дельта</div></div>
      </div>
    </div>
    <div class="card"><h3>Вердикты</h3><ul class="plain">${rows || '<li>нет</li>'}</ul></div>
    ${metricsBlock}`;
}

/* Метрики формы недели — над тренировками.
 *
 * Показываются и для текущей недели, и для закрытой: закрытая хранит
 * агрегат в саммари, текущая считается на лету сервером. Разница для
 * пользователя не видна — это один и тот же экран.
 *
 * Метрики без данных не рисуются: пустое значение честнее нуля.
 */
/* Метрики формы одной недели или тренировки.
 *
 * **Не плитки.** Квадраты с числами без пояснений — суета: непонятно,
 * где что и почему «0,68». Здесь строки «что — значение — что значит».
 * Читается взглядом, а не разбором.
 *
 * `scope` — 'week' или 'workout': у тренировки нет недельных итогов
 * («форма растёт» — про неделю), но всё остальное то же.
 */
function metricsRows(metrics, scope) {
  const rows = [];
  const row = (name, value, note) => {
    if (value === null || value === undefined || value === '') return;
    rows.push(`<div class="mrow">
      <span class="mname">${escapeHtml(name)}</span>
      <span class="mval">${escapeHtml(String(value))}</span>
      ${note ? `<span class="mnote">${escapeHtml(note)}</span>` : ''}
    </div>`);
  };

  // Объём в зонах: главный ответ на «какая неделя». Группируем в одну
  // строку — четыре отдельных числа в четырех плитках читались хуже.
  const zoneParts = [];
  const zmin = (v) => (v === null || v === undefined ? null : Math.round(v));
  const z2 = zmin(metrics.z2_min);
  const z3 = zmin(metrics.z3_min);
  const z4 = zmin(metrics.z4_min);
  const hi = zmin(metrics.hi_min);
  if (z2 !== null) zoneParts.push(`Z2 ${z2}`);
  if (z3 !== null) zoneParts.push(`Z3 ${z3}`);
  if (z4 !== null) zoneParts.push(`Z4 ${z4}`);
  if (hi !== null) zoneParts.push(`инт ${hi}`);
  row('Минуты в зонах', zoneParts.join(' · '),
    'пульс: Z2 лёгкая, Z3 порог, Z4 выше, инт — интенсивная');

  row('Темп в Z2', metrics.pace_z2, 'какой темп держишь на низком пульсе');
  row('Нагрузка', metrics.tss ? `${metrics.tss} TSS` : null,
    'объём × интенсивность, как в TrainingPeaks');

  if (metrics.efficiency !== null && metrics.efficiency !== undefined) {
    // Эффективность без расшифровки — просто дробь. Показываем темп
    // по форме рядом: «форма 4:22, факт 5:52» объясняет всё.
    const eff = Math.round(metrics.efficiency * 100);
    const note = metrics.form_pace
      ? `форма ${metrics.form_pace} — фактический темп составляет ${eff}% от неё`
      : `${eff}% от темпа, который позволяет форма`;
    row('Эффективность', `${eff}%`, note);
  }

  row('VO₂max', metrics.vo2max, 'форма по Garmin');

  if (metrics.cadence_work) {
    row('Каденция', `${metrics.cadence_work} ш/мин`,
      metrics.cadence_avg
        ? `в рабочей части; в среднем ${metrics.cadence_avg}`
        : 'в рабочей части');
  }

  if (scope === 'week' && metrics.workouts_counted) {
    row('Тренировок с разбором', metrics.workouts_counted,
      'остальным без FIT-разбора метрики посчитать не из чего');
  }

  return rows.join('');
}

/* Название выполненной тренировки для списка: «воскресенье 13 км».
 *
 * Раньше здесь стоял идентификатор Garmin («g-25010651701») — на экране
 * это ничего не значило: ни дня, ни объёма. Человеку нужен день и
 * сколько он набегал.
 *
 * Километраж — тем же `plannedKm`, что и в плашке тренировки: одна
 * величина на экране пишется одним способом. У силовой и велотренировки
 * километров нет, и «0 км» читалось бы как «набегал ноль».
 */
function workoutLabel(item) {
  const day = weekdayFull(item.date);
  const km = plannedKm({distance_m: item.distance_m});
  if (day && km) return `${day} ${km}`;
  if (day) return day;
  if (km) return km;
  return item.actual_id || '';
}

function weekMetricsBlock(metrics) {
  if (!metrics) return '';
  const counted = metrics.workouts_counted || 0;
  if (!counted) {
    return `<div class="card">
      <div class="chead">Метрики формы</div>
      <p class="lead">Нет разбора FIT — метрики посчитать не из чего.</p>
    </div>`;
  }

  const rows = metricsRows(metrics, 'week');
  if (!rows) return '';

  const perWorkout = metrics.per_workout || [];
  const items = perWorkout.map((item) => {
    const bits = [];
    if (item.pace_z2) bits.push(`темп ${item.pace_z2}`);
    if (item.z2_min) bits.push(`Z2 ${Math.round(item.z2_min)} мин`);
    if (item.tss) bits.push(`нагрузка ${item.tss}`);
    if (item.cadence_work) bits.push(`кад ${item.cadence_work}`);
    return `<div class="mrow"><span class="mname">${escapeHtml(workoutLabel(item))}</span>
      <span class="mval">${escapeHtml(bits.join(' · ') || '—')}</span></div>`;
  }).join('');

  return `<div class="card">
      <div class="chead">Метрики формы</div>
      <div class="metrics-list">${rows}</div>
      ${items ? `<div class="chead sub">По тренировкам</div>
      <div class="metrics-list">${items}</div>` : ''}
    </div>`;
}

/* Метрики формы одной фактической тренировки.
 *
 * Метрики считаются сервером из разбора FIT: без разбора их нет.
 * Пока грузятся — блок пустой, а не «ноль»: иначе выглядит как
 * «метрики посчитались и равны нулю».
 */
function workoutMetricsBlock(actualId) {
  const metrics = state.workoutMetrics;
  if (!metrics || metrics.actual_id !== actualId) return '';
  if (!metrics.workout_counted) {
    return `<div class="metrics-note">Нет разбора FIT — метрики посчитать не из чего.</div>`;
  }

  const rows = metricsRows(metrics, 'workout');
  if (!rows) return '';
  return `<div class="metrics-block">
      <div class="lbl">Метрики формы</div>
      <div class="metrics-list">${rows}</div>
    </div>`;
}

/* Загрузить метрики тренировки и перерисовать карточку.
 *
 * Метрики не входят в ответ недели: они считаются на сервере из
 * разбора, и тянуть их для всех тренировок недели — лишний запрос.
 *
 * `skipReload` разрывает петлю: перерисовка карточки вызывает
 * `showWorkout` снова, а тот — снова грузит метрики. Без флага
 * приложение зацикливается.
 */
async function loadWorkoutMetrics(actualId, skipReload = false) {
  if (!actualId) return;
  try {
    const response = await api.getMetrics(actualId);
    state.workoutMetrics = response.data;
  } catch (error) {
    state.workoutMetrics = null;
  }
  if (skipReload) return;
  if (state.openWorkoutId) showWorkout(state.openWorkoutId, true);
}

function screenClose() {
  const week = state.week;
  const status = week ? (week.status || 'proposed') : 'proposed';
  const linked = week ? (week.workouts || []).filter((w) => w.actual_id).length : 0;
  // Метрики формы: закрытой недели — из саммари, текущей — с сервера.
  // Неделя, закрытая до появления метрик, в саммари их не имеет —
  // тогда берём посчитанные сервером.
  const summaryMetrics = week && week.summary && week.summary.metrics;
  const metrics = (summaryMetrics && summaryMetrics.workouts_counted)
    ? summaryMetrics : state.metrics;
  const metricsBlock = weekMetricsBlock(metrics);

  if (status === 'closed') {
    const line = summaryLine(week ? week.summary : null);
    return `${messageBlock()}<h2>Закрытие недели</h2>
    <div class="card">
      <div class="chead">Неделя закрыта</div>
      ${line ? `<p class="lead">${escapeHtml(line)}</p>` : ''}
      <div class="metrics">
        <div class="metric"><div class="v">${state.actual.length}</div><div class="l">сессий в факте</div></div>
        <div class="metric"><div class="v">${week ? (week.workouts || []).length : 0}</div><div class="l">в плане</div></div>
        <div class="metric"><div class="v">${linked}</div><div class="l">связано</div></div>
      </div>
    </div>
    ${metricsBlock}`;
  }

  if (status !== 'active') {
    // Закрыть можно только активную неделю: сначала активация.
    return `${messageBlock()}<h2>Закрытие недели</h2>
    <div class="card">
      <div class="chead">Сначала активируй неделю</div>
      <p class="lead">Неделя ${escapeHtml(WEEK_STATUS[status] || status)}: `
      + `закрыть можно только активную. Нажми «Активировать неделю» `
      + `на экране недели.</p>
    </div>`;
  }

  return `${messageBlock()}<h2>Закрытие недели</h2>
    <div class="card">
      <div class="chead">Неделя ${state.week ? state.week.season_week : ''}</div>
      <div class="metrics">
        <div class="metric"><div class="v">${state.actual.length}</div><div class="l">сессий в факте</div></div>
        <div class="metric"><div class="v">${week ? (week.workouts || []).length : 0}</div><div class="l">в плане</div></div>
        <div class="metric"><div class="v">${linked}</div><div class="l">связано</div></div>
      </div>
      <p class="lead">Закрытие посчитает итог: что планировали против что сделали. `
      + `Факт подтянется из Garmin автоматически.</p>
    </div>
    ${metricsBlock}
    <button class="action" id="close">Закрыть неделю</button>`;
}

/* Экран «Предложить тренировку»: текст пожеланий → структура.
 *
 * Два состояния: ввод текста и результат разбора. Разбор — чтение,
 * неделя не меняется; добавление в неделю — отдельное действие.
 */
function screenCompose() {
  const busy = state.composeBusy;
  const head = `<div class="card">
      <div class="chead">Предложить тренировку</div>
      <p class="lead">Опиши тренировку как хочешь. Разберу сам и покажу
      структуру до того, как она попадёт в неделю.</p>
    </div>`;

  const input = `<div class="card">
      <textarea id="compose-text" placeholder="Например: 12 км, 3 км разминка, дальше фартлек, заминка 1 км">${escapeHtml(state.composeText)}</textarea>
      <div class="chips">
        ${['12 км с фартлеком', 'Интервалы 8×400', 'Темповая 40 минут', 'Лёгкая 50 минут']
          .map((t) => `<button class="chip" data-compose-example="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join('')}
      </div>
      ${state.composeError ? `<div class="msg error" id="compose-error">${escapeHtml(state.composeError)}</div>` : ''}
      <button class="action primary" id="compose-run"${busy ? ' disabled' : ''}>${busy ? 'Разбираю…' : 'Разобрать'}</button>
    </div>`;

  if (!state.compose) return `${head}${input}`;

  const c = state.compose;
  const steps = (c.steps || []).map((s) => {
    const step = s.step || {};
    const focus = step.focus_value || {};
    const detail = [
      focus.zone ? `пульс до ${focus.zone}` : '',
      focus.pace_min_per_km ? `${focus.pace_min_per_km}/км` : '',
      focus.hr_target ? `HR ${focus.hr_target}` : '',
    ].filter((x) => x).join(' · ');
    const amount = step.target_type === 'distance'
      ? `${(step.target_value / 1000).toFixed(1).replace('.', ',')} км`
      : `${Math.round(step.target_value)} мин`;
    const role = ROLE_RU[step.role] || step.role || '';
    return `<div class="mrow">
        <span class="mname">${escapeHtml(role)}</span>
        <span class="mval">${escapeHtml(amount)}</span>
        ${detail ? `<span class="mnote">${escapeHtml(detail)}</span>` : ''}
      </div>`;
  }).join('');

  const assumptions = (c.assumptions || []).length
    ? `<div class="card"><div class="chead">Что я додумал</div>
        <ul class="plain">${c.assumptions.map((a) => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
      </div>`
    : '';

  const total = `${(c.distance_m / 1000).toFixed(1).replace('.', ',')} км · ${formatDuration(c.duration_min)}`;

  return `${head}
    <div class="card">
      <div class="chead">${escapeHtml(c.name || 'Тренировка')}</div>
      <div class="metrics-list">${steps}</div>
      <div class="mrow total"><span class="mname">Итого</span>
        <span class="mval">${escapeHtml(total)}</span></div>
    </div>
    ${assumptions}
    <div class="card">
      <p class="lead">Тренировка станет непривязанной: время и окно
      выберешь сам.</p>
      <button class="action primary" id="compose-add">Добавить в неделю</button>
      <button class="action secondary" id="compose-reset">Изменить текст</button>
    </div>`;
}

function screenAthlete() {
  if (!state.athlete) return empty('Профиль ещё не загружен');
  const a = state.athlete;
  const ftp = state.ftpEstimate;
  // FTP — порог мощности. Без него нагрузка (TSS) не считается, а
  // оценить его можно по тренировкам: 95-й перцентиль мощности.
  const ftpBlock = ftpBlockHtml(ftp, a);
  return `${messageBlock()}<h2>Атлет</h2>
    <div class="card">
      <div class="chead">Нормативы</div>
      <div class="metrics">
        <div class="metric"><div class="v">${a.vdot || '—'}</div><div class="l">VDOT</div></div>
        <div class="metric"><div class="v">${a.hr_max || '—'}</div><div class="l">HRmax</div></div>
        <div class="metric"><div class="v">${a.lth || '—'}</div><div class="l">ЛТП</div></div>
      </div>
      <ul class="plain" style="margin-top:10px">
        <li><div class="row"><span>Вес</span><span class="num">${a.weight_kg || '—'} кг</span></div></li>
        <li><div class="row"><span>Состояние</span><span class="num">${escapeHtml(a.form || '—')}</span></div></li>
      </ul>
    </div>
    ${ftpBlock}
    ${slotsBlock()}`;
}

/* FTP: текущее значение или оценка по тренировкам.
 *
 * Оценка не записывается сама: пока пользователь не подтвердит
 * значение, нагрузка не считается. Подставить выдуманный порог —
 * значит показать правдоподобную цифру, которой никто не мерил.
 */
function ftpBlockHtml(ftp, athlete) {
  const current = athlete.ftp_w;
  const estimated = ftp && ftp.estimated_ftp_w
    ? Math.round(ftp.estimated_ftp_w) : null;

  if (current) {
    return `<div class="card">
      <div class="chead">Порог мощности</div>
      <div class="metrics">
        <div class="metric"><div class="v">${current}</div><div class="l">ватт · FTP</div></div>
      </div>
    </div>`;
  }

  if (!estimated) {
    return `<div class="card">
      <div class="chead">Порог мощности</div>
      <p class="lead">FTP не задан — нагрузка не считается. Нужен разбор
      тренировок с мощностью.</p>
    </div>`;
  }

  return `<div class="card">
    <div class="chead">Порог мощности</div>
    <div class="metrics">
      <div class="metric"><div class="v">${estimated}</div><div class="l">ватт · оценка</div></div>
    </div>
    <p class="lead">Оценка по ${ftp.workouts_used || 0} тренировкам. Подтверди —
    и нагрузка (TSS) посчитается.</p>
    <button class="action primary" id="set-ftp" data-ftp="${estimated}">Принять ${estimated} Вт</button>
  </div>`;
}

/* Окна тренировок — расписание, в которое раскладывается неделя.
 *
 * Окна повторяются каждую неделю, поэтому они и живут в карточке
 * атлета, а не в неделе: это часть среды, а не плана.
 */
function slotsBlock() {
  const slots = state.slots || [];
  if (!slots.length) return '';
  const totalMin = slots.reduce((sum, s) => sum + (s.capacity_min || 0), 0);
  const rows = [...slots]
    .sort((a, b) => (a.day - b.day) || String(a.start).localeCompare(String(b.start)))
    .map((slot) => {
      const time = slot.start && slot.end ? `${slot.start}–${slot.end}` : (slot.start || '');
      const cap = slot.capacity_min ? `${slot.capacity_min} мин` : '';
      return `<li><div class="row win-row">
          <span class="win-day">${escapeHtml(slot.day_name || '')}</span>
          <span class="win-time">${escapeHtml(time)}</span>
          <span class="num">${escapeHtml(cap)}</span>
        </div></li>`;
    })
    .join('');
  return `<div class="card">
      <div class="chead">Окна тренировок</div>
      <ul class="plain win-list">${rows}</ul>
      <ul class="plain" style="margin-top:8px">
        <li><div class="row"><span>Всего в неделю</span><span class="num">${formatHours(totalMin)} ч</span></div></li>
      </ul>
    </div>`;
}

function empty(text) {
  return `<p>${escapeHtml(text)}</p>`;
}



/* ------------------------------------------------------------------ разбор */

/* Цвета зон пульса — по порядку, от Z1 к Z7. */
const ZONE_COLORS = [
  'rgba(92,214,192,.10)',
  'rgba(92,214,192,.16)',
  'rgba(240,198,116,.14)',
  'rgba(255,155,106,.14)',
  'rgba(216,160,255,.16)',
  'rgba(216,160,255,.22)',
  'rgba(255,107,90,.22)',
];

/* Зоны пульса атлета из профиля. */
function hrZones() {
  const zones = state.athlete && state.athlete.hr_zones;
  if (!zones) return [];
  return Object.entries(zones).map(([name, bounds], index) => ({
    name,
    low: bounds.low,
    high: bounds.high,
    color: ZONE_COLORS[index % ZONE_COLORS.length],
  }));
}

/* Экран разбора выполненной тренировки — третий уровень.
 *
 * Отдельный экран, а не блок внизу карточки: разбор — это данные другой
 * сущности (факт), а не продолжение описания тренировки.
 */
function screenDetail() {
  const detail = state.detail;
  if (!detail) {
    return `<div class="card"><p class="lead">Разбор не загружен</p></div>`;
  }
  return detailContent(detail);
}

/* Открыть разбор: свой экран, свой заголовок, своя кнопка «назад». */
function showDetail(actualId) {
  const fact = state.actual.find((a) => a.id === actualId);
  const title = fact
    ? `${((fact.distance_m || 0) / 1000).toFixed(1)} км · ${escapeHtml(SPORT_NAME[fact.sport] || fact.sport)}`
    : 'Разбор тренировки';

  state.detailId = actualId;
  detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
  detailWrap.classList.remove('hidden');
  cardWrap.classList.add('hidden');
  picker.classList.add('hidden');

  try {
    history.pushState({page: 'detail', actual: actualId}, '', `#d${actualId}`);
  } catch (error) {
    history.replaceState(null, '', `#d${actualId}`);
  }
  render();
  window.scrollTo(0, 0);
}

/* Содержимое разбора. */
function detailContent(detail) {
  const distance = (detail.distance_m || 0) / 1000;
  const moving = formatDuration((detail.duration_s || 0) / 60);

  const stats = `<div class="card">
      <div class="chead">Итоги</div>
      <div class="metrics">
        <div class="metric"><div class="v">${distance.toFixed(1)}</div><div class="l">км</div></div>
        <div class="metric"><div class="v">${moving}</div><div class="l">время</div></div>
        <div class="metric"><div class="v">${detail.avg_hr ?? '—'}</div><div class="l">HR средний</div></div>
        <div class="metric"><div class="v">${detail.max_hr ?? '—'}</div><div class="l">HR макс</div></div>
        <div class="metric"><div class="v">${detail.avg_cadence ?? '—'}</div><div class="l">кад. ср</div></div>
        <div class="metric"><div class="v">${detail.max_cadence ?? '—'}</div><div class="l">кад. макс</div></div>
        <div class="metric"><div class="v">${Math.round(detail.ascent_m || 0)}</div><div class="l">м набор</div></div>
        <div class="metric"><div class="v">${detail.calories ?? '—'}</div><div class="l">ккал</div></div>
      </div>
      ${detail.cadence_source ? `<div class="sub">Каденция: ${detail.cadence_source === 'stryd' ? 'нагрудный ремень (Stryd)' : 'часы'}</div>` : ''}
    </div>`;

  return stats + zoneContent(detail) + chartContent(detail) + splitsContent(detail);
}

/* Время в зонах пульса атлета. */
function zoneContent(detail) {
  const minutes = detail.hr_zone_minutes || {};
  const total = Object.values(minutes).reduce((sum, value) => sum + value, 0);
  if (!total) return '';

  const rows = Object.entries(minutes).map(([zone, value]) => {
    const share = (value / total) * 100;
    return `<div class="zone-row">
        <span class="zone-name">${escapeHtml(zone)}</span>
        <span class="zone-bar"><i style="width:${share.toFixed(1)}%"></i></span>
        <span class="zone-value">${value.toFixed(0)} мин · ${share.toFixed(0)}%</span>
      </div>`;
  }).join('');

  return `<div class="card">
      <h3>Время в зонах пульса</h3>
      <div class="zones">${rows}</div>
    </div>`;
}

/* Графики: пульс, каденция, мощность. */
function chartContent(detail) {
  const series = detail.series || {};
  const blocks = [];
  if (series.hr && series.hr.length > 1) {
    blocks.push(chartCard('Пульс', series.hr, 'bpm', '#7aa2ff', true));
  }
  if (series.cadence && series.cadence.length > 1) {
    blocks.push(chartCard('Каденция', series.cadence, 'spm', '#5cd6c0', false));
  }
  if (series.power && series.power.length > 1) {
    blocks.push(chartCard('Мощность', series.power, 'Вт', '#ff9b6a', false));
  }
  return blocks.join('');
}

/* Один график: SVG с линией, подписями осей и зонами пульса. */
function chartCard(title, series, unit, color, withZones) {
  const plotWidth = 300;
  const height = 110;
  const gutter = 26;          // слева — подписи значений
  const bottom = 14;          // снизу — подписи времени
  const values = series.map((point) => point[1]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);

  const points = toPoints(series, plotWidth, height, minValue, maxValue);
  const bands = withZones
    ? zoneBands(hrZones(), values, plotWidth, height, minValue, maxValue)
    : [];
  const yLabels = axisLabels(minValue, maxValue, 4);
  const xLabels = timeLabels(series, 4);

  const bandHtml = bands.map((band) =>
    `<rect x="${gutter}" y="${band.y.toFixed(1)}" width="${plotWidth}" height="${band.height.toFixed(1)}" fill="${band.color}"/>`).join('');

  const yHtml = yLabels.map((label, index) => {
    const y = (index / Math.max(1, yLabels.length - 1)) * height;
    return `<line x1="${gutter}" y1="${y.toFixed(1)}" x2="${gutter + plotWidth}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.05)"/>
      <text x="${gutter - 4}" y="${(y + 3).toFixed(1)}" class="c-label c-right">${label}</text>`;
  }).join('');

  const xHtml = xLabels.map((label) => {
    const x = gutter + (label.x / 100) * plotWidth;
    const anchor = label.x <= 0 ? 'start' : label.x >= 100 ? 'end' : 'middle';
    return `<text x="${x.toFixed(1)}" y="${height + bottom - 2}" class="c-label c-mid" text-anchor="${anchor}">${label.text}</text>`;
  }).join('');

  return `<div class="card">
      <h3>${escapeHtml(title)} <span class="c-unit">${escapeHtml(unit)}</span></h3>
      <svg class="chart" viewBox="0 0 ${gutter + plotWidth} ${height + bottom}">
        ${bandHtml}
        ${yHtml}
        <polyline points="${polyline(points)}" fill="none" stroke="${color}" stroke-width="1.6"
          stroke-linejoin="round" stroke-linecap="round"
          transform="translate(${gutter} 0)"/>
        ${xHtml}
      </svg>
      <div class="c-foot">мин</div>
    </div>`;
}

/* Отрезки тренировки. */
function splitsContent(detail) {
  const splits = detail.splits || [];
  if (!splits.length) return '';

  const rows = splits.map((split) => {
    const speed = split.avg_speed_mps ? `${formatPace(split.avg_speed_mps)}/км` : '—';
    return `<li>
        <div class="row">
          <span>${split.index}</span>
          <span class="num">${((split.distance_m || 0) / 1000).toFixed(2)} км · ${speed}</span>
        </div>
        <div class="sub">
          ${formatDuration(split.duration_s / 60)}
          ${split.avg_hr ? ` · HR ${split.avg_hr}` : ''}
          ${split.avg_cadence ? ` · ${split.avg_cadence} spm` : ''}
          ${split.ascent_m ? ` · +${Math.round(split.ascent_m)} м` : ''}
        </div>
      </li>`;
  }).join('');

  return `<div class="card">
      <h3>Отрезки · ${splits.length}</h3>
      <ul class="plain">${rows}</ul>
    </div>`;
}

/* Темп из скорости: м/с → мин/км. */
function formatPace(mps) {
  if (!mps) return '—';
  const secPerKm = 1000 / mps;
  const minutes = Math.floor(secPerKm / 60);
  const seconds = Math.round(secPerKm % 60);
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/* ------------------------------------------------------------------ детали */

/* Детали тренировки — по эталонному plan-wN.html.
 * Сеты собираются обратно: шаги с одинаковым group — один блок,
 * шаги с round — повторы внутри блока.
 */
/* Тренировка недели — размещённая или нет.
 *
 * Размещённая тренировка лежит в `week.workouts`. Непривязанная — там
 * же (у неё просто нет дня), но клиент получает её ещё и в
 * `week.unplaced`, где у неё свой `id` — id запроса.
 *
 * Поэтому ищем дважды: по id тренировки и по id запроса.
 */
function findWorkout(workoutId) {
  const week = state.week || {};
  const byId = (week.workouts || []).find((w) => w.id === workoutId);
  if (byId) return byId;
  const unplaced = (week.unplaced || []).find((u) => u.id === workoutId);
  if (unplaced) return unplacedWorkout(unplaced);
  return null;
}

/* Непривязанная тренировка — в виде тренировки.
 *
 * У висяка в `week.unplaced` уже есть всё, что нужно для экрана
 * деталей: название, объект, шаги. Приводим к тому же виду, что и
 * размещённая тренировка, чтобы экран деталей был один.
 *
 * **id — разные вещи.** id висяка — это id запроса (`r-...`), а у
 * тренировки свой (`w-...`). Экран деталей должен знать id тренировки:
 * по нему удаляют. Поэтому берём `workout_id` из ответа, а если его
 * нет (старые данные) — ищем тренировку по запросу.
 */
function unplacedWorkout(u) {
  const week = state.week || {};
  const own = (week.workouts || []).find((w) => w.request_id === u.id);
  return {
    id: u.workout_id || (own ? own.id : u.id),
    request_id: u.request_id || u.id,
    sport: u.sport,
    kind: u.kind,
    focus: u.focus,
    objective: u.objective || {},
    location: u.location || '',
    time: u.time || '',
    steps: u.steps || [],
    duration_min: u.duration_min,
    distance_m: u.distance_m || 0,
    status: 'planned',
    rationale: u.rationale || '',
    actual_id: null,
  };
}

function showWorkout(workoutId, skipMetrics = false) {
  /* Тренировка ищется и среди размещённых, и среди непривязанных.
   *
   * Дефект, который это ловит: по висяку нельзя было посмотреть
   * детали — он был просто строкой «Лёгкий бег, 46 мин». Теперь у
   * непривязанной тренировки есть свой экран, как у размещённой.
   */
  const workout = findWorkout(workoutId);
  if (!workout) {
    cardHost.innerHTML = '<div class="card">Тренировка не найдена</div>';
    return;
  }

  const objective = workout.objective || {};
  const title = objective.name || workout.kind;
  const stepCount = (workout.steps || []).length;
  const meta = [];
  if (workout.location) meta.push(`<span class="meta-item">📍 ${escapeHtml(workout.location)}</span>`);
  if (workout.focus) meta.push(`<span class="meta-item focus-pill focus-${escapeHtml(workout.focus)}">${escapeHtml(workout.focus)}</span>`);
  if (objective.subkind) meta.push(`<span class="meta-item">${escapeHtml(objective.subkind)}</span>`);

  const session = objective.session || {};
  let goalHtml = '';
  if (session.session_goal) {
    goalHtml = `<div class="goal-block">
        <div class="lbl">Цель сессии</div>
        <div>${escapeHtml(session.session_goal)}</div>
        ${session.label ? `<div class="goal-row"><span class="meta-item">${escapeHtml(session.label)}</span></div>` : ''}
      </div>`;
  }

  let rationaleHtml = '';
  if (workout.rationale) {
    rationaleHtml = `<div class="rationale">
        <div class="lbl">Зачем</div>
        ${escapeHtml(workout.rationale)}
      </div>`;
  }

  const inventory = objective.inventory || [];
  const invHtml = inventory.length
    ? `<div class="inventory">
        <div class="lbl">Что нужно</div>
        ${inventory.map((i) => `<div class="inv-item"><span class="ico">${escapeHtml(i.icon || '•')}</span><span>${escapeHtml(i.name || '')}</span></div>`).join('')}
      </div>`
    : '';

  /* Непривязанная тренировка — с кнопкой привязки.
   *
   * Кнопка «привязать» на экране деталей ведёт себя ровно как раньше:
   * открывает выбор окна недели. Здесь она нужна, чтобы можно было
   * посмотреть детали и сразу решить, куда поставить.
   */
  const placed = objective.day !== undefined && objective.day !== null
    && objective.day !== '';
  const bindBlock = placed
    ? ''
    : `<div class="bind-block">
        <div class="lbl">Тренировка не привязана</div>
        <div class="hint">Выбери окно недели — и тренировка встанет на это время.</div>
        <button class="action primary" data-bind-pick="${escapeHtml(workout.request_id || workout.id)}">
          Привязать к окну
        </button>
        ${slotPickerFor(workout.request_id || workout.id, workout.sport)}
      </div>`;

  const linkedActual = workout.actual_id
    ? state.actual.find((a) => a.id === workout.actual_id)
    : null;

  /* Факт привязывают к размещённой тренировке: у непривязанной нет
   * дня, и связывать с ней активность — путаница. */
  const actualBlock = linkedActual
    ? `<div class="actual-block linked" data-detail="${escapeHtml(linkedActual.id)}">
        <div class="lbl">Выполнено</div>
        <div class="line">
          <b>${((linkedActual.distance_m || 0) / 1000).toFixed(1)} км</b> ·
          ${formatDuration(linkedActual.duration_min)}
          ${linkedActual.hr_avg ? ` · HR ${linkedActual.hr_avg}` : ''}
        </div>
        <div class="when">${linkedActual.date} · ${escapeHtml(SPORT_NAME[linkedActual.sport] || linkedActual.sport)}</div>
        ${workoutMetricsBlock(linkedActual.id)}
        <div class="actual-actions">
          <button class="action" data-detail="${escapeHtml(linkedActual.id)}">Разбор тренировки →</button>
          <button class="action secondary" data-unlink="${escapeHtml(workout.id)}">Отвязать</button>
        </div>
      </div>`
    : placed
      ? `<div class="actual-block empty">
        <div class="lbl">Факт не привязан</div>
        <div class="facts-hint">Кандидаты из Garmin — нажми, чтобы связать:</div>
        <div class="facts">${factList(workout)}</div>
        <button class="action secondary" id="pull">Загрузить факт из Garmin</button>
      </div>`
      : '';

  /* Кнопка удаления — только пока неделя не активна.
   *
   * В активной неделе план уже исполняется: удалять тренировку из неё
   * нельзя (и сервер не даст). В proposed-неделе план ещё можно
   * переделать — это и есть время убрать лишнее.
   */
  const weekStatus = state.week ? (state.week.status || 'proposed') : 'proposed';
  const removeBlock = weekStatus === 'proposed'
    ? `<div class="card"><div class="chead">Удалить тренировку</div>
        <p class="lead">Пока неделя не активирована, тренировку можно
        убрать из плана.</p>
        <button class="action secondary" data-remove-workout="${escapeHtml(workout.id)}">
          Удалить тренировку
        </button>
      </div>`
    : '';

  /* Подзаголовок: день, время, длительность и километраж.
   *
   * Километраж плана — рядом с длительностью: в карточке тренировки
   * это главное, чего не хватало. Плана по факту тут нет: показан
   * именно план, чтобы видеть, сколько метров заложено.
   */
  const planKm = plannedKm(workout);
  const subtitle = `${placed ? `${escapeHtml(objective.day || '')} · ` : 'не привязано · '}${escapeHtml(workout.time || '')}${workout.time ? ' · ' : ''}${formatDuration(workout.duration_min)}${planKm ? ` · ${escapeHtml(planKm)}` : ''}`;

  cardHost.innerHTML = `<div class="card detail">
      <div class="card-header">
        <div class="headline">
          <span class="kind-ico">${KIND_ICON[workout.sport] || '🎯'}</span>
          <span class="name">${escapeHtml(title)}</span>
        </div>
        <span class="tag kind-${escapeHtml(workout.sport)}">${stepCount} ${plural(stepCount, 'шаг', 'шага', 'шагов')}</span>
      </div>
      <div class="subtitle">${subtitle}</div>
      ${meta.length ? `<div class="meta-row">${meta.join('')}</div>` : ''}
      ${goalHtml}
      ${rationaleHtml}
      ${invHtml}
      <h3>Структура тренировки</h3>
      ${structureHtml(workout)}
      ${bindBlock}
      ${actualBlock}
      ${removeBlock}
    </div>
    <div id="detail-block"></div>`;

  state.openWorkoutId = workoutId;
  state.detailId = null;
  cardWrap.classList.remove('hidden');
  detailWrap.classList.add('hidden');
  picker.classList.add('hidden');

  const slug = slotSlug(workout);
  try {
    // Запись в историю: если мы уже на уровне тренировки — заменяем
    // текущую (переходим между тренировками), иначе добавляем новую.
    // Разбор поверх тренировки — отдельная запись, см. showDetail.
    const onWorkoutLevel = history.state
      && history.state.page === 'detail'
      && !history.state.actual;
    if (onWorkoutLevel) {
      history.replaceState({page: 'detail', slot: workoutId}, '', '#' + slug);
    } else {
      history.pushState({page: 'detail', slot: workoutId}, '', '#' + slug);
    }
  } catch (error) {
    history.replaceState(null, '', '#' + slug);
  }
  render();
  window.scrollTo(0, 0);

  /* Метрики формы грузятся после отрисовки: карточка появляется сразу,
   * а метрики — как ответят. Иначе открытие тренировки ждало бы сеть. */
  if (linkedActual && !skipMetrics) {
    loadWorkoutMetrics(linkedActual.id);
  }
}

/* Идентификатор тренировки для адреса — латиницей: кириллица в URL
 * ломает кодировку и делит ссылку на части.
 */
function slotSlug(workout) {
  const objective = workout.objective || {};
  const day = objective.day || '';
  const name = (objective.name || workout.kind || '')
    .toLowerCase()
    .replace(/[^a-zа-яё0-9]+/gi, '-')
    .replace(/^-|-$/g, '');
  return `w${workout.season_week || state.seasonWeek}-${day}-${name}`;
}

/* Шапка на экране деталей: кнопка «назад» + название. */
function detailBar(title, day) {
  return `<button class="back" id="backBtn">←</button>
    <div class="title">
      <div>${escapeHtml(title)}</div>
      ${day ? `<div class="sub">${escapeHtml(day)}</div>` : ''}
    </div>`;
}

/* Обратно к списку. */
function showPicker() {
  state.openWorkoutId = null;
  state.detailId = null;
  /* Выбор окна закрывается вместе с экраном: список окон висит и на
   * экране недели, и в деталях тренировки, и без сброса оба остаются
   * в DOM сразу. */
  state.pickUnplaced = null;
  cardWrap.classList.add('hidden');
  detailWrap.classList.add('hidden');
  picker.classList.remove('hidden');
  if (window.location.hash) {
    try { history.replaceState(history.state, '', ' '); } catch (error) { /* нет */ }
  }
  renderScreen();
  bar.innerHTML = chromeBar();
  // Меню перерисовываем отдельно: в нём подсветка активного раздела,
  // а сам экран её не трогает. Полный render() тут лишний — он
  // перерисовывает ещё и меню целиком.
  renderNav();
  // Прокрутка вверх — только если мы не наверху: лишний scrollTo
  // вызывает пересчёт раскладки и задерживает кадр.
  if (window.scrollY > 0) window.scrollTo(0, 0);
}

/* Нижнее меню: пять разделов, активный подсвечен. */
function renderNav() {
  nav.innerHTML = SCREENS
    .map(([id, title, ico]) =>
      `<button class="${state.screen === id ? 'on' : ''}" data-screen="${id}">
        <span class="ico">${ico}</span><span class="lbl">${title}</span>
      </button>`)
    .join('');
}

/* Назад с экрана разбора — к тренировке, из которой пришли.
 *
 * Уровни вложенности: неделя → тренировка → разбор. Назад убирает
 * верхний уровень, а не сбрасывает всё сразу.
 */
function showDetailBack() {
  const cameFromDetail = history.state && history.state.actual;
  state.detailId = null;

  if (cameFromDetail) {
    // Возврат — шаг назад по истории. Запись с разбором должна из
    // истории уйти, а не перезаписаться: иначе второй «назад» не
    // дойдёт до списка. Экраном займётся popstate.
    history.back();
    return;
  }

  detailWrap.classList.add('hidden');
  if (state.openWorkoutId) {
    showWorkout(state.openWorkoutId);
    return;
  }
  showPicker();
}

/* Структура тренировки: сеты собираются обратно из group/round. */
function structureHtml(workout) {
  const steps = workout.steps || [];
  if (!steps.length) return '<div class="empty">Нет структуры</div>';

  const blocks = groupBlocks(steps);
  return `<ol class="structure-list">${blocks.map(renderBlock).join('')}</ol>`;
}

/* Один блок структуры: одиночный шаг, сет или упражнение. */
function renderBlock(block) {
  const steps = block.steps;

  // Упражнения ОФП: у каждого шага есть название и повторы в focus_value.
  // Проверка именно по обоим полям: у разминки focus_value пустой.
  if (isExerciseBlock(steps)) {
    return `<li class="step step-ofp">
        <div class="step-head"><span class="step-phase">${escapeHtml(block.group || 'main')}</span></div>
        <ol class="ex-list">${steps.map((s, i) => `
          <li class="ex-item">
            <div class="ex-num">${i + 1}</div>
            <div class="ex-content">
              <div class="ex-name">${escapeHtml(s.label || '')}</div>
              <div class="ex-reps">${escapeHtml(s.focus_value.reps)}</div>
              ${s.notes ? `<div class="ex-why">${escapeHtml(s.notes)}</div>` : ''}
            </div>
          </li>`).join('')}
        </ol>
      </li>`;
  }

  // Сет интервалов: у шагов есть round — это повторы
  if (isSetBlock(steps)) {
    const reps = setReps(steps);
    // Название сета часто уже содержит число повторов («3×800м»).
    // Повторять его рядом — значит сказать одно и то же дважды.
    const repsTag = nameHasReps(block.group)
      ? ''
      : `<span class="step-reps">${repsLabel(reps)}</span>`;
    return `<li class="step step-set">
        <div class="step-head">
          <span class="step-phase">${escapeHtml(block.group || 'сет')}</span>
          ${repsTag}
        </div>
        <ol class="step-sublist">${steps.map(renderSubStep).join('')}</ol>
      </li>`;
  }

  // Одиночный шаг
  //
  // Шагов без названия группы (`group: null`) в тренировке может быть
  // несколько: разминка, работа, заминка у контрольной точки. Раньше
  // такой блок показывал только первый шаг, а остальные молча
  // пропадали: структура «3 шага» выглядела как «1 шаг».
  //
  // Название группы показываем, когда оно есть: у шага с `group`
  // (например «6×100м через 100м») иначе пропадает само название
  // серии, и читатель видит просто «0.1 км @ 3:35/км» без понятного,
  // что это за работа.
  if (steps.length > 1) {
    return `<li class="step">
        ${steps.map(renderSubStep).join('')}
      </li>`;
  }
  if (block.group) {
    return `<li class="step">
        <div class="step-head">
          <span class="step-phase">${escapeHtml(block.group)}</span>
        </div>
        ${renderSubStep(steps[0])}
      </li>`;
  }
  return `<li class="step">${renderSubStep(steps[0])}</li>`;
}

/* Шаг внутри: зона, роль, объём, пульс, темп. */
function renderSubStep(step) {
  const fv = step.focus_value || {};
  const zone = fv.zone ? `<span class="step-zone">${escapeHtml(fv.zone)}</span>` : '';
  const role = step.label || ROLE_RU[step.role] || step.role;

  let value = '';
  if (step.target_type === 'distance') {
    value = `<span class="step-dur">${(step.target_value / 1000).toFixed(1)} км</span>`;
  } else if (step.target_type === 'reps') {
    value = `<span class="step-reps">× ${step.target_value}</span>`;
  } else {
    value = `<span class="step-dur">${Math.round(step.duration_min)} мин</span>`;
  }

  const hr = fv.hr_target ? ` <span class="step-extra">HR ${fv.hr_target}</span>` : '';
  const pace = fv.pace_min_per_km ? ` <span class="step-extra">@ ${escapeHtml(fv.pace_min_per_km)}/км</span>` : '';

  /* Что шаг делает — своими словами.
   *
   * Раньше описание шага бралось из `notes`, а у шагов планировщика
   * `notes` пустой: в карточке тренировки вместо содержимого стояло
   * пустое место, и тренировку нельзя было понять, не открыв шаги
   * вручную.
   *
   * Здесь важно не повторять то, что уже показано: объём и темп уже
   * стоят в строке шага, поэтому `stepAbout` сообщает только то, чего
   * в строке нет, — например, пульс.
   */
  const about = stepAbout(step);

  return `<div class="step-head">${zone}
      <span class="step-phase">${escapeHtml(role)}</span> ${value}${hr}${pace}
      ${about ? `<span class="step-about">${escapeHtml(about)}</span>` : ''}
    </div>`;
}

/* Что в шаге не видно из строки шага: пульс и повторы ОФП. */
function stepAbout(step) {
  const fv = step.focus_value || {};
  if (fv.ofp) {
    return fv.reps ? `ОФП · ${fv.reps}` : 'ОФП';
  }
  const bits = [];
  if (fv.hr_target) bits.push(`пульс до ${fv.hr_target}`);
  if (step.target_type === 'reps') {
    bits.push(`${Math.round(step.target_value)} повт.`);
  }
  return bits.join(' · ');
}

/* ------------------------------------------------------------------ данные */

/* Какую неделю показывать на главном экране.
 *
 * Правило: главный экран — это **сейчас**, а не архив. Если открытая
 * неделя закрыта и она прошлая (текущая уже началась), показываем
 * текущую. Остатки закрытой недели на главном экране — шум: неделя
 * закончилась, её итоги живут в «Сезоне».
 *
 * Исключения:
 *   - неделю выбрали руками в «Сезоне» — человек сам её открыл;
 *   - текущая неделя ещё не началась по календарю (currentWeek неизвестен).
 *
 * Если текущая неделя не запланирована — открывается пустое состояние
 * с кнопкой «Спланировать неделю». Это и есть нужный вид: неделя
 * началась, плана у неё нет.
 */
function pickSeasonWeek(saved, currentWeek, weeks) {
  if (!currentWeek) return saved;
  if (!saved) return currentWeek;
  if (saved === currentWeek) return currentWeek;

  // Неделя выбрана руками — не трогаем.
  if (state.seasonWeekPinned) return saved;

  // Статус открытой недели: закрытая ли она.
  const record = (weeks || []).find((w) => w.season_week === saved);
  const status = record ? record.status : null;
  if (status !== 'closed') return saved;

  // Закрытая неделя, которая ещё идёт или прошла — показываем текущую.
  // Если текущая ещё не началась (saved < current), это прошлая: тоже
  // переключаем.
  return currentWeek;
}

/* Отпустить ручной выбор недели.
 *
 * Закрепление нужно только пока человек смотрит прошлую неделю. Как
 * только он действует с текущей (планирует, активирует, закрывает),
 * приложение возвращается к жизни по календарю.
 */
function unpinSeasonWeek() {
  if (!state.seasonWeekPinned) return;
  state.seasonWeekPinned = false;
  localStorage.removeItem('coach-app-week-pinned');
}

async function load() {
  // Записи в кэш — в фоне: экран не должен ждать IndexedDB.
  const cacheWrites = [];
  try {
    // Запросы идут параллельно, а не по очереди: пять последовательных
    // round-trip'ов на телефоне — это и есть «несколько секунд».
    const [snapshot, weeks, current, seasonPlan, slotsResponse, ftp] = await Promise.all([
      api.getSnapshot(),
      api.getWeeks().catch(() => null),
      api.getCurrentWeek().catch(() => null),
      api.getSeason().catch(() => null),
      api.getSlots().catch(() => null),
      api.getFtpEstimate().catch(() => null),
    ]);

    state.version = snapshot.version;
    state.season = snapshot.data.season;
    state.athlete = snapshot.data.athlete;
    state.stale = false;
    state.cachedAt = Date.now();
    // Кэш пишем после отрисовки: IndexedDB на телефоне медленный, и
    // ждать его перед показом экрана незачем.
    cacheWrites.push(putCache('snapshot', snapshot.data, snapshot.version));

    // Окна тренировок — часть среды, повторяются каждую неделю.
    if (slotsResponse) {
      state.slots = slotsResponse.data.slots || [];
      cacheWrites.push(putCache('slots', state.slots, snapshot.version));
    } else {
      state.slots = (await getCache('slots'))?.value || [];
    }

    if (ftp) {
      state.ftpEstimate = ftp.data;
    } else {
      state.ftpEstimate = state.ftpEstimate || null;
    }

    if (seasonPlan) {
      state.seasonPlan = seasonPlan.data;
      cacheWrites.push(putCache('season-plan', seasonPlan.data, snapshot.version));
    } else {
      state.seasonPlan = (await getCache('season-plan'))?.value || null;
    }

    if (weeks) {
      state.weeks = weeks.data.weeks || [];
      cacheWrites.push(putCache('weeks', state.weeks, snapshot.version));
    } else {
      state.weeks = state.weeks || [];
    }

    // Текущая неделя — по дате на сервере: клиент не знает про начало сезона.
    if (current) {
      state.currentWeek = current.data.season_week;
    }
    state.seasonWeek = pickSeasonWeek(state.seasonWeek, state.currentWeek,
                                      state.weeks);
    const seasonWeek = state.seasonWeek;

    // недели может не быть — это не ошибка, а пустое состояние
    const [week, actual] = await Promise.all([
      api.getWeek(seasonWeek).catch((error) => {
        if (error.code === 'not_found') return null;
        throw error;
      }),
      api.getActual(seasonWeek).catch(() => null),
    ]);

    if (week) {
      state.week = week.data;
      // Метрики формы — с неделей: сервер считает их из разборов.
      state.metrics = week.data.metrics || null;
      // Доступен ли разбор текста в тренировку: без ключа модели
      // кнопку «Предложить тренировку» не показываем.
      state.composeAvailable = week.data.compose_available !== false;
      cacheWrites.push(putCache(`week:${seasonWeek}`, week.data, snapshot.version));
    } else {
      state.week = null;
      state.metrics = null;
    }

    if (actual) {
      state.actual = actual.data.sessions || [];
      cacheWrites.push(putCache(`actual:${seasonWeek}`, state.actual, snapshot.version));
    } else {
      state.actual = (await getCache(`actual:${seasonWeek}`))?.value || [];
    }

    state.summary = state.week ? state.week.summary : null;
  } catch (error) {
    await loadFromCache();
    showMessage('Сервер недоступен — показан последний известный снимок', 'error');
  }
  render();
  // Кэш дописываем после отрисовки, ошибки в нём ничего не ломают.
  await Promise.allSettled(cacheWrites);
}

async function loadFromCache() {
  // Каждый кэш читается независимо: отсутствие одного не должно ронять
  // остальные — показываем то, что есть.
  try {
    const snapshot = await getCache('snapshot');
    if (snapshot) {
      state.season = snapshot.value.season;
      state.athlete = snapshot.value.athlete;
      state.version = snapshot.version;
      state.cachedAt = snapshot.cached_at;
    }
  } catch (error) { /* кэша нет — пустое состояние */ }

  try {
    const week = await getCache(`week:${state.seasonWeek}`);
    if (week) {
      state.week = week.value;
      state.summary = week.value.summary;
    }
  } catch (error) { /* недели в кэше нет */ }

  try {
    const actual = await getCache(`actual:${state.seasonWeek}`);
    if (actual) state.actual = actual.value;
  } catch (error) { /* факта в кэше нет */ }

  try {
    const weeks = await getCache('weeks');
    if (weeks) state.weeks = weeks.value;
  } catch (error) { /* списка недель в кэше нет */ }

  try {
    const slots = await getCache('slots');
    if (slots) state.slots = slots.value;
  } catch (error) { /* окон тренировок в кэше нет */ }

  state.stale = true;
}

/* Ошибка, из-за которой команда бессмысленна: повтор не поможет.
 * Такую команду убираем из очереди, иначе она блокирует все следующие.
 */
function isPermanentError(error) {
  return error.code === 'degraded'
    || error.code === 'invalid_command'
    || error.code === 'not_found';
}

async function flushOutbox() {
  const queued = await pendingCommands();
  state.outbox = queued;
  if (!queued.length) return;

  for (const command of queued) {
    try {
      await api.sendCommand(command);
      await removeCommand(command.id);
    } catch (error) {
      await markAttempt(command.id, error.message);
      if (isPermanentError(error)) {
        // Команда не выполнима — убираем, чтобы не блокировать очередь.
        await removeCommand(command.id);
        showMessage(error.message, 'error');
        continue;
      }
      if (error.code === 'version_conflict') {
        // Состояние изменилось на сервере: перечитываем и повторяем
        // команду с новой версией. Плашка тут не помогала — она висела
        // и ничего не делала.
        await load();
        command.expected_version = state.version;
        await api.sendCommand(command);
        await removeCommand(command.id);
        continue;
      }
      if (!error.code) {
        showMessage('Нет связи с сервером — команда ждёт в очереди', 'error');
      } else {
        showMessage(error.message, 'error');
      }
      break;
    }
  }
  state.outbox = await pendingCommands();
}

/* ------------------------------------------------------------------ события */

document.addEventListener('click', async (event) => {
  const target = event.target;
  // Ищем ближайшего предка с признаком: тап может прийти по иконке или
  // подписи внутри кнопки — тогда target не сама кнопка.
  const closest = (selector) => (target.closest ? target.closest(selector) : null);

  // Тап по плашке сообщения — закрыть её
  if (closest('#msg')) {
    state.message = null;
    if (state.messageTimer) clearTimeout(state.messageTimer);
    state.messageTimer = null;
    render();
    return;
  }

  const slot = closest('[data-slot]');

  // Тап по плашке тренировки — открыть детали
  if (slot) {
    showWorkout(slot.dataset.slot);
    return;
  }

  // Кнопка «назад»: убираем верхний уровень вложенности
  if (closest('#backBtn')) {
    if (state.detailId) {
      // с разбора — к тренировке
      showDetailBack();
    } else if (state.screen === 'compose') {
      // с разбора тренировки — к неделе
      state.screen = 'week';
      showPicker();
    } else if (history.state && history.state.page === 'detail') {
      history.back();
    } else {
      showPicker();
    }
    return;
  }

  // Переход в раздел: тап по кнопке, её иконке или подписи.
  const screen = closest('[data-screen]');
  if (screen) {
    state.screen = screen.dataset.screen;
    // showPicker() уже перерисовывает экран и шапку — второй render()
    // делал ту же работу дважды.
    showPicker();
    return;
  }

  // Неделя макро-плана: открыть неделю. Только те, что уже заведены:
  // у будущей недели нет ни плана, ни факта — открывать нечего.
  const seasonWeek = closest('[data-week]');
  if (seasonWeek) {
    await openSeasonWeek(Number(seasonWeek.dataset.week));
    return;
  }

  if (closest('#refresh')) {
    await load();
    await flushOutbox();
    render();
    // Код тоже мог устареть: телефон по обычному HTTP держит браузерный
    // кэш, и перезагрузка данных новую версию клиента не принесёт.
    await updateShell();
    return;
  }

  /* Вернуться на текущую неделю.
   *
   * Снимаем закрепление: дальше приложение живёт по календарю, и
   * закрытая прошлая неделя снова уступает место текущей.
   */
  if (closest('#go-current')) {
    const current = state.currentWeek;
    if (!current) return;
    unpinSeasonWeek();
    state.seasonWeek = current;
    localStorage.setItem('coach-app-week', String(current));
    state.screen = 'week';
    await load();
    showPicker();
    return;
  }

  // Тап по факту — связать с открытой тренировкой
  const fact = closest('[data-actual]');
  if (fact) {
    await linkActual(fact.dataset.actual, fact.dataset.workout);
    return;
  }

  /* Тап по висяку — открыть детали тренировки.
   *
   * То же, что тап по размещённой: отдельный экран со структурой,
   * шагами и кнопкой привязки. Из списка висяков детали были
   * недоступны — а решить, куда поставить, не видя состава тренировки,
   * невозможно.
   */
  const unplaced = closest('[data-unplaced]');
  if (unplaced) {
    showWorkout(unplaced.dataset.unplaced);
    return;
  }

  /* Кнопка «привязать» — открыть выбор окна. Поведение прежнее.
   *
   * На экране деталей выбор окон появляется под кнопкой, поэтому
   * детали перерисовываются: список окон живёт внутри них. */
  const bindPick = closest('[data-bind-pick]');
  if (bindPick) {
    state.pickUnplaced = bindPick.dataset.bindPick;
    if (state.openWorkoutId) {
      showWorkout(state.openWorkoutId);
    } else {
      render();
    }
    return;
  }

  // Выбор окна для висяка: привязать тренировку вручную.
  const bind = closest('[data-bind-slot]');
  if (bind) {
    await placeUnplaced(bind.dataset.bindRequest, bind.dataset.bindSlot,
                        bind.dataset.bindStart, bind.dataset.bindDay);
    return;
  }

  // Отвязать факт от тренировки
  const unlink = closest('[data-unlink]');
  if (unlink) {
    await unlinkActual(unlink.dataset.unlink);
    return;
  }

  // Разбор тренировки: загрузить детали или разобрать FIT
  const detail = closest('[data-detail]');
  if (detail) {
    await loadDetail(detail.dataset.detail);
    return;
  }

  if (closest('#pull')) {
    showMessage('Загружаю факт из Garmin…');
    render();
    await queueCommand({
      id: `pull-${Date.now()}`,
      type: 'pull_fact',
      args: { season_week: state.seasonWeek },
      reason: 'загрузка факта из Garmin',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    // Сообщение ставим ПОСЛЕ load(): load() больше не стирает плашку,
    // а ошибка команды должна её пережить.
    if (state.messageKind !== 'error') {
      showMessage('Факт загружен');
    }
    render();
    // Вернуться в детали, если тренировка была открыта.
    if (state.week && state.openWorkoutId) showWorkout(state.openWorkoutId);
    return;
  }

  if (closest('#plan-week')) {
    await runWeekCommand('propose_week', 'Планирую неделю…',
      'Неделя спланирована — проверь и активируй');
    return;
  }

  /* Спланировать следующую неделю — до закрытия текущей.
   *
   * Команда уходит на неделю после текущей: туда и возвращаемся. */
  if (closest('#plan-next-week')) {
    const next = nextPlannableWeek();
    if (!next) return;
    const macro = macroWeekOf(next);
    /* Уже предложена — открываем её, а не предлагаем заново. Так же,
     * как делала большая карточка: «Открыть неделю» вместо
     * «Спланировать». */
    if (macro && macro.status) {
      await openSeasonWeek(next);
      return;
    }
    showMessage('Планирую следующую неделю…');
    state.busy = true;
    render();
    // Планирование — действие с текущей неделей: ручной выбор отпускаем.
    unpinSeasonWeek();
    await queueCommand({
      id: `propose-${next}-${Date.now()}`,
      type: 'propose_week',
      args: {season_week: next},
      reason: 'планирование следующей недели',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    state.busy = false;
    if (state.messageKind === 'error' && state.message) {
      render();
      return;
    }
    showMessage('Следующая неделя спланирована');
    render();
    return;
  }

  if (closest('#set-ftp')) {
    const ftp = Number(closest('#set-ftp').dataset.ftp);
    if (!ftp) return;
    showMessage('Записываю порог мощности…');
    state.busy = true;
    render();
    await queueCommand({
      id: `ftp-${ftp}-${Date.now()}`,
      type: 'update_athlete',
      args: {ftp_w: ftp},
      reason: 'порог мощности для расчёта нагрузки',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    state.busy = false;
    if (state.messageKind === 'error' && state.message) {
      render();
      return;
    }
    showMessage(`Порог мощности: ${ftp} Вт`);
    render();
    return;
  }

  /* Открыть экран разбора тренировки. */
  if (closest('#compose-open')) {
    state.screen = 'compose';
    state.compose = null;
    state.composeError = null;
    state.composeText = '';
    showPicker();
    return;
  }

  /* Пример пожелания — подставляется в поле. */
  const example = closest('[data-compose-example]');
  if (example) {
    state.composeText = example.dataset.composeExample || '';
    state.compose = null;
    state.composeError = null;
    render();
    return;
  }

  /* Разобрать текст в структуру. */
  if (closest('#compose-run')) {
    const field = document.getElementById('compose-text');
    const text = (field ? field.value : state.composeText) || '';
    if (!text.trim()) {
      state.composeError = 'Опиши тренировку — пустым текстом её не сделать';
      render();
      return;
    }
    state.composeText = text;
    state.composeBusy = true;
    state.composeError = null;
    render();
    try {
      const response = await api.composeWorkout(text, state.seasonWeek);
      state.compose = response.data;
    } catch (error) {
      state.compose = null;
      state.composeError = error.message || 'не удалось разобрать текст';
    }
    state.composeBusy = false;
    render();
    return;
  }

  /* Вернуться к тексту: разбор можно поправить. */
  if (closest('#compose-reset')) {
    state.compose = null;
    state.composeError = null;
    render();
    return;
  }

  /* Добавить разобранную тренировку в неделю — висяком. */
  if (closest('#compose-add')) {
    const c = state.compose;
    if (!c) return;
    const intents = (c.steps || []).map((s) => {
      const step = s.step || {};
      return {
        role: step.role,
        sport: step.sport,
        target_type: step.target_type,
        target_value: step.target_value,
        intent: (step.focus_value || {}).intent || 'easy',
        label: step.label || '',
        reps: 1,
        rest_type: 'distance',
        rest_value: 0,
      };
    });
    showMessage('Добавляю тренировку в неделю…');
    state.busy = true;
    render();
    await queueCommand({
      id: `compose-add-${Date.now()}`,
      type: 'add_composed_workout',
      args: {
        season_week: state.seasonWeek,
        name: c.name,
        assumptions: c.assumptions || [],
        source_text: c.source_text || state.composeText,
        intents,
      },
      reason: 'тренировка из твоего описания',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    state.busy = false;
    state.screen = 'week';
    state.compose = null;
    if (state.messageKind === 'error' && state.message) {
      render();
      return;
    }
    showMessage('Тренировка добавлена — привяжи её к окну');
    render();
    return;
  }

  /* Удалить тренировку. Кнопка есть только у неактивной недели. */
  if (closest('[data-remove-workout]')) {
    const workoutId = closest('[data-remove-workout]').dataset.removeWorkout;
    showMessage('Удаляю тренировку…');
    state.busy = true;
    render();
    await queueCommand({
      id: `remove-workout-${Date.now()}`,
      type: 'remove_workout',
      args: {season_week: state.seasonWeek, workout_id: workoutId},
      reason: 'удаление тренировки из недели',
      expected_version: state.version,
    });
    await flushOutbox();
    await load();
    state.busy = false;
    if (state.messageKind === 'error' && state.message) {
      render();
      return;
    }
    // Тренировки больше нет — карточка закрывается, иначе она продолжит
    // показывать удалённую тренировку. Возврат — к списку недели.
    showPicker();
    showMessage('Тренировка удалена');
    render();
    return;
  }

  if (closest('#propose')) {
    await runWeekCommand('propose_week', 'Предлагаю неделю заново…',
      'Неделя предложена заново');
    return;
  }

  if (closest('#activate')) {
    await runWeekCommand('activate_week', 'Активирую неделю…',
      'Неделя активна');
    return;
  }

  if (closest('#close')) {
    await runWeekCommand('close_week', 'Закрываю неделю…', 'Неделя закрыта');
    return;
  }
});

/* Команда недели: propose → activate → close.
 *
 * Ошибка команды — не пустота на экране: плашка с текстом отказа должна
 * пережить перезагрузку данных, иначе нажатие выглядит как «ничего не
 * произошло».
 */
async function runWeekCommand(type, pendingText, doneText) {
  showMessage(pendingText);
  state.busy = true;
  render();
  // Команда идёт по текущей неделе — ручной выбор больше не нужен:
  // снимаем «закрепление», чтобы приложение дальше жило по календарю.
  unpinSeasonWeek();
  await queueCommand({
    id: `${type}-${Date.now()}`,
    type,
    args: {season_week: state.seasonWeek},
    reason: type,
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.busy = false;
  // Плашка с ошибкой пережила перезагрузку — оставляем её.
  if (state.messageKind === 'error' && state.message) {
    render();
    return;
  }
  showMessage(doneText);
  render();
}

/* Кнопка «назад» на телефоне — убрать верхний уровень вложенности.
 *
 * Уровни: неделя → тренировка → разбор. Свайп назад из разбора
 * возвращает к тренировке, из тренировки — к списку.
 */
window.addEventListener('popstate', (event) => {
  const current = event.state;
  if (current && current.page === 'detail' && current.actual) {
    // Вперёд: открыт разбор.
    state.detailId = current.actual;
    detailWrap.classList.remove('hidden');
    cardWrap.classList.add('hidden');
    picker.classList.add('hidden');
    detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
    render();
    return;
  }
  if (current && current.page === 'detail') {
    // Назад с разбора: мы на уровне тренировки.
    state.detailId = null;
    detailWrap.classList.add('hidden');
    showWorkout(current.slot);
    return;
  }
  showPicker();
});

/* Разбор тренировки: сначала пробуем готовый, иначе разбираем FIT. */
async function loadDetail(actualId) {
  // Экран разбора открываем сразу — пока грузится, он пустой.
  showDetail(actualId);
  showMessage('Загружаю разбор…');
  render();
  try {
    const detail = await api.getDetail(actualId);
    state.detail = detail.data;
    state.message = null;
    detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
    render();
    return;
  } catch (error) {
    if (error.code !== 'not_found') {
      showMessage(error.message, 'error');
      render();
      return;
    }
  }

  // Разбора нет — разбираем FIT через Garmin
  showMessage('Разбираю FIT-файл…');
  render();
  await queueCommand({
    id: `fit-${actualId}-${Date.now()}`,
    type: 'import_fit',
    args: { actual_id: actualId },
    reason: 'разбор тренировки из Garmin',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  try {
    const detail = await api.getDetail(actualId);
    state.detail = detail.data;
  } catch (error) {
    showMessage('Разбор не удался', 'error');
  }
  detailHost.innerHTML = `<div class="card detail-screen">${screenDetail()}</div>`;
  render();
}
/* Связать факт с тренировкой. */
async function linkActual(actualId, workoutId) {
  showMessage('Связываю…');
  render();
  await queueCommand({
    id: `link-${actualId}-${workoutId}-${Date.now()}`,
    type: 'link_actual',
    args: { season_week: state.seasonWeek, actual_id: actualId, workout_id: workoutId },
    reason: 'связь факта с тренировкой',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  // Вернуться в детали тренировки: после загрузки экран сбрасывается.
  if (state.week && workoutId) showWorkout(workoutId);
}

/* Отвязать факт от тренировки. */
async function unlinkActual(workoutId) {
  showMessage('Отвязываю…');
  render();
  await queueCommand({
    id: `unlink-${workoutId}-${Date.now()}`,
    type: 'unlink_actual',
    args: { season_week: state.seasonWeek, workout_id: workoutId },
    reason: 'разрыв связи факта с тренировкой',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.message = null;
  render();
  if (state.week && workoutId) showWorkout(workoutId);
}

/* Привязать висяка к окну — вручную.
 *
 * Решение о времени тренировки принимает пользователь, поэтому здесь
 * нет проверок: окно может быть занято, тренировка может в него не
 * влезать — это его решение, и сервер его выполнит.
 */
async function placeUnplaced(requestId, slotId, start, day) {
  showMessage('Привязываю…');
  render();
  await queueCommand({
    id: `place-${requestId}-${slotId}-${Date.now()}`,
    type: 'place_unplaced',
    args: {
      season_week: state.seasonWeek,
      request_id: requestId,
      slot_id: slotId,
      start: start || '',
      day: day === '' || day === undefined ? null : Number(day),
    },
    reason: 'ручная привязка тренировки к окну',
    expected_version: state.version,
  });
  await flushOutbox();
  await load();
  state.pickUnplaced = null;
  state.message = null;
  render();
}

async function queueCommand(command) {
  await enqueue(command);
  state.outbox = await pendingCommands();
}

/* ------------------------------------------------------------------ утилиты */

/* Компактный формат для метрик: «6,2 ч» вместо «6 ч 14 мин». */
function formatHours(minutes) {
  if (!minutes) return '0';
  const hours = minutes / 60;
  return hours >= 10 ? hours.toFixed(0) : hours.toFixed(1);
}

function formatDuration(minutes) {
  if (!minutes) return '0 мин';
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (!h) return `${m} мин`;
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

/* Русское склонение: 1 шаг, 2 шага, 5 шагов. */
function plural(count, one, few, many) {
  const n = Math.abs(Math.round(count)) % 100;
  const n1 = n % 10;
  if (n > 10 && n < 20) return many;
  if (n1 > 1 && n1 < 5) return few;
  if (n1 === 1) return one;
  return many;
}

function timeOf(timestamp) {
  if (!timestamp) return '—';
  return new Date(timestamp).toLocaleTimeString('ru-RU', {
    hour: '2-digit', minute: '2-digit',
  });
}

function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

window.addEventListener('online', () => {
  state.online = true;
  flushOutbox().then(load);
});

window.addEventListener('offline', () => {
  state.online = false;
  render();
});

api.subscribe((event) => {
  // Событие с той же версией — перезагрузка не нужна. Раньше сравнение
  // шло с версией сезона, а клиент держит глобальную: расхождение было
  // постоянным, и каждое событие перезагружало данные целиком.
  if (event.version === state.version) return;
  // Пока идёт команда — не перезагружать: перезагрузка сбрасывает
  // плашку «Закрываю неделю…» и экран мигает.
  if (state.busy) return;
  load();
});

/* Обновить оболочку приложения: код, а не только данные.
 *
 * Три уровня устаревания, и каждый надо пройти:
 *
 * 1. **Service worker** — на HTTPS он держит оболочку в своём кэше.
 *    `registration.update()` проверяет новую версию `sw.js`; если версия
 *    изменилась, новый worker встанет и заберёт свежие файлы.
 * 2. **Браузерный кэш** — на обычном HTTP service worker не работает, и
 *    телефон держит `app.js` сам. `reload()` с `cache: 'reload'` просит
 *    сервер заново.
 * 3. **Открытая страница** — старый `app.js` уже в памяти, поэтому после
 *    перезагрузки файлов страницу надо переоткрыть.
 *
 * Без этого «обновить» обновляет только цифры, а правка в коде на экране
 * не появляется — и выглядит как «приложение сломано».
 */
async function updateShell() {
  try {
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.getRegistration();
      if (registration) {
        await registration.update();
        // Ждём, пока новый worker возьмёт управление, и только потом
        // переоткрываем страницу: иначе загрузится старый кэш.
        await navigator.serviceWorker.ready;
      }
    }
  } catch (error) {
    /* service worker недоступен — идём дальше, браузерный кэш обновим */
  }

  try {
    // Просим сервер заново, минуя кэш браузера.
    const url = new URL(location.href);
    url.searchParams.set('v', String(Date.now()));
    location.replace(url.toString());
  } catch (error) {
    /* переход не удался — показываем старую версию, это не ошибка */
  }
}

/* Service worker: оболочка кэшируется, приложение открывается без сети. */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {
    /* без service worker приложение всё равно работает, только без офлайна */
  });
}

load().then(flushOutbox).then(render).then(() => {
  // Если в адресе есть хэш тренировки — открыть её (ссылка на детали).
  const hash = window.location.hash.replace('#', '');
  if (hash && state.week) {
    const match = (state.week.workouts || []).find((w) => slotSlug(w) === hash);
    if (match) {
      history.replaceState({page: 'init'}, '', ' ');
      showWorkout(match.id);
    }
  }
});
