"""
Описание недели — про объём, и карточка совпадает с внутренностью.

Два дефекта, которые это ловит:

1. Описание недели бралось из цели качественной работы. Неделя с
   контрольной точкой называлась «Проверяем форму на контрольной
   точке» — это цель одной тренировки, а не недели. По такой подписи
   каждая пробежка недели выглядела подготовкой к тесту, и объём
   недели в описании не читался.

2. Карточка тренировки и её внутреннее содержание считались разными
   способами, и читатель получал «43 мин» на карточке и другое
   внутри. Здесь: длительность карточки — сумма шагов, а каждый шаг
   с дистанцией согласован со своим темпом.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    Athlete,
    Goal,
    LoadModel,
    MacroWeek,
    Plan,
    Season,
)
from app.domain.enums import PlanStatus
from app.services.week_planner import WeekPlanner
from app.services.week_proposal import plan_from_macro


def _macro_weeks() -> list[MacroWeek]:
    """Макро-недели сезона — с описанием недели про объём."""
    weeks: list[MacroWeek] = []
    for season_week in range(1, 29):
        phase = 1 if season_week <= 6 else (
            2 if season_week <= 13 else (
                3 if season_week <= 20 else 4))
        phase_id = {1: "run_base", 2: "run_build",
                    3: "run_specific", 4: "run_taper"}[phase]
        weeks.append(MacroWeek(
            season_week=season_week,
            phase_id=phase_id,
            focus="tempo",
            goal_text="Набираем 41 км за 7 тренировок · работа по плану",
            run_km=41.0,
            total_h=6.62,
            sessions_target=7,
            minutes_by_sport={
                "run": 257.0, "bike": 60.0, "swim": 30.0, "ofp": 50.0,
            },
            long_min=56,
            easy_min=159,
            quality_min=42,
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
        slots=[],
        plans=[plan],
    )


@pytest.fixture
def planner() -> WeekPlanner:
    """Планировщик с таблицей Дэниэлса — как в приложении."""
    from app.adapters.daniels import load_paces, load_plan

    repo = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
    reference = repo / "reference" / "daniels"
    athlete = Athlete(
        vdot=48.0,
        hr_zones={
            "Z1": (100, 118), "Z2": (118, 135), "Z3": (136, 150),
            "Z4": (150, 160), "Z5": (160, 168), "Z6": (169, 172),
            "Z7": (173, 182),
        },
        hr_max=182, rhr=54, lth=164,
    )
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=load_paces(reference),
        plan=load_plan(reference),
    )


def test_week_description_is_about_volume(season, planner):
    """Описание недели — про объём, а не про контрольную точку."""
    week = plan_from_macro(season, 4, planner, {})
    focus = week.focus or ""
    assert focus, "у недели нет описания"
    assert "контрольной точке" not in focus.lower(), \
        f"описание недели — это цель тренировки: {focus!r}"
    assert "проверяем форму" not in focus.lower(), \
        f"описание недели — это цель тренировки: {focus!r}"


def test_week_description_mentions_kilometres(season, planner):
    """В описании недели читается объём."""
    week = plan_from_macro(season, 4, planner, {})
    focus = week.focus or ""
    assert "км" in focus.lower(), f"в описании недели нет километров: {focus!r}"


def test_card_duration_equals_steps_sum(season, planner):
    """Длительность карточки — сумма шагов тренировки."""
    week = plan_from_macro(season, 4, planner, {})
    for workout in week.workouts:
        total = sum(step.duration_min for step in workout.steps)
        assert abs(total - workout.duration_min) < 0.01, (
            f"{workout.id}: карточка {workout.duration_min:.1f} мин, "
            f"шаги {total:.1f} мин"
        )


def test_distance_step_agrees_with_its_pace(season, planner):
    """Шаг с дистанцией согласован со своим темпом.

    Длина шага в шагах считается по темпу зоны. Если шаг говорит
    «7.3 км @ 5:30», то он должен занимать 44 минуты — иначе внутри
    тренировки время не сходится с расстоянием.
    """
    week = plan_from_macro(season, 4, planner, {})
    checked = 0
    for workout in week.workouts:
        for step in workout.steps:
            fv = step.focus_value or {}
            pace = fv.get("pace_min_per_km")
            if not pace or step.target_type.value != "distance":
                continue
            minutes, seconds = (int(x) for x in pace.split(":"))
            pace_sec = minutes * 60 + seconds
            km = step.target_value / 1000.0
            expected = km * pace_sec / 60.0
            assert abs(expected - step.duration_min) < 0.15, (
                f"{workout.id} шаг {step.id}: {km:.2f} км @ {pace} = "
                f"{expected:.1f} мин, а в шаге {step.duration_min:.1f} мин"
            )
            checked += 1
    assert checked, "в неделе не нашлось шага с дистанцией и темпом"


def test_easy_pace_is_530_in_steps(season, planner):
    """Лёгкий бег идёт в темпе 5:30."""
    week = plan_from_macro(season, 4, planner, {})
    paces = set()
    for workout in week.workouts:
        for step in workout.steps:
            fv = step.focus_value or {}
            pace = fv.get("pace_min_per_km")
            zone = fv.get("zone")
            if pace and zone == "Z2":
                paces.add(pace)
    assert paces == {"5:30"}, f"темп лёгкого бега: {paces}"


def test_workout_names_describe_composition(season, planner):
    """Название тренировки — из её состава."""
    week = plan_from_macro(season, 4, planner, {})
    names = []
    for workout in week.workouts:
        name = (workout.objective or {}).get("name") or ""
        assert name, f"{workout.id}: у тренировки нет названия"
        assert "контрольной точке" not in name.lower(), \
            f"{workout.id}: в названии — цель недели: {name!r}"
        names.append(name)

    # В неделе есть и лёгкие пробежки, и длинный бег: названия разные.
    assert any("Длинный бег" in n for n in names), names
    assert any(n.startswith("Лёгкий бег") for n in names), names


def test_long_run_named_long_even_if_kind_is_easy(season, planner):
    """Длинный пробежек называется длинным, а не лёгким.

    Дефект: длинный пробежек приходил с видом работы `easy` (форма
    фазы не различает), и в названии вставало «Лёгкий бег» — или,
    наоборот, «Длинный бег» у лёгкой пробежки.
    """
    week = plan_from_macro(season, 4, planner, {})
    by_focus = {}
    for workout in week.workouts:
        by_focus[workout.focus] = by_focus.get(workout.focus, 0) + 1

    long_names = [n for n in by_focus if "Длинный бег" in n]
    assert long_names, f"в неделе нет длинного бега: {by_focus}"
    # Ровно одна длинная пробежка.
    assert sum(by_focus[n] for n in long_names) == 1, by_focus


def test_unplaced_focus_matches_workout_name(season, planner):
    """Висяк называется так же, как сама тренировка."""
    week = plan_from_macro(season, 4, planner, {})
    workout_focus = {w.request_id: w.focus for w in week.workouts}
    for request in week.unplaced:
        expected = workout_focus.get(request.id)
        if expected is None:
            continue
        assert request.focus == expected, (
            f"{request.id}: висяк «{request.focus}», "
            f"тренировка «{expected}»"
        )


def test_rationale_matches_workout_name(season, planner):
    """«Зачем» в карточке совпадает с названием тренировки.

    Фокус цели не знает, что в тренировке есть ОФП: в «зачем» стояло
    «easy · Лёгкий бег + отрезки», а сверху «Лёгкий бег + отрезки + ОФП».
    """
    week = plan_from_macro(season, 4, planner, {})
    for workout in week.workouts:
        if workout.rationale:
            assert workout.rationale == workout.focus, (
                f"{workout.id}: «зачем» {workout.rationale!r} ≠ "
                f"название {workout.focus!r}"
            )
