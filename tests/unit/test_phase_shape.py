"""Форма недели фазы по Дэниэлсу.

Правило фазы I (Кирилл, 02.11.2026):

- 7 тренировок в неделю в лёгкой зоне;
- к 4 из них (точно не к длинной) — 6-8 коротких быстрых отрезков по
  100 м через 100 м бега трусцой;
- к 3 из семи — ОФП 15 минут в конце;
- недельный километраж — 55-57, не больше.

Форма — из справочника (`reference/daniels/training_plan_19_1.json`),
структура пробежки — из шагов тренировки: отрезки и ОФП идут **внутри**
пробежки, а не отдельными тренировками.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domain.entities import (
    Athlete,
    Goal,
    LoadModel,
    MacroWeek,
    Plan,
    Season,
    Slot,
)
from app.domain.enums import PlanStatus, Sport, StepRole, TargetType
from app.domain.methodology import ZONE_REPETITION
from app.services.week_planner import WeekPlanner
from app.services.week_proposal import plan_from_macro

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118), "Z2": (118, 135), "Z3": (136, 150), "Z4": (150, 160),
    "Z5": (160, 168), "Z6": (169, 172), "Z7": (173, 182),
}

SLOTS = [
    Slot(id="mon", day=1, start="18:45", end="20:15", capacity_min=90),
    Slot(id="tue-early", day=2, start="09:00", end="09:30", capacity_min=30),
    Slot(id="tue", day=2, start="18:30", end="19:45", capacity_min=75),
    Slot(id="wed", day=3, start="17:00", end="19:00", capacity_min=120),
    Slot(id="thu", day=4, start="10:30", end="11:15", capacity_min=45),
    Slot(id="fri", day=5, start="18:00", end="19:00", capacity_min=60),
    Slot(id="sat", day=6, start="10:00", end="11:00", capacity_min=60),
    Slot(id="sun", day=0, start="11:00", end="13:00", capacity_min=120),
]

# Макро фазы I: километраж и разбивка — из макро-плана сезона.
MACRO_KM = 55.0
MACRO_LONG_MIN = 56
MACRO_QUALITY_MIN = 42
MACRO_EASY_MIN = 158


def _macro_weeks() -> list[MacroWeek]:
    weeks: list[MacroWeek] = []
    for season_week in range(1, 8):
        weeks.append(MacroWeek(
            season_week=season_week,
            phase_id="run_base",
            focus="progression",
            goal_text="Развиваем базу",
            run_km=MACRO_KM,
            total_h=7.5,
            sessions_target=7,
            minutes_by_sport={
                "run": 257.0, "bike": 60.0, "swim": 30.0, "ofp": 0.0,
            },
            long_min=MACRO_LONG_MIN,
            easy_min=MACRO_EASY_MIN,
            quality_min=MACRO_QUALITY_MIN,
        ))
    return weeks


@pytest.fixture
def season() -> Season:
    goal = Goal(
        id="g1",
        discipline="run_10k",
        race_date=date(2027, 4, 18),
        metric_type="time_sec",
        metric_target=2400.0,
        target_friendly="10К за 40:00",
    )
    plan = Plan(
        id="g1",
        status=PlanStatus.ACTIVE,
        goal=goal,
        period_start=date(2026, 10, 11),
        period_end=date(2027, 9, 18),
        macro_weeks=_macro_weeks(),
    )
    return Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 18),
        season_week_count=49,
        slots=SLOTS,
        plans=[plan],
    )


@pytest.fixture
def planner() -> WeekPlanner:
    from app.adapters.daniels import load_paces, load_plan

    athlete = Athlete(
        vdot=48.0, hr_zones=HR_ZONES, hr_max=182, rhr=54, lth=164,
    )
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=load_paces(REFERENCE),
        plan=load_plan(REFERENCE),
    )


def _week(season: Season, planner: WeekPlanner, season_week: int):
    """Неделя фазы I, собранная по правилам."""
    return plan_from_macro(season, season_week, planner, {})


def _runs(week) -> list:
    return [w for w in week.workouts if w.sport is Sport.RUN]


def _stride_count(workout) -> int:
    """Сколько отрезков в пробежке — по шагам в повторном темпе."""
    return sum(
        1 for step in workout.steps
        if step.focus_value.get("daniels_zone") == ZONE_REPETITION
        and step.role is StepRole.WORK
    )


def _ofp_minutes(workout) -> float:
    """Сколько минут ОФП в пробежке."""
    return sum(
        step.duration_min for step in workout.steps
        if step.focus_value.get("ofp")
    )


def _ofp_at_end(workout) -> bool:
    """ОФП — в конце пробежки."""
    ofp_indices = [
        index for index, step in enumerate(workout.steps)
        if step.focus_value.get("ofp")
    ]
    if not ofp_indices:
        return True
    return ofp_indices[-1] == len(workout.steps) - 1


def _km(week) -> float:
    """Километраж недели — по шагам с дистанцией."""
    return sum(
        float(step.target_value)
        for workout in week.workouts
        for step in workout.steps
        if step.target_type is TargetType.DISTANCE
    ) / 1000.0


def test_shape_is_read_from_reference(season, planner):
    """Форма фазы приходит из справочника Дэниэлса, а не из кода."""
    shape = planner._plan.shape_for(1)
    assert shape is not None, "у фазы I нет формы недели"
    assert shape.runs_per_week == 7
    assert shape.stride_runs == 4
    assert shape.stride_reps_min == 6
    assert shape.stride_reps_max == 8
    assert shape.stride_distance_m == 100
    assert shape.stride_recovery_m == 100
    assert shape.ofp_runs == 3
    assert shape.ofp_minutes == 15
    assert shape.weekly_km_min == 55
    assert shape.weekly_km_max == 57


def test_week_has_seven_runs(season, planner):
    """Семь пробежек в неделю — «7 дней в неделю Л-темп»."""
    week = _week(season, planner, 4)
    assert len(_runs(week)) == 7, (
        f"в неделе {len(_runs(week))} пробежек, а правило требует семь"
    )


def test_strides_in_four_runs(season, planner):
    """Отрезки — в четырёх пробежках, по 6-8 в каждой."""
    week = _week(season, planner, 4)
    with_strides = [w for w in _runs(week) if _stride_count(w) > 0]
    assert len(with_strides) == 4, (
        f"отрезки в {len(with_strides)} пробежках, а правило требует четыре"
    )
    for workout in with_strides:
        reps = _stride_count(workout)
        assert 6 <= reps <= 8, (
            f"в пробежке {reps} отрезков, правило говорит 6-8"
        )


def test_long_run_has_no_strides(season, planner):
    """Длинная пробежка — без отрезков.

    Отрезки добавляются «по меньшей мере к четырём Л-забегам», а длинная
    пробежка — тоже Л-забег, но к отрезкам её не добавляют: она и так
    самая длинная.
    """
    week = _week(season, planner, 4)
    long_runs = [w for w in _runs(week) if w.kind == "long"]
    assert long_runs, "в неделе нет длинного бега"
    for workout in long_runs:
        assert _stride_count(workout) == 0, "в длинной пробежке есть отрезки"


def test_shorter_run_gets_more_strides(season, planner):
    """В более короткой пробежке отрезков больше, в более длинной — меньше.

    «6 в более длинной тренировке, 8 в более короткие»: иначе отрезки
    съедают объём длинной пробежки и превращают короткую в интервальную.
    """
    week = _week(season, planner, 4)
    with_strides = [w for w in _runs(week) if _stride_count(w) > 0]
    lengths = [
        (sum(float(s.target_value) for s in w.steps
             if s.target_type is TargetType.DISTANCE),
         _stride_count(w))
        for w in with_strides
    ]
    longest = max(lengths, key=lambda item: item[0])
    shortest = min(lengths, key=lambda item: item[0])
    assert longest[1] <= shortest[1], (
        f"в более длинной пробежке {longest[1]} отрезков, "
        f"в более короткой {shortest[1]}"
    )
    assert longest[1] == 6, "в самой длинной пробежке должно быть 6 отрезков"
    assert shortest[1] == 8, "в самой короткой пробежке должно быть 8 отрезков"


def test_ofp_at_end_of_three_runs(season, planner):
    """ОФП — в конце трёх пробежек, по 15 минут."""
    week = _week(season, planner, 4)
    with_ofp = [w for w in _runs(week) if _ofp_minutes(w) > 0]
    assert len(with_ofp) == 3, (
        f"ОФП в {len(with_ofp)} пробежках, а правило требует три"
    )
    for workout in with_ofp:
        assert _ofp_minutes(workout) == pytest.approx(15.0, abs=1.0), (
            f"ОФП {workout.id}: {_ofp_minutes(workout)} мин, а нужно 15"
        )
        assert _ofp_at_end(workout), f"ОФП в {workout.id} не в конце пробежки"


def test_weekly_km_within_shape(season, planner):
    """Недельный километраж — 55-57, не больше."""
    week = _week(season, planner, 4)
    km = _km(week)
    assert 55.0 <= km <= 57.0, f"недельный километраж {km:.1f}, а нужно 55-57"


def test_every_session_is_unplaced(season, planner):
    """Висят все: время тренировки выбирает пользователь.

    Планировщик больше не раскладывает неделю по окнам — автоматическая
    привязка работала плохо (вел вставал во вторник, где велосипеда нет).
    """
    week = _week(season, planner, 4)
    assert week.assignments == [], "планировщик не должен размещать ничего"
    assert len(week.unplaced) == len(week.requests), (
        "каждая тренировка недели — висяк: "
        f"{len(week.unplaced)} висяков на {len(week.requests)} тренировок"
    )
    for workout in week.workouts:
        assert workout.time is None, "у висяка не должно быть времени"


def test_stride_steps_are_in_workout_structure(season, planner):
    """Отрезки — шаги тренировки, а не отдельные тренировки.

    Иначе неделя показывает 30 тренировок вместо семи.
    """
    week = _week(season, planner, 4)
    for workout in _runs(week):
        if _stride_count(workout) == 0:
            continue
        groups = {step.group for step in workout.steps
                  if step.focus_value.get("daniels_zone") == ZONE_REPETITION}
        assert groups, "у отрезков нет общей группы — клиент их не соберёт"


def test_control_point_takes_one_of_seven_runs(season, planner):
    """Контрольная точка — одна из семи пробежек, а не восьмая."""
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test", "kind": "quality", "title": "3K",
        "distance_m": 3000, "pace_min_per_km": "4:40",
        "variant_id": "tt_pace",
    }
    week = plan_from_macro(season, 4, planner, {})
    assert len(_runs(week)) == 7, (
        f"с контрольной точкой пробежек {len(_runs(week))}, а должно быть семь"
    )
    assert len(week.unplaced) == len(week.requests), (
        "контрольная точка — тоже висяк: время теста выбирает пользователь"
    )


def test_phase_one_km_clamps_macro_volume(season, planner):
    """Форма фазы ограничивает километраж макро.

    Макро говорит 55 км — форма требует 55-57. Если макро скажет
    41, форма всё равно доведёт до 55: недельный километраж в фазе I
    задан правилом, а не объёмом предыдущей недели.
    """
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.run_km = 41.0
    week = plan_from_macro(season, 4, planner, {})
    km = _km(week)
    assert 55.0 <= km <= 57.0, f"недельный километраж {km:.1f}, а нужно 55-57"
