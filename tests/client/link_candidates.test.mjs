/**
 * Тесты клиента: сортировка кандидатов для связывания.
 *
 * Проверяются чистые функции — без DOM и без сети. Запуск:
 *     node --test tests/client/
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { linkCandidates, sportRank } from '../../client/link.js';

function session(id, date, sport, linkedWorkoutId = null) {
  return {
    id,
    date,
    sport,
    linked_workout_id: linkedWorkoutId,
    duration_min: 60,
    distance_m: 10000,
  };
}

test('бег идёт первым, остальные виды спорта — по алфавиту', () => {
  assert.equal(sportRank('run'), 0);
  assert.equal(sportRank('bike'), 1);
  assert.equal(sportRank('swim'), 1);
  assert.equal(sportRank('ofp'), 1);
});

test('кандидаты — только тот же вид спорта, что и тренировка', () => {
  const workout = { id: 'w1', sport: 'run' };
  const sessions = [
    session('a', '2026-10-26', 'run'),
    session('b', '2026-10-27', 'bike'),
    session('c', '2026-10-28', 'swim'),
    session('d', '2026-10-29', 'run'),
  ];

  const result = linkCandidates(workout, sessions);
  assert.deepEqual(result.map((s) => s.id), ['a', 'd']);
});

test('внутри вида спорта — по дате, от самой старой', () => {
  const workout = { id: 'w1', sport: 'run' };
  const sessions = [
    session('c', '2026-10-28', 'run'),
    session('a', '2026-10-26', 'run'),
    session('b', '2026-10-27', 'run'),
  ];

  const result = linkCandidates(workout, sessions);
  assert.deepEqual(result.map((s) => s.id), ['a', 'b', 'c']);
});

test('занятые факты — не кандидаты', () => {
  const workout = { id: 'w1', sport: 'run' };
  const sessions = [
    session('a', '2026-10-26', 'run'),
    session('b', '2026-10-27', 'run', 'w-other'),
  ];

  const result = linkCandidates(workout, sessions);
  assert.deepEqual(result.map((s) => s.id), ['a']);
});

test('нет кандидатов — пустой список, не ошибка', () => {
  const workout = { id: 'w1', sport: 'swim' };
  const sessions = [session('a', '2026-10-26', 'run')];

  assert.deepEqual(linkCandidates(workout, sessions), []);
});
