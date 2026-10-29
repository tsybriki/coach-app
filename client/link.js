/* Отбор кандидатов для связывания факта с тренировкой.
 *
 * Чистые функции: без DOM, без сети, без состояния. Поэтому их можно
 * проверять тестами — `node --test tests/client/`.
 */

/* Порядок видов спорта: бег первым, остальные по алфавиту. */
export function sportRank(sport) {
  return sport === 'run' ? 0 : 1;
}

/* Кандидаты для связывания с тренировкой.
 *
 * Только тот же вид спорта: беговой тренировке — беговые активности,
 * велосипед с бегом не связать. Занятые факты не кандидаты.
 * Порядок: спорт (бег первым), внутри — дата, от самой старой.
 */
export function linkCandidates(workout, sessions) {
  const sport = workout.sport;
  return sessions
    .filter((a) => a.sport === sport && !a.linked_workout_id)
    .sort((a, b) => {
      if (sportRank(a.sport) !== sportRank(b.sport)) {
        return sportRank(a.sport) - sportRank(b.sport);
      }
      if (a.sport !== b.sport) return a.sport.localeCompare(b.sport);
      return String(a.date).localeCompare(String(b.date));
    });
}
