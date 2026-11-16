"""Перепланировка остатка недели: `replan_remainder`.

Смысл команды (Кирилл): «все тренировки, которым не привязан факт,
переходят в состояние proposed, неделя приходит назад в состояние
proposed, и можно поменять все тренировки, которым не привязан факт».

Команда делит неделю **по факту**, а не по дате:

  - тренировка с фактом — выполнена, её не трогаем: факт остаётся
    связан, тренировка остаётся на своём месте;
  - тренировка без факта — не выполнена: она снова планируемая. Её
    запрос уходит в `unplaced` (висяк), размещение снимается, день и
    окно из карточки убираются — иначе тренировка осталась бы и в
    списке размещённых, и среди висяков.

Неделя возвращается в `proposed`: дальше работает обычный режим
propose — пересборка по правилам, ручная правка, активация.

Имена тестов = номера инвариантов из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

import pytest

from app.domain.entities import (
    Assignment,
    Request,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
    WorkoutStatus,
)
from app.services.week_lifecycle import (
    TransitionError,
    activate_week,
    replan_remainder,
)


def make_step(step_id: str = "s1", duration: float = 60.0) -> Step:
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=duration,
        duration_min=duration,
    )


def make_workout(wid: str, req_id: str, *, actual_id: str | None = None,
                 duration: float = 60.0) -> Workout:
    return Workout(
        id=wid,
        request_id=req_id,
        sport=Sport.RUN,
        kind="easy",
        focus="base",
        objective={"name": "Лёгкий бег", "day": 1, "slot_id": "s2"},
        steps=[make_step(duration=duration)],
        duration_min=duration,
        actual_id=actual_id,
        status=WorkoutStatus.DONE if actual_id else WorkoutStatus.PLANNED,
    )


def make_request(req_id: str) -> Request:
    return Request(id=req_id, sport=Sport.RUN, kind="easy", focus="base",
                   duration_min=60)


def active_week(*, done_id: str = "w-done",
                planned_id: str = "w-planned") -> Week:
    """Активная неделя: одна тренировка выполнена, другая — нет."""
    done_req = make_request("r-done")
    planned_req = make_request("r-planned")
    return Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=__import__("datetime").date(2026, 10, 11),
        end=__import__("datetime").date(2026, 10, 17),
        status=WeekStatus.ACTIVE,
        requests=[done_req, planned_req],
        assignments=[
            Assignment(request_id="r-done", slot_id="s1", start="18:45",
                       duration_min=60),
            Assignment(request_id="r-planned", slot_id="s2", start="18:45",
                       duration_min=60),
        ],
        workouts=[
            make_workout(done_id, "r-done", actual_id="a1"),
            make_workout(planned_id, "r-planned"),
        ],
    )


# ------------------------------------------------------------------ I22


def test_i22_replan_keeps_workout_with_fact():
    """I22: переплан не трогает тренировку, к которой привязан факт."""
    week = active_week()

    replanned = replan_remainder(week)

    done = [w for w in replanned.workouts if w.actual_id == "a1"]
    assert len(done) == 1, "тренировка с фактом потерялась"
    assert done[0].status is WorkoutStatus.DONE
    assert done[0].actual_id == "a1"


def test_i22_replan_returns_week_to_proposed():
    """I22: после переплана неделя снова proposed — её можно править."""
    week = active_week()

    replanned = replan_remainder(week)

    assert replanned.status is WeekStatus.PROPOSED


def test_i22_replan_moves_workout_without_fact_to_unplaced():
    """I22: тренировка без факта снова планируемая — её можно поменять."""
    week = active_week()

    replanned = replan_remainder(week)

    assert "r-planned" in {r.id for r in replanned.unplaced}
    assert not any(a.request_id == "r-planned" for a in replanned.assignments)


def test_i22_replan_clears_day_of_workout_without_fact():
    """У невыполненной тренировки убирается день: она больше не размещена."""
    week = active_week()

    replanned = replan_remainder(week)

    planned = next(w for w in replanned.workouts if w.id == "w-planned")
    assert "day" not in planned.objective
    assert "slot_id" not in planned.objective
    assert planned.status is WorkoutStatus.PLANNED


def test_i22_replan_keeps_fact_link_of_done_workout():
    """Факт выполненной тренировки остаётся связан с ней."""
    week = active_week()

    replanned = replan_remainder(week)

    done = next(w for w in replanned.workouts if w.actual_id == "a1")
    assert done.request_id == "r-done"
    assert any(a.request_id == "r-done" for a in replanned.assignments)


def test_i22_replan_keeps_done_request_in_week():
    """Запрос выполненной тренировки остаётся в неделе."""
    week = active_week()

    replanned = replan_remainder(week)

    assert "r-done" in {r.id for r in replanned.requests}


def test_i22_replan_works_when_nothing_done():
    """Неделя без выполненного: всё уходит в план заново."""
    week = active_week()
    for workout in week.workouts:
        workout.actual_id = None
        workout.status = WorkoutStatus.PLANNED

    replanned = replan_remainder(week)

    assert replanned.status is WeekStatus.PROPOSED
    assert replanned.assignments == []
    assert {r.id for r in replanned.unplaced} == {"r-done", "r-planned"}


def test_i22_replan_result_passes_invariants():
    """Результат переплана проходит проверки недели."""
    week = active_week()

    replanned = replan_remainder(week)

    replanned.validate()


def test_i22_replan_result_can_be_activated():
    """После переплана неделю можно активировать — обычный режим."""
    week = active_week()

    replanned = replan_remainder(week)
    activated = activate_week(replanned)

    assert activated.status is WeekStatus.ACTIVE


# ------------------------------------------------------------------ I23


def test_i23_replan_closed_week_is_rejected():
    """I23: закрытая неделя не перепланируется."""
    week = active_week()
    week.status = WeekStatus.CLOSED

    with pytest.raises(TransitionError, match="закрыт"):
        replan_remainder(week)


# ------------------------------------------------------------------ I39


def test_i39_replan_divides_by_fact_not_by_date():
    """I39: деление — по факту, а не по календарной дате.

    Тренировка «в прошлом» по дате, но без факта, — невыполненная:
    её переплан трогает. Иначе неделя «зависнет» на тренировках,
    которые пользователь пропустил, и он не сможет их переделать.
    """
    week = active_week()
    past = make_workout("w-past", "r-past")
    week.workouts.append(past)
    week.requests.append(make_request("r-past"))
    week.assignments.append(
        Assignment(request_id="r-past", slot_id="s3", start="18:45",
                   duration_min=60))

    replanned = replan_remainder(week)

    assert "r-past" in {r.id for r in replanned.unplaced}
    assert not any(a.request_id == "r-past" for a in replanned.assignments)


def test_i39_replan_keeps_done_workout_even_if_it_is_in_the_past():
    """Выполненная тренировка не трогается, даже если она «в прошлом»."""
    week = active_week()
    done = next(w for w in week.workouts if w.actual_id == "a1")
    done.time = "2026-10-12"

    replanned = replan_remainder(week)

    assert any(w.actual_id == "a1" for w in replanned.workouts)
