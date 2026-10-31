"""Предложение недели: макро + правила методики → неделя для активации.

Команда `propose_week` собирает неделю заново по правилам. Планировщик
(`WeekPlanner`) умеет раскладывать рецепты по слотам, но не знает, что
взять из текущей недели: макро (объём по видам спорта) живёт в самой неделе.

Поэтому здесь — тонкий слой поверх планировщика: достать макро из текущей
недели, добавить к бегу качественную работу по правилам Дэниэлса, собрать
неделю заново.

**Длинный бег** — по правилу Дэниэлса: 25 % недельного километража или
1,5 часа, что меньше. Остальное время — лёгкий бег.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.entities import Season, Slot, Week, Workout
from app.domain.enums import Sport, WeekStatus
from app.services.week_lifecycle import TransitionError
from app.services.week_planner import WeeklyTarget, WeekPlanInput, WeekPlanner

# Длинный бег: 25 % недельного километража или 1,5 часа, что меньше.
LONG_FRACTION = 0.25
LONG_MAX_MIN = 90


@dataclass
class MacroVolume:
    """Объём недели по виду спорта — из текущей недели."""

    minutes: dict[Sport, int] = None  # type: ignore[assignment]
    run_km: float = 0.0
    long_min: int = 0

    def __post_init__(self) -> None:
        if self.minutes is None:
            self.minutes = {}


def macro_from_week(week: Week) -> MacroVolume:
    """Макро текущей недели: минуты по видам спорта и километраж бега.

    Километраж бега берётся из `load_target.distance_m` — это цель недели,
    заданная макро, а не факт пробега.
    """
    minutes: dict[Sport, int] = {}
    long_min = 0
    for workout in week.workouts:
        minutes[workout.sport] = minutes.get(workout.sport, 0) + int(workout.duration_min)
        # Вид длинного бега в плане пайплайна — `long_Z2`: регистр и
        # подчёркивание не несут смысла, несёт смысл слово `long`.
        if workout.kind.lower().startswith("long"):
            long_min += int(workout.duration_min)
    run_km = float(week.load_target.get("distance_m", 0.0)) / 1000.0
    return MacroVolume(minutes=minutes, run_km=run_km, long_min=long_min)

def weeks_to_race(season: Season, week_start: date) -> int:
    """Сколько недель до старта — по дате гонки плана.

    Этот срок определяет, как программа Дэниэлса раскладывается по фазам.
    """
    for plan in season.plans:
        days = (plan.goal.race_date - week_start).days
        if days >= 0:
            return days // 7
    return 0


def build_targets(macro: MacroVolume, week: Week) -> list[WeeklyTarget]:
    """Запросы недели: бег по правилам Дэниэлса.

    Не беговые виды спорта (велосипед, плавание, ОФП) сюда не входят: их
    структуру задаёт не Дэниэлс, а макро и среда, поэтому они переносятся
    из текущей недели как есть — иначе они попали бы в план дважды.
    """
    targets: list[WeeklyTarget] = []

    run_minutes = macro.minutes.get(Sport.RUN, 0)
    if run_minutes > 0:
        long_min = macro.long_min
        if not long_min and macro.run_km > 0:
            # Длинный бег по правилу: 25 % недельного километража или 1,5 ч.
            long_min = int(min(macro.run_km * LONG_FRACTION, LONG_MAX_MIN))
        targets.append(WeeklyTarget(
            sport=Sport.RUN,
            duration_min=run_minutes,
            focus=week.focus or "",
            kind="easy",
            long_min=long_min or None,
        ))
    return targets


def propose_week(season: Season,
                 current: Week,
                 planner: WeekPlanner,
                 ) -> Week:
    """Собрать неделю по правилам методики.

    `current` — текущая неделя: из неё берётся макро (объём по видам спорта).
    Качественная работа по бегу — из правил Дэниэлса, по номеру недели
    программы для этого срока до старта.

    I21/I40: повторный propose полностью заменяет содержимое proposed-недели.
    I23: закрытая неделя не меняется — предлагать её заново нельзя.
    """
    if current.status is not WeekStatus.PROPOSED:
        raise TransitionError(
            f"предложить заново можно только proposed-неделю, а не {current.status}"
        )

    macro = macro_from_week(current)
    targets = build_targets(macro, current)
    if not targets:
        raise ValueError("в неделе нет объёма — нечего предлагать")

    slots = list(season.slots)
    planned = planner.build_from(WeekPlanInput(
        season_week=current.season_week,
        week_start=current.start,
        week_end=current.end,
        targets=targets,
        slots=slots,
        weeks_to_race=weeks_to_race(season, current.start),
        run_km=macro.run_km,
        plan_id=current.plan_id,
    ))

    # Не беговые тренировки переносим из текущей недели: правила Дэниэлса
    # задают бег, а вел, плавание и ОФП — это из макро и среды.
    others = [w for w in current.workouts if w.sport is not Sport.RUN]
    if others:
        planned = _append_others(planned, others, slots)

    # Недельная цель пересчитывается по итоговой неделе: перенесённые
    # тренировки тоже тренировки, а число сессий показывается клиенту.
    planned.load_target = planner.load_target_for_week(planned)

    planned.validate()
    return planned


def _append_others(week: Week, others: list[Workout],
                   slots: list[Slot]) -> Week:
    """Добавить не беговые тренировки текущей недели к собранной.

    Запросы и размещения создаются под них, чтобы инвариант «каждый Workout
    вырос из Request» не нарушился.

    Размещение ищется по времени тренировки среди слотов недели: слот должен
    существовать, иначе висяк — тренировка без места. Выдуманный id слота
    означал бы, что тренировка поставлена туда, куда бегать нельзя.
    """
    from app.domain.entities import Assignment, Request

    requests = list(week.requests)
    assignments = list(week.assignments)
    workouts = list(week.workouts)
    unplaced = list(week.unplaced)

    by_time: dict[str, list[Slot]] = {}
    for week_slot in slots:
        by_time.setdefault(week_slot.start, []).append(week_slot)

    taken = {a.slot_id for a in assignments}
    for index, workout in enumerate(others):
        request_id = f"r{week.season_week}-keep-{index + 1}"
        requests.append(Request(
            id=request_id,
            sport=workout.sport,
            kind=workout.kind,
            focus=workout.focus,
            duration_min=int(workout.duration_min),
        ))
        slot = _slot_for(workout, by_time, taken)
        if slot is not None:
            taken.add(slot.id)
            assignments.append(Assignment(
                request_id=request_id,
                slot_id=slot.id,
                start=slot.start,
                duration_min=int(workout.duration_min),
            ))
        else:
            # Места нет — висяк: решение пользователя.
            unplaced.append(Request(
                id=request_id,
                sport=workout.sport,
                kind=workout.kind,
                focus=workout.focus,
                duration_min=int(workout.duration_min),
            ))

        workouts.append(Workout(
            id=f"w-{request_id}",
            request_id=request_id,
            sport=workout.sport,
            kind=workout.kind,
            focus=workout.focus,
            objective=workout.objective,
            equipment_ids=workout.equipment_ids,
            location=workout.location,
            time=workout.time,
            steps=workout.steps,
            duration_min=workout.duration_min,
            priority=workout.priority,
            rationale=workout.rationale,
        ))

    return week.copy_with(
        requests=requests,
        assignments=assignments,
        unplaced=unplaced,
        workouts=workouts,
    )


def _slot_for(workout: Workout, by_time: dict[str, list[Slot]],
              taken: set[str]) -> Slot | None:
    """Слот для тренировки — по времени начала и виду спорта.

    None — подходящего слота нет: тренировка остаётся висяком.
    """
    if not workout.time:
        return None
    for slot in by_time.get(workout.time, []):
        if slot.id in taken:
            continue
        if slot.capacity_min < int(workout.duration_min):
            continue
        if workout.sport in slot.forbidden_sports:
            continue
        return slot
    return None


__all__ = [
    "MacroVolume",
    "build_targets",
    "macro_from_week",
    "propose_week",
    "weeks_to_race",
]
