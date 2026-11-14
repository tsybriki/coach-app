"""Километраж тренировки в плане.

Кирилл: «в плашке тренировки минуты, а не километры. Мне не хватает
километража основной работы — длинные тренировки хочу видеть в
километрах, а не только в минутах».

Километраж плана считается по шагам с дистанцией: шаг планировщика
знает метры, а тренировка их не хранит. Проверяем доменную функцию и
то, что она доезжает до API.

Правило одно и для планировщика, и для разбора текста: **круг = работа
+ отдых**. «6 по 200 через 200» — это 6 × 400 = 2400 м, а не 1200.
Отдых на бегу — пройденные метры, и итог должен совпадать с фактом.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domain.composition import WorkoutIntent, build_steps
from app.domain.derivations import workout_distance_m
from app.domain.entities import (
    Assignment,
    Athlete,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import Sport, StepRole, TargetType, WeekStatus

PACE = {"E": 330.0, "T": 240.0, "I": 220.0, "R": 200.0, "M": 270.0}


def make_step(step_id: str, target_type: TargetType, value: float,
              role: StepRole = StepRole.WORK) -> Step:
    return Step(id=step_id, role=role, sport=Sport.RUN,
                target_type=target_type, target_value=value,
                duration_min=30.0)


def make_workout(steps: list[Step]) -> Workout:
    return Workout(id="w1", request_id="r1", sport=Sport.RUN, kind="long",
                   focus="long", steps=steps, duration_min=77.0,
                   time="10:00")


def test_distance_sums_distance_steps():
    """Километраж — сумма шагов с дистанцией."""
    workout = make_workout([
        make_step("s1", TargetType.DISTANCE, 12000.0),
        make_step("s2", TargetType.DISTANCE, 100.0, StepRole.REST),
        make_step("s3", TargetType.DISTANCE, 1900.0),
    ])

    assert workout_distance_m(workout) == 14000.0


def test_distance_ignores_time_steps():
    """Шаги без дистанции (разминка по времени, силовая) не дают метров."""
    workout = make_workout([
        make_step("s1", TargetType.DISTANCE, 12000.0),
        make_step("s2", TargetType.TIME, 15.0, StepRole.WARMUP),
        make_step("s3", TargetType.REPS, 3.0),
    ])

    assert workout_distance_m(workout) == 12000.0


def test_distance_of_workout_without_distance_steps_is_zero():
    """Нет шагов с дистанцией — ноль: дистанция не задана."""
    workout = make_workout([make_step("s1", TargetType.TIME, 60.0)])

    assert workout_distance_m(workout) == 0.0


def test_distance_of_missing_workout_is_zero():
    assert workout_distance_m(None) == 0.0


def _athlete() -> Athlete:
    return Athlete(
        vdot=50.0,
        hr_zones={"Z2": (111, 130), "Z5": (159, 168), "Z7": (172, 182)},
        hr_max=182, rhr=50, lth=164,
    )


def test_distance_of_composed_set_counts_rest():
    """Дистанция набора из разбора — работа ПЛЮС отдых.

    «6 по 200 через 200» = 6 × (200 + 200) = 2400 м.
    """
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=200.0,
        intent="interval",
        label="Интервалы",
        reps=6,
        rest_type=TargetType.DISTANCE,
        rest_value=200.0,
    )]
    composition = build_steps(intents, athlete=_athlete(), pace_by_zone=PACE)
    workout = Workout(
        id="w1", request_id="r1", sport=Sport.RUN, kind="composed",
        focus="Интервалы", steps=[s.step for s in composition.steps],
        duration_min=composition.duration_min,
    )

    assert workout_distance_m(workout) == 2400.0


def test_duration_of_composed_set_counts_rest():
    """Время набора из разбора — работа ПЛЮС отдых."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=200.0,
        intent="interval",
        label="Интервалы",
        reps=6,
        rest_type=TargetType.DISTANCE,
        rest_value=200.0,
    )]
    composition = build_steps(intents, athlete=_athlete(), pace_by_zone=PACE)

    work_min = sum(
        s.step.duration_min for s in composition.steps
        if s.step.role is StepRole.WORK
    )
    rest_min = sum(
        s.step.duration_min for s in composition.steps
        if s.step.role is StepRole.REST
    )
    assert work_min > 0
    assert rest_min > 0
    assert composition.duration_min == pytest.approx(work_min + rest_min)


