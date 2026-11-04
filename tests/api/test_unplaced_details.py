"""Непривязанная тренировка отдаётся с деталями.

Дефект, который это ловит: висяк приходил строкой «Лёгкий бег, 46
мин» — без названия, без структуры, без шагов. По нему нельзя было
открыть экран деталей: пользователь решал, куда поставить тренировку,
не видя, что в ней.

Теперь у висяка есть всё, что есть у размещённой тренировки: название,
объект, шаги, «зачем».
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)


def _seed_unplaced(root) -> None:
    """Неделя с одной непривязанной тренировкой."""
    storage = FileStorage(root)
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.DISTANCE, target_value=7000.0,
                focus_value={"zone": "Z2", "pace_min_per_km": "5:30"},
                duration_min=42.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy",
                      focus="Лёгкий бег", duration_min=42)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.PROPOSED,
        requests=[request],
        assignments=[],
        unplaced=[request],
        workouts=[Workout(
            id="w1", request_id="r1", sport=Sport.RUN, kind="easy",
            focus="Лёгкий бег", objective={"name": "Лёгкий бег"},
            steps=[step], duration_min=42.0, rationale="Лёгкий бег")],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )
    storage.put_week(week, expected_version=1)


def test_unplaced_has_name_and_steps(client: TestClient, data_root):
    """У висяка есть название и шаги."""
    _seed_unplaced(data_root)
    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    unplaced = response.json()["data"]["unplaced"]
    assert len(unplaced) == 1, "висяк не отдан"
    entry = unplaced[0]
    assert entry["name"] == "Лёгкий бег", entry
    assert entry["steps"], "у висяка нет шагов"
    assert entry["steps"][0]["target_value"] == 7000.0
    assert entry["steps"][0]["focus_value"]["pace_min_per_km"] == "5:30"


def test_unplaced_has_objective_and_rationale(client: TestClient, data_root):
    """У висяка есть объект и «зачем» — как у размещённой тренировки."""
    _seed_unplaced(data_root)
    response = client.get("/api/v1/week/1")
    unplaced = response.json()["data"]["unplaced"][0]
    assert unplaced["objective"]["name"] == "Лёгкий бег", unplaced
    assert unplaced["rationale"] == "Лёгкий бег", unplaced


def test_unplaced_duration_matches_steps(client: TestClient, data_root):
    """Длительность висяка — та же, что у его тренировки.

    Иначе в списке и в деталях показываются разные минуты.
    """
    _seed_unplaced(data_root)
    response = client.get("/api/v1/week/1")
    week = response.json()["data"]
    unplaced = week["unplaced"][0]
    steps_sum = sum(s["duration_min"] for s in unplaced["steps"])
    assert abs(steps_sum - unplaced["duration_min"]) < 0.01, unplaced


def test_unplaced_matches_its_workout(client: TestClient, data_root):
    """Висяк и его тренировка — одно и то же.

    Иначе карточка в списке и детали показывают разное: одно название
    в списке висяков и другое в экране тренировки.
    """
    _seed_unplaced(data_root)
    response = client.get("/api/v1/week/1")
    week = response.json()["data"]
    unplaced = week["unplaced"][0]
    workout = next(w for w in week["workouts"]
                   if w["request_id"] == unplaced["id"])
    assert unplaced["name"] == workout["objective"]["name"]
    assert unplaced["duration_min"] == workout["duration_min"]
    assert len(unplaced["steps"]) == len(workout["steps"])


def test_unplaced_without_workout_still_returns(client: TestClient, data_root):
    """Висяк без тренировки не роняет ответ.

    Страховка: если тренировки нет, висяк всё равно должен прийти —
    хотя бы именем и длительностью.
    """
    storage = FileStorage(data_root)
    _seed_unplaced(data_root)
    week = storage.week(1)
    assert week is not None
    week.workouts = []
    storage.put_week(week, expected_version=storage.version())

    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    unplaced = response.json()["data"]["unplaced"]
    assert len(unplaced) == 1
    assert unplaced[0]["name"] == "Лёгкий бег"
    assert unplaced[0]["steps"] == []
