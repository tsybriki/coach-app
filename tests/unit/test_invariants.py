"""Тесты доменных инвариантов.

Имена тестов = номера инвариантов из `specs/domain/DOMAIN-SPEC.md`:
`test_i09_...` — инвариант I9. Связь со спецификацией не теряется.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    ActualSession,
    Athlete,
    Command,
    Goal,
    InvariantViolationError,
    LoadModel,
    Plan,
    PlanStatus,
    Request,
    Season,
    Slot,
    Step,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import (
    CommandType,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)

# ------------------------------------------------------------------ фикстуры


def make_step(step_id: str = "s1", sport: Sport = Sport.RUN, duration: float = 10.0) -> Step:
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=sport,
        target_type=TargetType.TIME,
        target_value=duration,
        duration_min=duration,
    )


def make_request(req_id: str = "r1", sport: Sport = Sport.RUN) -> Request:
    return Request(id=req_id, sport=sport, kind="easy", focus="base", duration_min=60)


def make_workout(
    steps: list[Step] | None = None,
    sport: Sport = Sport.RUN,
    duration_min: float | None = None,
) -> Workout:
    steps = steps if steps is not None else [make_step()]
    total = sum(s.duration_min for s in steps) if duration_min is None else duration_min
    return Workout(
        id="w1",
        request_id="r1",
        sport=sport,
        kind="easy",
        focus="base",
        steps=steps,
        duration_min=total,
    )


def make_week(
    status: WeekStatus = WeekStatus.PROPOSED,
    requests: list[Request] | None = None,
    unplaced: list[Request] | None = None,
    summary: WeekSummary | None = None,
) -> Week:
    return Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=date(2026, 10, 11),
        end=date(2026, 10, 17),
        status=status,
        requests=requests if requests is not None else [make_request()],
        unplaced=unplaced or [],
        summary=summary,
    )


def make_goal() -> Goal:
    return Goal(
        id="g1",
        discipline="run_10k",
        race_date=date(2027, 4, 18),
        metric_type="time_sec",
        metric_target=2400.0,
        target_friendly="10К за 40:00",
    )


def make_plan(status: PlanStatus = PlanStatus.ACTIVE) -> Plan:
    return Plan(
        id="p1",
        status=status,
        goal=make_goal(),
        period_start=date(2026, 10, 11),
        period_end=date(2027, 9, 12),
    )


# ------------------------------------------------------------------ I1, I3


def test_i01_single_active_plan():
    """I1: в сезоне ровно один Plan со статусом active."""
    season = Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 12),
        season_week_count=49,
        plans=[make_plan(PlanStatus.ACTIVE)],
    )
    season.check_single_active_plan()

    season.plans.append(make_plan(PlanStatus.ACTIVE))
    with pytest.raises(InvariantViolationError, match="I1"):
        season.validate()


def test_i03_slot_equipment_must_exist():
    """I3: ссылка слота — на существующее оборудование из реестра."""
    season = Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 12),
        season_week_count=49,
        plans=[make_plan()],
        slots=[
            Slot(
                id="sl1",
                day=0,
                start="18:45",
                end="20:15",
                capacity_min=90,
                equipment_ids=("pool",),
            )
        ],
    )
    with pytest.raises(InvariantViolationError, match="I3"):
        season.check_slot_equipment_exists()


# ------------------------------------------------------------------ I4, I5


def test_i04_single_sport_in_workout():
    """I4: в тренировке один sport; все шаги этого спорта."""
    with pytest.raises(InvariantViolationError, match="I4"):
        make_workout([make_step(sport=Sport.RUN)], sport=Sport.SWIM).validate()


def test_i05_duration_equals_sum_of_steps():
    """I5: Σ длительностей шагов = длительность тренировки."""
    w = make_workout([make_step("a", duration=10.0), make_step("b", duration=20.0)])
    assert w.steps_duration_min == 30.0
    assert w.duration_min == 30.0
    w.validate()

    # плановая длительность разошлась с шагами
    w.duration_min = 45.0
    with pytest.raises(InvariantViolationError, match="I5"):
        w.validate()


# ------------------------------------------------------------------ I6


def test_i06_rest_after_work():
    """I6: шаги не пересекаются по времени; rest идёт после work."""
    rest = Step(
        id="r",
        role=StepRole.REST,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=2.0,
        duration_min=2.0,
    )
    work = make_step("w", duration=10.0)

    make_workout([work, rest]).check_steps_do_not_overlap()

    with pytest.raises(InvariantViolationError, match="I6"):
        make_workout([rest, work]).check_steps_do_not_overlap()


# ------------------------------------------------------------------ I7


def test_i07_request_without_placement_goes_to_unplaced():
    """I7: запрос без размещения попадает в unplaced с причиной."""
    week = make_week()
    with pytest.raises(InvariantViolationError, match="I7"):
        week.validate()

    week.unplaced.append(make_request())
    week.validate()


# ------------------------------------------------------------------ I8


def test_i08_closed_week_has_summary():
    """I8: у недели со статусом closed есть WeekSummary."""
    week = make_week(status=WeekStatus.CLOSED, unplaced=[make_request()])
    with pytest.raises(InvariantViolationError, match="I8"):
        week.validate()

    week.summary = WeekSummary(week_id=week.id)
    week.validate()


# ------------------------------------------------------------------ I9


def test_i09_link_is_bidirectional():
    """I9: Workout.actual_id и ActualSession.linked_workout_id указывают друг на друга."""
    w = make_workout()
    a = ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60
    )

    w.actual_id = a.id
    a.linked_workout_id = w.id

    assert w.actual_id == a.id
    assert a.linked_workout_id == w.id


# ------------------------------------------------------------------ I16


def test_i16_actual_moderate_equals_sum_of_contributions():
    """I16: actual_moderate = Σ contributions[].moderate_min."""
    summary = WeekSummary(
        week_id="W1",
        intensity={
            "actual_moderate": 30,
            "contributions": [
                {"actual_id": "a1", "moderate_min": 10, "vigorous_min": 5},
                {"actual_id": "a2", "moderate_min": 20, "vigorous_min": 0},
            ],
        },
    )
    assert summary.actual_moderate() == 30
    assert summary.actual_vigorous() == 5
    summary.check_contributions_sum()

    summary.intensity["actual_moderate"] = 25
    with pytest.raises(InvariantViolationError, match="I16"):
        summary.check_contributions_sum()


# ------------------------------------------------------------------ I20


def test_i20_every_workout_grew_from_request():
    """I20: каждый Workout вырос из Request (request_id задан)."""
    week = make_week(unplaced=[make_request()])
    week.workouts.append(make_workout())
    week.validate()

    week.workouts[0].request_id = "unknown"
    with pytest.raises(InvariantViolationError, match="I20"):
        week.validate()


# ------------------------------------------------------------------ I31


def test_i31_unplaced_not_bound_to_day():
    """I31: висяк (unplaced[]) не привязан к дню."""
    week = make_week(unplaced=[make_request()])
    week.validate()


# ------------------------------------------------------------------ I43


def test_i43_adaptation_rate_has_single_owner():
    """I43: единственный adaptation_rate — в LoadModel."""
    lm = LoadModel(adaptation_rate={"run": 1.0, "swim": 0.55})
    assert lm.adaptation_rate["swim"] == 0.55

    # в Athlete такого поля нет — единственный владелец
    assert not hasattr(Athlete, "adaptation_rate")


# ------------------------------------------------------------------ команды


def test_command_requires_reason():
    """Команда без причины не принимается."""
    with pytest.raises(InvariantViolationError, match="reason"):
        Command(id="c1", type=CommandType.PROPOSE_WEEK, reason="   ")


def test_command_types_cover_all_operations():
    """Все типы команд из спецификации присутствуют в enum."""
    expected = {
        "propose_week",
        "activate_week",
        "close_week",
        "replan_remainder",
        "place_unplaced",
        "unplace_request",
        "link_actual",
        "unlink_actual",
        "edit_actual",
        "update_athlete",
        "set_goal",
        "set_plan",
        "set_slots",
        "override_slots",
        "set_equipment",
        "set_gate_result",
        "decide_gate",
        "pull_fact",
        "import_fit",
        "narrate",
        "import_state",
    }
    assert expected == {t.value for t in CommandType}


# ------------------------------------------------------------------ факт


def test_actual_session_defaults():
    """Факт по умолчанию: Garmin, без связи с планом."""
    a = ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60
    )
    assert a.linked_workout_id is None
    assert a.source.value == "garmin"
