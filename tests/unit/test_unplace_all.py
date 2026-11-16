"""Отвязка тренировок без факта от слотов.

Два действия, различающиеся только тем, что происходит со статусом
недели:

- `replan_remainder` — активная неделя возвращается в `proposed`,
  тренировки без факта отвязываются от слотов. **Без пересборки**:
  новые тренировки не создаются, план остаётся прежним.
- `unplace_all` — то же отвязка, но статус недели не меняется:
  неделя остаётся активной, а тренировки просто теряют дни и
  становятся висяками.

Обе команды не трогают выполненное: тренировка с фактом остаётся на
своём месте и со своей связью.

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
    replan_remainder,
    unplace_all,
)


def make_step(duration: float = 60.0) -> Step:
    return Step(
        id="s1",
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=duration,
        duration_min=duration,
    )


def make_workout(wid: str, req_id: str, *, actual_id: str | None = None) -> Workout:
    return Workout(
        id=wid,
        request_id=req_id,
        sport=Sport.RUN,
        kind="easy",
        focus="base",
        objective={"name": "Лёгкий бег", "day": 1, "slot_id": "s2"},
        steps=[make_step()],
        duration_min=60.0,
        actual_id=actual_id,
        status=WorkoutStatus.DONE if actual_id else WorkoutStatus.PLANNED,
    )


def make_request(req_id: str) -> Request:
    return Request(id=req_id, sport=Sport.RUN, kind="easy", focus="base",
                   duration_min=60)


def week_with_two(status: WeekStatus = WeekStatus.ACTIVE) -> Week:
    """Неделя: одна тренировка выполнена, другая — нет. Обе размещены."""
    return Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=__import__("datetime").date(2026, 10, 11),
        end=__import__("datetime").date(2026, 10, 17),
        status=status,
        requests=[make_request("r-done"), make_request("r-planned")],
        assignments=[
            Assignment(request_id="r-done", slot_id="s1", start="18:45",
                       duration_min=60),
            Assignment(request_id="r-planned", slot_id="s2", start="18:45",
                       duration_min=60),
        ],
        workouts=[
            make_workout("w-done", "r-done", actual_id="a1"),
            make_workout("w-planned", "r-planned"),
        ],
    )


# ------------------------------------------------------------------ I22


def test_i22_replan_unplaces_workout_without_fact():
    """I22: тренировка без факта теряет слот — её можно привязать заново."""
    week = week_with_two()

    replanned = replan_remainder(week)

    assert not any(a.request_id == "r-planned" for a in replanned.assignments)
    assert "r-planned" in {r.id for r in replanned.unplaced}


def test_i22_replan_does_not_rebuild_plan():
    """Переплан не пересобирает план: новых тренировок не появляется.

    Пересборка по правилам создаёт тренировки заново — а это не то,
    о чём просил пользователь: он хотел отвязать тренировки, чтобы
    двигать их, а не получить другой план.
    """
    week = week_with_two()

    replanned = replan_remainder(week)

    assert len(replanned.workouts) == 2, "план пересобран — тренировок стало больше"
    assert {w.id for w in replanned.workouts} == {"w-done", "w-planned"}


def test_i22_replan_keeps_workout_with_fact():
    """Выполненная тренировка не трогается: факт, слот и день на месте."""
    week = week_with_two()

    replanned = replan_remainder(week)

    done = next(w for w in replanned.workouts if w.actual_id == "a1")
    assert done.objective.get("day") == 1
    assert any(a.request_id == "r-done" for a in replanned.assignments)


def test_i22_replan_clears_day_of_unplaced_workout():
    """У отвязанной тренировки дня нет — иначе она осталась бы размещённой."""
    week = week_with_two()

    replanned = replan_remainder(week)

    planned = next(w for w in replanned.workouts if w.id == "w-planned")
    assert "day" not in planned.objective
    assert "slot_id" not in planned.objective


def test_i22_replan_returns_week_to_proposed():
    """После переплана неделя снова proposed — её можно править."""
    week = week_with_two()

    replanned = replan_remainder(week)

    assert replanned.status is WeekStatus.PROPOSED


def test_i22_replan_result_passes_invariants():
    week = week_with_two()

    replanned = replan_remainder(week)

    replanned.validate()


# ------------------------------------------------------------------ I23


def test_i23_replan_closed_week_is_rejected():
    """I23: закрытая неделя не перепланируется."""
    week = week_with_two(WeekStatus.CLOSED)

    with pytest.raises(TransitionError, match="закрыт"):
        replan_remainder(week)


# ------------------------------------------------------------------ отвязка всех


def test_unplace_all_unplaces_workout_without_fact():
    """Отвязка всех: тренировка без факта теряет слот."""
    week = week_with_two()

    result = unplace_all(week)

    assert not any(a.request_id == "r-planned" for a in result.assignments)
    assert "r-planned" in {r.id for r in result.unplaced}


def test_unplace_all_keeps_week_active():
    """Статус недели не меняется: она остаётся в процессе."""
    week = week_with_two()

    result = unplace_all(week)

    assert result.status is WeekStatus.ACTIVE


def test_unplace_all_keeps_workout_with_fact():
    """Выполненное не трогается."""
    week = week_with_two()

    result = unplace_all(week)

    done = next(w for w in result.workouts if w.actual_id == "a1")
    assert done.objective.get("day") == 1
    assert any(a.request_id == "r-done" for a in result.assignments)


def test_unplace_all_does_not_rebuild_plan():
    """Отвязка не пересобирает план: тренировки те же."""
    week = week_with_two()

    result = unplace_all(week)

    assert len(result.workouts) == 2
    assert {w.id for w in result.workouts} == {"w-done", "w-planned"}


def test_unplace_all_on_closed_week_is_rejected():
    """Закрытая неделя не отвязывается."""
    week = week_with_two(WeekStatus.CLOSED)

    with pytest.raises(TransitionError, match="закрыт"):
        unplace_all(week)


def test_unplace_all_result_passes_invariants():
    week = week_with_two()

    result = unplace_all(week)

    result.validate()


def test_unplace_all_is_idempotent():
    """Повторная отвязка ничего не меняет: висяк отвязывать нечего."""
    week = week_with_two()

    once = unplace_all(week)
    twice = unplace_all(once)

    assert twice.assignments == once.assignments
    assert {r.id for r in twice.unplaced} == {r.id for r in once.unplaced}
