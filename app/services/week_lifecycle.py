"""Сценарии над состоянием.

Сервисы связывают правила домена и контракты портов. Они не знают, где лежат
данные: только через порты.

Жизненный цикл недели: `proposed → active → closed`. Все переходы — команды
пользователя, ничего не инициируется само.
"""
from __future__ import annotations

from datetime import date

from app.domain.derivations import is_today
from app.domain.entities import (
    ActualSession,
    Command,
    InvariantViolationError,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import CommandType, WeekStatus, WorkoutStatus


class TransitionError(Exception):
    """Переход невозможен в текущем состоянии."""


def propose_week(week: Week, new_content: Week) -> Week:
    """I21/I40: повторный propose полностью заменяет содержимое proposed-недели.

    Новый propose вытирает предыдущий: неделю можно предлагать заново, пока она
    не активна. Привязки факта пользователь ставит заново.
    """
    if week.status is not WeekStatus.PROPOSED:
        raise TransitionError(
            f"предложить заново можно только proposed-неделю, а не {week.status}"
        )

    replaced = Week(
        id=week.id,
        plan_id=week.plan_id,
        season_week=week.season_week,
        start=week.start,
        end=week.end,
        status=WeekStatus.PROPOSED,
        focus=new_content.focus,
        load_target=new_content.load_target,
        requests=list(new_content.requests),
        assignments=list(new_content.assignments),
        unplaced=list(new_content.unplaced),
        slot_overrides=list(new_content.slot_overrides),
        # привязки факта сброшены: пользователь ставит их заново
        workouts=[_without_actual(w) for w in new_content.workouts],
        summary=None,
        version=week.version,
    )
    replaced.validate()
    return replaced


def _without_actual(workout: Workout) -> Workout:
    """Сброс привязки факта — при повторном propose она ставится заново."""
    return Workout(
        id=workout.id,
        request_id=workout.request_id,
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
        status=WorkoutStatus.PLANNED,
        rationale=workout.rationale,
        actual_id=None,
    )


def activate_week(week: Week) -> Week:
    """proposed → active. Висяки остаются висять: расписание мягкое."""
    if week.status is not WeekStatus.PROPOSED:
        raise TransitionError(f"активировать можно только proposed, а не {week.status}")

    activated = week.copy_with(status=WeekStatus.ACTIVE)
    activated.validate()
    return activated


def close_week(week: Week, summary: WeekSummary) -> Week:
    """active → closed. Саммари пишется и фиксируется.

    I23: закрытая неделя не меняется — после закрытия переходов больше нет.
    I25: переносов между неделями нет — закрываем одну, потом планируем следующую.
    """
    if week.status is not WeekStatus.ACTIVE:
        raise TransitionError(f"закрыть можно только active, а не {week.status}")

    closed = week.copy_with(status=WeekStatus.CLOSED)
    closed.summary = summary
    closed.validate()
    return closed


def replan_remainder(week: Week, today: date, new_workouts: list[Workout]) -> Week:
    """I22/I39: переплан остатка — меняет только сессии на сегодня и позже.

    «Сегодня» определяется по календарной дате. Прошедшие сессии не трогаются.
    """
    if week.status is WeekStatus.CLOSED:
        raise TransitionError("закрытая неделя не перепланируется")

    replanned = week.copy_with()
    for workout in new_workouts:
        workout_date = _workout_date(workout, week)
        if not is_today(workout_date, today) and workout_date < today:
            continue  # прошедшая — не трогаем
        replanned.workouts = [w for w in replanned.workouts if w.id != workout.id]
        replanned.workouts.append(workout)

    replanned.validate()
    return replanned


def _workout_date(workout: Workout, week: Week) -> date:
    """Дата тренировки: из `time`, иначе — начало недели."""
    if workout.time:
        try:
            return date.fromisoformat(workout.time)
        except ValueError:
            return week.start
    return week.start


def link_actual(week: Week, workout_id: str, actual: ActualSession) -> Week:
    """I9/I10/I11/I15: связь факта и тренировки — только вручную, 1:1.

    Один факт — максимум одна плановая тренировка, и наоборот.
    """
    workouts = [w for w in week.workouts if w.id == workout_id]
    if not workouts:
        raise TransitionError(f"в неделе {week.id} нет тренировки {workout_id}")

    for other in week.workouts:
        if other.id != workout_id and other.actual_id == actual.id:
            raise TransitionError(
                f"факт {actual.id} уже связан с тренировкой {other.id} — связь 1:1"
            )

    updated = week.copy_with()
    for workout in updated.workouts:
        if workout.id == workout_id:
            workout.actual_id = actual.id
            workout.status = WorkoutStatus.DONE
    updated.validate()
    return updated


def unlink_actual(week: Week, workout_id: str) -> Week:
    """Разрыв связи факта и тренировки."""
    updated = week.copy_with()
    for workout in updated.workouts:
        if workout.id == workout_id:
            workout.actual_id = None
            if workout.status is WorkoutStatus.DONE:
                workout.status = WorkoutStatus.PLANNED
    updated.validate()
    return updated


def close_week_is_forbidden_after_close(week: Week) -> None:
    """I23/I24: закрытая неделя не меняется; закрытие — только по команде."""
    if week.status is WeekStatus.CLOSED:
        raise TransitionError("неделя уже закрыта")


def check_status_changed_by_command(week: Week, command: Command) -> None:
    """I19: статус недели меняется только через Command."""
    if command.type not in (
        CommandType.PROPOSE_WEEK,
        CommandType.ACTIVATE_WEEK,
        CommandType.CLOSE_WEEK,
        CommandType.REPLAN_REMAINDER,
    ):
        raise InvariantViolationError(
            "I19", f"команда {command.type} не может менять статус недели"
        )


def check_single_week_proposed(season_week_numbers: list[int]) -> None:
    """I41: план готовит propose для одной следующей недели."""
    if len(season_week_numbers) > 1:
        raise TransitionError(
            f"propose готовится для одной недели, а передано {len(season_week_numbers)}"
        )


