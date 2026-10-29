/**
 * Тесты клиента: сортировка кандидатов для связывания.
 *
 * Проверяются чистые функции — без DOM и без сети. Запуск:
 *     node --test tests/client/
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import { linkCandidates, sportRank, sportCompatible } from '../../client/link.js';

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

test('ОФП-тренировке подходит факт HIIT и силовая', () => {
  const workout = { id: 'w1', sport: 'ofp' };
  const sessions = [
    session('a', '2026-10-26', 'hiit'),
    session('b', '2026-10-27', 'strength'),
    session('c', '2026-10-28', 'run'),
  ];

  const result = linkCandidates(workout, sessions);
  assert.deepEqual(result.map((s) => s.id), ['a', 'b']);
});

test('HIIT-тренировке подходят HIIT, силовая и ОФП — одна группа', () => {
  const workout = { id: 'w1', sport: 'hiit' };
  const sessions = [
    session('a', '2026-10-26', 'hiit'),
    session('b', '2026-10-27', 'strength'),
    session('c', '2026-10-28', 'ofp'),
    session('d', '2026-10-29', 'bike'),
  ];

  const result = linkCandidates(workout, sessions);
  // Велосипед не подходит; остальные — по дате.
  assert.deepEqual(result.map((s) => s.id), ['a', 'b', 'c']);
});

test('внутри силовой группы порядок — по дате, а не по виду спорта', () => {
  const workout = { id: 'w1', sport: 'ofp' };
  const sessions = [
    session('c', '2026-10-26', 'ofp'),
    session('a', '2026-10-26', 'hiit'),
    session('b', '2026-10-27', 'strength'),
  ];

  const result = linkCandidates(workout, sessions);
  assert.deepEqual(result.map((s) => s.id), ['a', 'c', 'b']);
});

test('силовая группа: HIIT, силовая и ОФП взаимозаменяемы', () => {
  assert.equal(sportCompatible('hiit', 'strength'), true);
  assert.equal(sportCompatible('hiit', 'ofp'), true);
  assert.equal(sportCompatible('strength', 'ofp'), true);
  assert.equal(sportCompatible('ofp', 'hiit'), true);
});

test('бег не совместим с ОФП и HIIT', () => {
  assert.equal(sportCompatible('run', 'run'), true);
  assert.equal(sportCompatible('run', 'hiit'), false);
  assert.equal(sportCompatible('run', 'ofp'), false);
});

test('велосипед не совместим с бегом', () => {
  assert.equal(sportCompatible('bike', 'bike'), true);
  assert.equal(sportCompatible('bike', 'run'), false);
});
