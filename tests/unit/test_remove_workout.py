"""Удаление тренировки из недели.

Кирилл: «нужно добавить кнопку удалить тренировку, которая доступна
только пока неделя не активирована. Потому что если что-то не пошло,
нужно возможность удалить эту тренировку».

Правило: удалять можно у proposed-недели. Активная неделя — исполняется,
закрытая — не меняется (I23).
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    Assignment,
    Request,
    Step,
    Week,
    Workout,
)
from app.domain.enums import Sport, StepRole, TargetType, WeekStatus
from app.services.week_lifecycle import TransitionError, remove_workout


def make_week(status: WeekStatus = WeekStatus.PROPOSED) -> Week:
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    return Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=status,
        requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN,
                          kind="easy", focus="base", steps=[step],
                          duration_min=60.0, time="18:45")],
    )


def test_remove_workout_drops_workout_request_and_assignment():
    """Удаляются тренировка, её запрос и её размещение."""
    week = make_week()

    updated = remove_workout(week, "w1")

    assert updated.workouts == []
    assert updated.requests == []
    assert updated.assignments == []
    assert updated.unplaced == []


def test_remove_workout_keeps_other_workouts():
    """Остальные тренировки недели не трогаются."""
    week = make_week()
    other_step = Step(id="s2", role=StepRole.WORK, sport=Sport.RUN,
                      target_type=TargetType.TIME, target_value=30.0,
                      duration_min=30.0)
    other_request = Request(id="r2", sport=Sport.RUN, kind="long", focus="long",
                             duration_min=30)
    week.requests.append(other_request)
    # Размещение обязательно: запрос без размещения должен висеть в
    # unplaced (инвариант I7).
    week.assignments.append(Assignment(request_id="r2", slot_id="s2",
                                        start="10:00", duration_min=30))
    week.workouts.append(Workout(
        id="w2", request_id="r2", sport=Sport.RUN, kind="long", focus="long",
        steps=[other_step], duration_min=30.0, time="10:00"))

    updated = remove_workout(week, "w1")

    assert [w.id for w in updated.workouts] == ["w2"]
    assert [r.id for r in updated.requests] == ["r2"]


def test_remove_unplaced_workout_drops_it_from_unplaced():
    """Висяк удаляется вместе с тренировкой."""
    week = make_week()
    week.unplaced.append(week.requests[0])

    updated = remove_workout(week, "w1")

    assert updated.unplaced == []


def test_cannot_remove_from_active_week():
    """Активная неделя — исполняется: удалять из неё нельзя."""
    week = make_week(WeekStatus.ACTIVE)

    with pytest.raises(TransitionError) as error:
        remove_workout(week, "w1")

    assert "актив" in str(error.value).lower()


def test_cannot_remove_from_closed_week():
    """Закрытая неделя не меняется (I23)."""
    week = make_week(WeekStatus.CLOSED)

    with pytest.raises(TransitionError):
        remove_workout(week, "w1")


def test_cannot_remove_unknown_workout():
    """Нет такой тренировки — понятная ошибка."""
    week = make_week()

    with pytest.raises(TransitionError) as error:
        remove_workout(week, "w-none")

    assert "w-none" in str(error.value)