def test_planner_and_composer_agree_on_set_distance():
    """Планировщик и разбор считают объём набора одинаково.

    Набор из методики: «6 по 200 через 200». Планировщик собирает его из
    рецепта, разбор — из намерения модели. Объём должен совпасть.
    """
    from app.adapters.daniels import load_paces
    from app.domain.methodology import (
        RecipeSegment,
        RecipeSet,
        WorkoutRecipe,
    )
    from app.domain.methodology import build_steps as build_recipe_steps

    workout_recipe = WorkoutRecipe(
        kind="R",
        label="Работа в повторном темпе",
        sets=(RecipeSet(
            reps_min=6, reps_max=6,
            segments=(
                RecipeSegment(zone="R", distance_m=200.0),
                RecipeSegment(zone="E", distance_m=200.0),
            ),
            label="6×200м через 200м",
        ),),
    )
    paces = load_paces(
        Path(__file__).resolve().parent.parent.parent / "reference" / "daniels"
    ).pace_by_zone(50)
    planner_steps = build_recipe_steps(workout_recipe, paces, _athlete())

    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=200.0,
        intent="interval",
        label="Интервалы",
        reps=6,
        rest_type=TargetType.DISTANCE,
        rest_value=200.0,
    )]
    composed = build_steps(intents, athlete=_athlete(), pace_by_zone=paces)

    planner_m = sum(
        s.target_value for s in planner_steps
        if s.target_type is TargetType.DISTANCE
    )
    composed_m = sum(
        s.step.target_value for s in composed.steps
        if s.step.target_type is TargetType.DISTANCE
    )
    assert planner_m == composed_m == 2400.0


def test_api_returns_planned_distance(client, data_root):
    """В ответе недели тренировка отдаёт километраж плана."""
    from app.adapters.storage.files import FileStorage

    storage = FileStorage(data_root)
    steps = [
        make_step("s1", TargetType.DISTANCE, 12000.0),
        make_step("s2", TargetType.TIME, 15.0, StepRole.WARMUP),
    ]
    request = Request(id="r1", sport=Sport.RUN, kind="long", focus="long",
                      duration_min=77)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.PROPOSED, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="10:00",
                                duration_min=77)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN,
                          kind="long", focus="long", steps=steps,
                          duration_min=77.0, time="10:00")],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[],
               slots=[Slot(id="s1", day=6, start="10:00", end="11:00",
                           capacity_min=60)]),
        expected_version=0,
    )
    storage.put_week(week, expected_version=1)

    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    workouts = response.json()["data"]["workouts"]

    assert workouts[0]["distance_m"] == 12000.0


def test_api_returns_zero_distance_when_steps_have_none(client, data_root):
    """Тренировка без дистанции — distance_m = 0, а не выдуманные метры."""
    from app.adapters.storage.files import FileStorage

    storage = FileStorage(data_root)
    request = Request(id="r1", sport=Sport.BIKE, kind="bike", focus="easy",
                      duration_min=60)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.PROPOSED, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.BIKE,
                          kind="bike", focus="easy",
                          steps=[make_step("s1", TargetType.TIME, 60.0)],
                          duration_min=60.0, time="18:45")],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )
    storage.put_week(week, expected_version=1)

    response = client.get("/api/v1/week/1")
    workouts = response.json()["data"]["workouts"]

    assert workouts[0]["distance_m"] == 0.0
