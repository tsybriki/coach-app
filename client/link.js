/* Отбор кандидатов для связывания факта с тренировкой.
 *
 * Чистые функции: без DOM, без сети, без состояния. Поэтому их можно
 * проверять тестами — `node --test tests/client/`.
 */

/* Порядок видов спорта: бег первым, остальные по алфавиту. */
export function sportRank(sport) {
  return sport === 'run' ? 0 : 1;
}

/* Виды спорта делятся на группы: внутри группы вид не важен.
 *
 * Силовая группа — ОФП, силовая и HIIT: в Garmin всё это записывается как
 * «hiit» (typeKey) или «strength_training», и в плане может быть помечено
 * любым из трёх. Связать их между собой — можно, это одна и та же работа.
 * Бег, вел и плавание — точное совпадение: велосипед с бегом не связать.
 */
const GROUP = {
  ofp: 'strength',
  strength: 'strength',
  hiit: 'strength',
};

/* Подходит ли вид факта к виду тренировки. */
export function sportCompatible(workoutSport, actualSport) {
  const groupA = GROUP[workoutSport];
  const groupB = GROUP[actualSport];
  if (groupA || groupB) return groupA === groupB;
  return workoutSport === actualSport;
}

/* Кандидаты для связывания с тренировкой.
 *
 * Только тот же вид спорта: беговой тренировке — беговые активности,
 * велосипед с бегом не связать. Занятые факты не кандидаты.
 * Порядок: спорт (бег первым), внутри — дата, от самой старой.
 */
export function linkCandidates(workout, sessions) {
  return sessions
    .filter((a) => sportCompatible(workout.sport, a.sport) && !a.linked_workout_id)
    .sort((a, b) => {
      // Сначала вид спорта (бег первым), внутри группы — по дате,
      // от самой старой. Дата — последний ключ: иначе порядок внутри
      // группы (hiit/strength/ofp) скачет по датам.
      if (sportRank(a.sport) !== sportRank(b.sport)) {
        return sportRank(a.sport) - sportRank(b.sport);
      }
      const byDate = String(a.date).localeCompare(String(b.date));
      if (byDate !== 0) return byDate;
      return a.sport.localeCompare(b.sport);
    });
}
