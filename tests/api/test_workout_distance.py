"""Километраж тренировки в плане.

Кирилл: «в плашке тренировки минуты, а не километры. Мне не хватает
километража основной работы — длинные тренировки хочу видеть в
километрах, а не только в минутах».

Километраж плана считается по шагам с дистанцией: шаг планировщика
знает метры, а тренировка их не хранит. Проверяем доменную функцию и
то, что она доезжает до API.
"""
from __future__ import annotations

from datetime import date

from app.domain.derivations import workout_distance_m
from app.domain.entities import (
    Assignment,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import Sport, StepRole, TargetType, WeekStatus


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
