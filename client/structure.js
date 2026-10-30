/* Структура тренировки: шаги, сеты, упражнения.
 *
 * Чистые функции без DOM — их можно проверять тестами
 * (`node --test tests/client/`).
 */

/* Название сета уже содержит число повторов?
 *
 * В плане сет назван «3×800м с прогрессией 4:15 → 3:50», и число повторов
 * равно трём. Если продублировать «× 3» рядом с названием, одно и то же
 * сказано дважды. Возвращает true, если название уже содержит «N×».
 */
export function nameHasReps(name) {
  if (!name) return false;
  return /\d+\s*[×x]\s*\d*/i.test(name);
}

/* Число повторов сета — из плана, а не из числа шагов: в шагах есть и
 * отдых, поэтому шагов вдвое больше, чем повторов.
 */
export function setReps(steps) {
  if (!steps || !steps.length) return 0;
  const fromPlan = steps[0].focus_value?.set_reps;
  if (fromPlan) return Number(fromPlan);
  return steps.length;
}

/* Блок структуры: одиночный шаг, сет интервалов или упражнения ОФП.
 *
 * Блок начинается, если сменилась группа или тип шага (упражнение / нет).
 */
export function groupBlocks(steps) {
  const blocks = [];
  let current = null;

  for (const step of steps || []) {
    const isExercise = Boolean(step.label && step.focus_value?.reps);
    if (current && (step.group !== current.group || isExercise !== current.isExercise)) {
      current = {group: step.group, steps: [], isExercise};
      blocks.push(current);
    } else if (!current) {
      current = {group: step.group, steps: [], isExercise};
      blocks.push(current);
    }
    current.steps.push(step);
  }
  return blocks;
}

/* Являются ли шаги упражнениями ОФП: у каждого есть название и повторы. */
export function isExerciseBlock(steps) {
  return steps.length > 1 && steps.every((s) => s.label && s.focus_value?.reps);
}

/* Являются ли шаги сетом интервалов: у каждого есть номер повтора. */
export function isSetBlock(steps) {
  return steps.length > 1
    && steps.every((s) => s.round !== null && s.round !== undefined);
}

/* Человекочитаемое число повторов: «3 повтора» / «1 повтор». */
export function repsLabel(reps) {
  if (reps === 1) return '1 повтор';
  const mod10 = reps % 10;
  const mod100 = reps % 100;
  if (mod10 === 1 && mod100 !== 11) return `${reps} повтор`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${reps} повтора`;
  return `${reps} повторов`;
}
