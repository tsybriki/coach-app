"""Тесты сервисов: планировщик недели, достижимость, оценка."""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    ActualSession,
    Assignment,
    Athlete,
    Goal,
    LoadModel,
    Request,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FactSource,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)
from app.services.assessment import Assessor
from app.services.goal_feasibility import (
    GoalFeasibility,
    LinearGrowthRule,
    StubGrowthRule,
    VerdictKind,
)
from app.services.week_planner import WeeklyTarget, WeekPlanner

WEEK_START = date(2026, 10, 11)
WEEK_END = date(2026, 10, 17)


def make_athlete(vdot: float = 46.4) -> Athlete:
    return Athlete(
        vdot=vdot,
        hr_zones={"Z2": (118, 135)},
        hr_max=182,
        rhr=54,
        lth=164,
    )


def make_slots() -> list[Slot]:
    return [
        Slot(id="sl-mon", day=0, start="18:45", end="20:15", capacity_min=90),
        Slot(id="sl-tue", day=1, start="09:00", end="09:30", capacity_min=30),
    ]


def make_planner() -> WeekPlanner:
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0, "swim": 0.55}),
        athlete=make_athlete(),
    )


def make_goal(race_date: date = date(2027, 4, 18), target: float = 2400.0) -> Goal:
    return Goal(
        id="g1",
        discipline="run_10k",
        race_date=race_date,
        metric_type="time_sec",
        metric_target=target,
        target_friendly="10К за 40:00",
    )


# ------------------------------------------------------------------ планировщик


def test_planner_builds_week_from_targets():
    """Планировщик собирает неделю: запросы → размещения → тренировки → шаги."""
    planner = make_planner()
    targets = [
        WeeklyTarget(sport=Sport.RUN, duration_min=60, focus="base"),
        WeeklyTarget(sport=Sport.SWIM, duration_min=30),
    ]

    week = planner.build(1, WEEK_START, WEEK_END, targets, make_slots())

    assert week.status is WeekStatus.PROPOSED
    assert len(week.requests) == 2
    assert len(week.assignments) == 2
    assert len(week.workouts) == 2
    assert len(week.unplaced) == 0
    assert week.validate() is None


def test_planner_step_durations_sum_to_workout():
    """Длительность тренировки = Σ шагов."""
    planner = make_planner()
    week = planner.build(
        1, WEEK_START, WEEK_END,
        [WeeklyTarget(sport=Sport.RUN, duration_min=60)],
        make_slots(),
    )
    workout = week.workouts[0]
    assert workout.duration_min == sum(s.duration_min for s in workout.steps)
    assert workout.duration_min == pytest.approx(60.0)


def test_planner_puts_unplaced_when_no_slot_fits():
    """Не разложилось — висяк, решение пользователя."""
    planner = make_planner()
    targets = [
        WeeklyTarget(sport=Sport.RUN, duration_min=60),
        WeeklyTarget(sport=Sport.SWIM, duration_min=30),
        WeeklyTarget(sport=Sport.BIKE, duration_min=120),
    ]

    week = planner.build(1, WEEK_START, WEEK_END, targets, make_slots())

    assert len(week.unplaced) == 1, "третья тренировка не поместилась — висяк"
    assert len(week.assignments) == 2
    week.validate()


def test_planner_respects_slot_capacity():
    """Слот берётся, только если хватает времени."""
    planner = make_planner()
    week = planner.build(
        1, WEEK_START, WEEK_END,
        [WeeklyTarget(sport=Sport.RUN, duration_min=45)],
        make_slots(),
    )
    # первый слот 90 мин — подходит
    assert week.assignments[0].slot_id == "sl-mon"


def test_planner_skips_slot_with_wrong_equipment():
    """Слот без нужного оборудования не берётся."""
    planner = make_planner()
    slots = [
        Slot(id="sl-mon", day=0, start="18:45", end="20:15", capacity_min=90),
        Slot(id="sl-pool", day=1, start="09:00", end="09:30", capacity_min=30,
             equipment_ids=("pool",)),
    ]
    week = planner.build(
        1, WEEK_START, WEEK_END,
        [WeeklyTarget(sport=Sport.SWIM, duration_min=30,
                      equipment_required=("pool",))],
        slots,
    )
    # слот плава подходит по оборудованию
    assert week.assignments[0].slot_id == "sl-pool"
    assert week.requests[0].equipment_required == ("pool",)


def test_planner_load_target_sums_targets():
    """Недельная цель — сумма минут и число сессий."""
    planner = make_planner()
    week = planner.build(
        1, WEEK_START, WEEK_END,
        [
            WeeklyTarget(sport=Sport.RUN, duration_min=60),
            WeeklyTarget(sport=Sport.SWIM, duration_min=30),
        ],
        make_slots(),
    )
    assert week.load_target["minutes"] == 90.0
    assert week.load_target["sessions"] == 2.0


# ------------------------------------------------------------------ достижимость


def test_feasibility_with_stub_rule_says_cannot_estimate():
    """Правило роста не задано — честный ответ «не могу оценить»."""
    service = GoalFeasibility(
        growth_rule=StubGrowthRule(),
        target_vdot_for_metric=lambda goal: 52.0,
    )
    verdict = service.assess(make_goal(), make_athlete(), date(2026, 10, 26))

    assert verdict.kind is VerdictKind.CANNOT_ESTIMATE
    assert "не задано" in verdict.reason
    assert verdict.gap == pytest.approx(5.6)
    assert verdict.options


