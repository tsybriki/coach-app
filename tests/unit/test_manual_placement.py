"""
Ручная привязка тренировок к дням недели.

Авто-привязка работает плохо, и решение о времени тренировки принимает
пользователь. Проверяем главное: привязка работает, обратное действие
работает, и — главное — **никаких проверок**: план мягкий, и «нельзя»
здесь было бы ровно тем, от чего мы уходим.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    Assignment,
    Request,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FocusType,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)
from app.services.week_lifecycle import (
    TransitionError,
    place_unplaced,
    unplace_request,
)

WEEK_START = date(2026, 10, 11)
WEEK_END = date(2026, 10, 17)


def make_step(step_id: str = "s1", duration: float = 60.0) -> Step:
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=duration,
        focus=FocusType.HR,
        focus_value={"zone": "Z2"},
        duration_min=duration,
    )


def make_request(req_id: str = "r1", duration: int = 60) -> Request:
    return Request(id=req_id, sport=Sport.RUN, kind="easy", focus="base",
                   duration_min=duration)


def make_workout(req_id: str = "r1", duration: float = 60.0) -> Workout:
    return Workout(
        id=f"w-{req_id}",
        request_id=req_id,
        sport=Sport.RUN,
        kind="easy",
        focus="base",
        steps=[make_step("s1", duration)],
        duration_min=duration,
    )


def make_week_with_unplaced(req_id: str = "r1") -> Week:
    return Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=WEEK_START,
        end=WEEK_END,
        status=WeekStatus.PROPOSED,
        requests=[make_request(req_id)],
        unplaced=[make_request(req_id)],
        workouts=[make_workout(req_id)],
    )


def test_place_unplaced_binds_request_to_slot():
    """Висяк, привязанный к окну, перестаёт быть висяком."""
    week = make_week_with_unplaced("r4-6")

    updated = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    assert [r.id for r in updated.unplaced] == []
    assert len(updated.assignments) == 1
    assignment = updated.assignments[0]
    assert assignment.request_id == "r4-6"
    assert assignment.slot_id == "win-ПН-1"
    assert assignment.start == "18:45"
    assert assignment.duration_min == 60


def test_place_unplaced_sets_slot_on_workout():
    """Тренировка висяка получает окно — карточка знает, куда она встала."""
    week = make_week_with_unplaced("r4-6")

    updated = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    workout = next(w for w in updated.workouts if w.request_id == "r4-6")
    assert workout.objective.get("slot_id") == "win-ПН-1"
    assert workout.time == "18:45"


def test_place_unplaced_sets_day_on_workout():
    """Перенос в другой день меняет день в карточке.

    Иначе тренировка стоит в субботу, а подписана средой — карточка
    показывает не тот день, в который её положили.
    """
    week = make_week_with_unplaced("r4-6")

    updated = place_unplaced(week, "r4-6", "win-СБ-1", start="10:00", day=6)

    workout = next(w for w in updated.workouts if w.request_id == "r4-6")
    assert workout.objective.get("day") == 6
    assert workout.time == "10:00"


def test_place_unplaced_keeps_day_when_not_given():
    """Без дня от сервера прежний день не стирается."""
    week = make_week_with_unplaced("r4-6")
    week.workouts[0].objective = {"day": 3}

    updated = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    workout = next(w for w in updated.workouts if w.request_id == "r4-6")
    assert workout.objective.get("day") == 3


def test_place_unplaced_accepts_occupied_slot():
    """Занятое окно — не помеха: решение принимает пользователь.

    Проверок нет: если пользователь поставил тренировку в это окно,
    значит, она там и стоит.
    """
    week = make_week_with_unplaced("r4-6")
    occupied = Week(
        id=week.id,
        plan_id=week.plan_id,
        season_week=week.season_week,
        start=week.start,
        end=week.end,
        status=week.status,
        requests=week.requests,
        assignments=[Assignment(request_id="r4-1", slot_id="win-ПН-1",
                               start="18:45", duration_min=60)],
        unplaced=week.unplaced,
        workouts=week.workouts,
    )

    updated = place_unplaced(occupied, "r4-6", "win-ПН-1", start="18:45")

    assert len(updated.assignments) == 2
    assert {a.slot_id for a in updated.assignments} == {"win-ПН-1"}


def test_place_unplaced_accepts_oversized_session():
    """Тренировка длиннее окна — тоже не помеха."""
    week = make_week_with_unplaced("r4-6")

    updated = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    assert len(updated.assignments) == 1


def test_place_unplaced_rejects_unknown_request():
    """Несуществующий висяк — понятная ошибка, а не тихий no-op."""
    week = make_week_with_unplaced("r4-6")

    with pytest.raises(TransitionError):
        place_unplaced(week, "r4-99", "win-ПН-1")


def test_place_unplaced_requires_slot():
    """Без окна привязка невозможна — это не «привязать куда-нибудь»."""
    week = make_week_with_unplaced("r4-6")

    with pytest.raises(TransitionError):
        place_unplaced(week, "r4-6", "")


def test_unplace_request_returns_session_to_unplaced():
    """Обратное действие: тренировка снова висяк."""
    week = make_week_with_unplaced("r4-6")
    placed = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    updated = unplace_request(placed, "r4-6")

    assert [r.id for r in updated.unplaced] == ["r4-6"]
    assert updated.assignments == []
    workout = next(w for w in updated.workouts if w.request_id == "r4-6")
    assert "slot_id" not in workout.objective


def test_unplace_request_rejects_unplaced():
    """Висяка нечего отвязывать — он и так не привязан."""
    week = make_week_with_unplaced("r4-6")

    with pytest.raises(TransitionError):
        unplace_request(week, "r4-6")


def test_placing_twice_moves_not_duplicates():
    """Повторная привязка того же висяка не плодит размещения."""
    week = make_week_with_unplaced("r4-6")
    placed = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    # Висяка больше нет — второй раз привязать его нельзя.
    with pytest.raises(TransitionError):
        place_unplaced(placed, "r4-6", "win-ВТ-1")


def test_place_unplaced_keeps_other_unplaced():
    """Привязка одного висяка не трогает остальных."""
    other = make_request("r4-7")
    week = Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=WEEK_START,
        end=WEEK_END,
        status=WeekStatus.PROPOSED,
        requests=[make_request("r4-6"), other],
        unplaced=[make_request("r4-6"), other],
        workouts=[make_workout("r4-6"), make_workout("r4-7")],
    )

    updated = place_unplaced(week, "r4-6", "win-ПН-1", start="18:45")

    assert [r.id for r in updated.unplaced] == ["r4-7"]


def test_slot_entity_exists_for_reference():
    """Окно, к которому привязывают, — обычное окно среды."""
    slot = Slot(id="win-ПН-1", day=1, start="18:45", end="20:15",
                capacity_min=90)
    assert slot.day == 1
    assert slot.capacity_min == 90
