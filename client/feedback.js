/* Субъективная оценка тренировки: поля формы и маркеры.
 *
 * Чистые функции: без DOM, без сети, без состояния. Поэтому их можно
 * проверять тестами — `node --test tests/client/`.
 *
 * **Вид работы задаёт форму.** Вид приходит с сервера (`feedback_kind`
 * в ответе недели): сервер разбирает `kind` и шаги, а клиент по виду
 * работы решает, какие поля показывать. Разбирать `kind` на клиенте
 * нельзя: у интервальной тренировки, собранной из текста, `kind` =
 * `composed`, и по нему её не отличить от лёгкой.
 *
 * **Одно нажатие на ответ.** Все поля выбираются чипсами: без
 * выпадающих списков и без ввода цифр. В форме оценки человек не
 * печатает — он жмёт.
 *
 * **Значение по умолчанию — «Фон».** В обычный день человек ничего не
 * выбирает, и лишний тап не должен быть ценой заполнения формы.
 */

/* Виды работы — те же коды, что у сервера. */
export const KIND_EASY = 'easy';
export const KIND_QUALITY = 'quality';
export const KIND_OTHER = 'other';

/* Поля формы.
 *
 * `body_status` — общий для всех беговых тренировок: состояние икр и
 * поясницы. Остальные зависят от вида работы.
 */
export const FIELDS = {
  body_status: {
    label: 'Тело (икры / поясница)',
    options: [
      {value: 0, label: 'Фон'},
      {value: -1, label: 'Тянет'},
      {value: -2, label: 'Ломает'},
    ],
  },
  easy_feel: {
    label: 'Общее ощущение',
    options: [
      {value: 1, label: 'Ноги свежие'},
      {value: 0, label: 'Устали, но нормально'},
      {value: -1, label: 'Еле вышел'},
    ],
  },
  rep1_mental: {
    label: '1-й отрезок — психология',
    options: [
      {value: 'fresh', label: 'Свежо'},
      {value: 'heavy', label: 'Тяжело заходить'},
    ],
  },
  rep2_physical: {
    label: '2-й отрезок — физика',
    options: [
      {value: 'opened_up', label: 'Раскрылся'},
      {value: 'wooden', label: 'Деревянный'},
    ],
  },
  want_one_more: {
    label: 'Финиш: хотел бы сделать ещё 1?',
    options: [
      {value: 'yes', label: 'Да'},
      {value: 'enough', label: 'Хватило'},
      {value: 'definitely_no', label: 'Точно нет'},
    ],
  },
};

/* Поля по виду работы.
 *
 * Лёгкая и длинная работа спрашивает одно: как чувствовались ноги.
 * Интервальная и пороговая — динамику внутри работы: как зашёл, как
 * разогрелся, хватило ли.
 */
export function feedbackFields(kind) {
  if (kind === KIND_EASY) {
    return ['body_status', 'easy_feel'];
  }
  if (kind === KIND_QUALITY) {
    return ['body_status', 'rep1_mental', 'rep2_physical', 'want_one_more'];
  }
  return [];
}

/* Поле комментария — для всех видов работы, но само по себе оценки не
 * составляет: человек может написать «новые кроссовки» и не ставить
 * ни одного чипа. */
export const COMMENT_FIELD = 'comment';

/* Значения, которые сервер уже отверг — их не показываем выбранными.
 *
 * Присланное значение, которого нет среди вариантов, — мусор: показывать
 * его отмеченным нельзя, но и терять молча не надо. */
export function normaliseValues(raw) {
  const values = {};
  if (!raw || typeof raw !== 'object') return values;
  for (const [key, field] of Object.entries(FIELDS)) {
    const value = raw[key];
    if (value === undefined || value === null) continue;
    if (field.options.some((option) => option.value === value)) {
      values[key] = value;
    }
  }
  if (typeof raw[COMMENT_FIELD] === 'string') {
    values[COMMENT_FIELD] = raw[COMMENT_FIELD];
  }
  return values;
}

/* Оценка пустая — только значения по умолчанию и без комментария.
 *
 * «Фон» (0) — это значение, а не отсутствие: человек его выбрал.
 * Пустая оценка — это когда не выбрано ничего и комментарий пуст.
 */
export function isEmpty(values) {
  if (!values) return true;
  for (const [key, value] of Object.entries(values)) {
    if (key === COMMENT_FIELD) {
      if (String(value).trim()) return false;
      continue;
    }
    if (value !== undefined && value !== null) {
      /* «Фон» — выбранное значение, поэтому не пусто. */
      return false;
    }
  }
  return true;
}

/* Маркеры оценки — для плашки тренировки в списке недели.
 *
 * Короткие, чтобы картина недели читалась с одного взгляда: «Тело -1»,
 * «Ноги +1», «Ещё 1: Хватило». «Фон» не показывается: это отсутствие
 * проблемы, а не новость, и такой маркер висел бы на каждой тренировке.
 */
export function feedbackBadges(values) {
  if (!values) return [];
  const badges = [];

  const body = values.body_status;
  if (typeof body === 'number' && body !== 0) {
    badges.push(`Тело ${body}`);
  }

  const feel = values.easy_feel;
  if (typeof feel === 'number') {
    badges.push(feel > 0 ? 'Ноги +1' : (feel < 0 ? 'Ноги -1' : 'Ноги 0'));
  }

  const want = values.want_one_more;
  if (want !== undefined && want !== null) {
    const field = FIELDS.want_one_more;
    const option = field.options.find((item) => item.value === want);
    if (option) badges.push(`Ещё 1: ${option.label}`);
  }

  return badges;
}
