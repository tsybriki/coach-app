/* Субъективная оценка тренировки: поля формы и маркеры.
 *
 * ТЗ (Кирилл, 26.11.2026): форма быстрой оценки при привязке факта.
 * Поля зависят от вида работы, всё выбирается в одно нажатие, у
 * состояния тела есть значение по умолчанию.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';

import {
  COMMENT_FIELD,
  FIELDS,
  KIND_EASY,
  KIND_OTHER,
  KIND_QUALITY,
  feedbackBadges,
  feedbackFields,
  isEmpty,
  normaliseValues,
} from '../../client/feedback.js';

/* ------------------------------------------------------------------ поля */

test('лёгкая работа: тело и общее ощущение', () => {
  assert.deepEqual(feedbackFields(KIND_EASY),
    ['body_status', 'easy_feel']);
});

test('качественная работа: тело и три поля динамики', () => {
  assert.deepEqual(feedbackFields(KIND_QUALITY),
    ['body_status', 'rep1_mental', 'rep2_physical', 'want_one_more']);
});

test('не-беговая работа: полей нет', () => {
  assert.deepEqual(feedbackFields(KIND_OTHER), []);
});

test('неизвестный вид работы: полей нет', () => {
  /* Лучше не спросить, чем спросить не о том. */
  assert.deepEqual(feedbackFields('что-то'), []);
});

test('каждое поле имеет подпись и варианты', () => {
  for (const key of Object.keys(FIELDS)) {
    const field = FIELDS[key];
    assert.ok(field.label, `у поля ${key} нет подписи`);
    assert.ok(field.options.length >= 2, `у поля ${key} мало вариантов`);
    for (const option of field.options) {
      assert.ok(option.label, `у варианта ${option.value} поля ${key} нет подписи`);
    }
  }
});

test('состояние тела по умолчанию — «Фон»', () => {
  /* В обычный день человек ничего не выбирает, и лишний тап не должен
   * быть ценой заполнения формы. */
  const field = FIELDS.body_status;
  const zero = field.options.find((o) => o.value === 0);
  assert.ok(zero, 'в состоянии тела нет значения 0');
  assert.equal(zero.label, 'Фон');
});

/* ------------------------------------------------------------------ значения */

test('мусорные значения отбрасываются', () => {
  const values = normaliseValues({
    body_status: 'пять',
    easy_feel: 99,
    rep1_mental: 'нету',
    want_one_more: 'yes',
  });
  assert.equal(values.body_status, undefined);
  assert.equal(values.easy_feel, undefined);
  assert.equal(values.rep1_mental, undefined);
  assert.equal(values.want_one_more, 'yes');
});

test('корректные значения сохраняются', () => {
  const values = normaliseValues({
    body_status: -1,
    easy_feel: 0,
    rep1_mental: 'fresh',
    rep2_physical: 'wooden',
    want_one_more: 'definitely_no',
    comment: 'ветер',
  });
  assert.equal(values.body_status, -1);
  assert.equal(values.easy_feel, 0);
  assert.equal(values.rep1_mental, 'fresh');
  assert.equal(values.rep2_physical, 'wooden');
  assert.equal(values.want_one_more, 'definitely_no');
  assert.equal(values.comment, 'ветер');
});

test('пустое и не-объект — пустые значения', () => {
  assert.deepEqual(normaliseValues(null), {});
  assert.deepEqual(normaliseValues('мусор'), {});
  assert.deepEqual(normaliseValues(undefined), {});
});

/* ------------------------------------------------------------------ пустота */

test('оценка без выбора — пустая', () => {
  assert.ok(isEmpty({}));
  assert.ok(isEmpty(null));
  assert.ok(isEmpty({body_status: undefined}));
});

test('«Фон» — не пустая оценка', () => {
  /* Человек выбрал «Фон» — это ответ, а не отсутствие ответа. */
  assert.ok(!isEmpty({body_status: 0}));
});

test('комментарий без чипов — не пустая оценка', () => {
  assert.ok(!isEmpty({comment: 'новые кроссовки'}));
});

test('пустой комментарий не делает оценку непустой', () => {
  assert.ok(isEmpty({comment: '   '}));
});

/* ------------------------------------------------------------------ маркеры */

test('маркер состояния тела', () => {
  assert.deepEqual(feedbackBadges({body_status: -1}), ['Тело -1']);
  assert.deepEqual(feedbackBadges({body_status: -2}), ['Тело -2']);
});

test('«Фон» маркера не даёт', () => {
  /* Отсутствие проблемы — не новость, и маркер висел бы на каждой
   * тренировке недели. */
  assert.deepEqual(feedbackBadges({body_status: 0}), []);
});

test('маркер ощущения', () => {
  assert.deepEqual(feedbackBadges({easy_feel: 1}), ['Ноги +1']);
  assert.deepEqual(feedbackBadges({easy_feel: 0}), ['Ноги 0']);
  assert.deepEqual(feedbackBadges({easy_feel: -1}), ['Ноги -1']);
});

test('маркер финиша', () => {
  assert.deepEqual(feedbackBadges({want_one_more: 'enough'}),
    ['Ещё 1: Хватило']);
  assert.deepEqual(feedbackBadges({want_one_more: 'yes'}),
    ['Ещё 1: Да']);
});

test('маркеры идут в фиксированном порядке', () => {
  assert.deepEqual(
    feedbackBadges({want_one_more: 'enough', easy_feel: -1, body_status: -2}),
    ['Тело -2', 'Ноги -1', 'Ещё 1: Хватило']);
});

test('без оценки маркеров нет', () => {
  assert.deepEqual(feedbackBadges(null), []);
  assert.deepEqual(feedbackBadges({}), []);
});

test('мусорный код финиша не даёт маркера', () => {
  assert.deepEqual(feedbackBadges({want_one_more: 'может быть'}), []);
});

/* ------------------------------------------------------------------ комментарий */

test('комментарий — отдельное поле, не чип', () => {
  assert.equal(COMMENT_FIELD, 'comment');
  assert.ok(!Object.keys(FIELDS).includes(COMMENT_FIELD));
});