def test_feasibility_achievable_when_ceiling_covers_target():
    """Потолок покрывает цель — вердикт «достижима»."""
    service = GoalFeasibility(
        growth_rule=LinearGrowthRule(vdot_per_week=0.5),
        target_vdot_for_metric=lambda goal: 52.0,
    )
    verdict = service.assess(make_goal(), make_athlete(), date(2026, 10, 26))
    assert verdict.kind is VerdictKind.ACHIEVABLE


def test_feasibility_not_achievable_gives_options():
    """Цель недостижима — варианты: смягчить, сдвинуть, наилучшая достижимая."""
    service = GoalFeasibility(
        growth_rule=LinearGrowthRule(vdot_per_week=0.01),
        target_vdot_for_metric=lambda goal: 52.0,
    )
    verdict = service.assess(make_goal(), make_athlete(), date(2026, 10, 26))

    assert verdict.kind is VerdictKind.NOT_ACHIEVABLE
    assert len(verdict.options) == 3
    assert "смягчить" in verdict.options[0]
    assert "сдвинуть" in verdict.options[1]
    assert "наилучшую" in verdict.options[2]


def test_feasibility_with_caveats_when_ceiling_near_target():
    """Потолок покрывает цель не полностью — «с оговорками»."""
    service = GoalFeasibility(
        growth_rule=LinearGrowthRule(vdot_per_week=0.21),
        target_vdot_for_metric=lambda goal: 52.0,
    )
    verdict = service.assess(make_goal(), make_athlete(), date(2026, 10, 26))
    assert verdict.kind is VerdictKind.ACHIEVABLE_WITH_CAVEATS


def test_feasibility_past_race_date_is_not_achievable():
    """Дата цели прошла — недостижимо."""
    service = GoalFeasibility(
        growth_rule=LinearGrowthRule(vdot_per_week=0.5),
        target_vdot_for_metric=lambda goal: 52.0,
    )
    verdict = service.assess(
        make_goal(race_date=date(2020, 1, 1)), make_athlete(), date(2026, 10, 26)
    )
    assert verdict.kind is VerdictKind.NOT_ACHIEVABLE
    assert "прошла" in verdict.reason


# ------------------------------------------------------------------ оценка


def make_week_for_assessment() -> Week:
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    return Week(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=WEEK_START,
        end=WEEK_END,
        status=WeekStatus.ACTIVE,
        requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="sl-mon", start="18:45",
                                duration_min=60)],
        workouts=[
            Workout(id="w1", request_id="r1", sport=Sport.RUN, kind="easy",
                    focus="base", steps=[step], duration_min=60.0)
        ],
    )


def make_session(sid: str, linked: str | None = None) -> ActualSession:
    return ActualSession(
        id=sid,
        date=date(2026, 10, 14),
        sport=Sport.RUN,
        duration_min=60,
        moderate_min=30,
        vigorous_min=10,
        source=FactSource.GARMIN,
        external_id=f"ext-{sid}",
        linked_workout_id=linked,
    )


def test_assessment_counts_linked_and_unlinked():
    """Связанный факт — выполнено, несвязанный — extra."""
    week = make_week_for_assessment()
    sessions = [make_session("a1", linked="w1"), make_session("a2")]

    result = Assessor().assess(week, sessions)

    assert result.summary.verdict["done"] == 1
    assert result.summary.verdict["extra"] == 1
    assert result.unlinked_facts == ["a2"]
    assert result.summary.extra == ["a2"]


def test_assessment_builds_intensity_contributions():
    """Вклад в интенсивность — по связанным фактам недели."""
    week = make_week_for_assessment()
    sessions = [make_session("a1", linked="w1")]

    result = Assessor().assess(week, sessions)
    contributions = result.summary.intensity["contributions"]

    assert len(contributions) == 1
    assert contributions[0]["actual_id"] == "a1"
    assert contributions[0]["moderate_min"] == 30
    assert result.summary.intensity["actual_moderate"] == 30


def test_assessment_ignores_fact_outside_week():
    """Факт вне диапазона недели не попадает в итог."""
    week = make_week_for_assessment()
    outside = make_session("a2")
    outside.date = date(2026, 11, 1)

    result = Assessor().assess(week, [outside])
    assert result.summary.totals["actual_minutes"] == 0.0
    assert result.summary.intensity["actual_moderate"] == 0


def test_assessment_marks_workout_without_fact_as_missed():
    """Тренировка без факта — пропущена."""
    week = make_week_for_assessment()
    result = Assessor().assess(week, [])

    assert result.summary.verdict["missed"] == 1
    assert result.summary.per_session[0]["verdict"].value == "missed"


def test_assessment_records_deviation():
    """Отклонение недели: факт − план."""
    week = make_week_for_assessment()
    sessions = [make_session("a1", linked="w1")]

    result = Assessor().assess(week, sessions)
    minutes = next(d for d in result.summary.deviations if d["metric"] == "minutes")

    assert minutes["planned"] == 60.0
    assert minutes["actual"] == 60.0
