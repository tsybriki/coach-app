"""Отвязка тренировок без факта через API.

Два действия:

- `unplace_all` — «Отвязать все»: тренировки без факта теряют слоты,
  неделя остаётся активной. Полезно, когда нужно поменять дни.
- `replan_remainder` — то же, но неделя возвращается в `proposed`.

Оба **не пересобирают план**: тренировки те же, меняются привязки.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    ActualSession,
    Assignment,
    Goal,
    MacroWeek,
    Phase,
    Plan,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FactSource,
    PlanStatus,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
    WorkoutStatus,
)


def _seed(root: Path) -> int:
    """Активная неделя: одна тренировка выполнена, другая — нет."""
    storage = FileStorage(root)
    goal = Goal(id="g1", discipline="run_10k", race_date=date(2027, 4, 18),
                metric_type="time_sec", metric_target=2400.0,
                target_friendly="40:00", venue="S25 Berlin 10K")
    plan = Plan(
        id="g1", status=PlanStatus.ACTIVE, goal=goal,
        period_start=date(2026, 10, 11), period_end=date(2027, 9, 12),
        phases=[Phase(id="run_base", objective="Поднимаем базовый объём",
                      load_range=(4.96, 9.74), volume_range=(27.0, 50.0))],
        macro_weeks=[
            MacroWeek(season_week=1, phase_id="run_base",
                      focus="progression", goal_text="Развиваем базу",
                      run_km=27.0, total_h=4.99, sessions_target=6,
                      minutes_by_sport={"run": 299.0}, long_min=90,
                      easy_min=209, easy_runs=5),
        ],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49,
               plans=[plan],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90),
                      Slot(id="s2", day=2, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )

    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0,
                duration_min=60.0)
    done_request = Request(id="r-done", sport=Sport.RUN, kind="easy",
                            focus="base", duration_min=60)
    planned_request = Request(id="r-planned", sport=Sport.RUN, kind="easy",
                               focus="base", duration_min=60)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.ACTIVE,
        requests=[done_request, planned_request],
        assignments=[
            Assignment(request_id="r-done", slot_id="s1", start="18:45",
                       duration_min=60),
            Assignment(request_id="r-planned", slot_id="s2", start="18:45",
                       duration_min=60),
        ],
        workouts=[
            Workout(id="w-done", request_id="r-done", sport=Sport.RUN,
                    kind="easy", focus="base",
                    objective={"name": "Лёгкий бег", "day": 1,
                               "slot_id": "s1"},
                    steps=[step], duration_min=60.0, time="18:45",
                    actual_id="a1", status=WorkoutStatus.DONE),
            Workout(id="w-planned", request_id="r-planned", sport=Sport.RUN,
                    kind="easy", focus="base",
                    objective={"name": "Лёгкий бег", "day": 2,
                               "slot_id": "s2"},
                    steps=[step], duration_min=60.0, time="18:45"),
        ],
    )
    version = storage.put_week(week, expected_version=1)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 12), sport=Sport.RUN, duration_min=60,
        distance_m=10000.0, source=FactSource.GARMIN, external_id="ext-1",
        linked_workout_id="w-done"))
    return version


def _command(client: TestClient, cid: str, ctype: str, version: int,
             season_week: int = 1):
    return client.post("/api/v1/commands", json={
        "id": cid, "type": ctype,
        "args": {"season_week": season_week}, "reason": f"проверка {ctype}",
        "expected_version": version,
    })


def _week(client: TestClient) -> dict:
    return client.get("/api/v1/week/1").json()["data"]


# ------------------------------------------------------------------ unplace_all


def test_unplace_all_unplaces_workout_without_fact(
    client: TestClient, data_root: Path
):
    """Тренировка без факта теряет слот и становится висяком."""
    version = _seed(data_root)

    response = _command(client, "unplace-1", "unplace_all", version)
    assert response.status_code == 200, response.text

    week = _week(client)
    assert "r-planned" in {u["id"] for u in week["unplaced"]}
    assert "r-planned" not in {a["request_id"] for a in week["assignments"]}


def test_unplace_all_keeps_week_active(
    client: TestClient, data_root: Path
):
    """Отвязка — не перепланирование: неделя остаётся активной."""
    version = _seed(data_root)
    _command(client, "unplace-1", "unplace_all", version)

    assert _week(client)["status"] == "active"


def test_unplace_all_keeps_workout_with_fact(
    client: TestClient, data_root: Path
):
    """Выполненная тренировка остаётся на своём месте."""
    version = _seed(data_root)
    _command(client, "unplace-1", "unplace_all", version)

    week = _week(client)
    done = [w for w in week["workouts"] if w["actual_id"] == "a1"]
    assert len(done) == 1, "тренировка с фактом потерялась"
    assert done[0]["day"], "у выполненной тренировки потерялся день"
    assert "r-done" in {a["request_id"] for a in week["assignments"]}


def test_unplace_all_does_not_rebuild_plan(
    client: TestClient, data_root: Path
):
    """План не пересобирается: тренировки те же самые.

    Пересборка по правилам создавала неделю заново — а пользователь
    просил отвязать тренировки, чтобы двигать их.
    """
    version = _seed(data_root)
    _command(client, "unplace-1", "unplace_all", version)

    week = _week(client)
    assert {w["id"] for w in week["workouts"]} == {"w-done", "w-planned"}
    assert len(week["workouts"]) == 2, "план пересобран"


def test_unplace_all_on_closed_week_is_rejected(
    client: TestClient, data_root: Path
):
    """Закрытая неделя не отвязывается."""
    version = _seed(data_root)
    _command(client, "unplace-1", "unplace_all", version)
    version = client.get("/api/v1/snapshot").json()["version"]
    _command(client, "replan-1", "replan_remainder", version)
    version = client.get("/api/v1/snapshot").json()["version"]
    _command(client, "act-1", "activate_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]
    _command(client, "close-1", "close_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = _command(client, "unplace-2", "unplace_all", version)
    assert response.status_code == 400
    assert "закрыт" in response.json()["error"]["message"]


# ------------------------------------------------------------------ replan


def test_replan_remainder_does_not_rebuild_plan(
    client: TestClient, data_root: Path
):
    """Переплан отвязывает тренировки, но не создаёт новые."""
    version = _seed(data_root)

    _command(client, "replan-1", "replan_remainder", version)

    week = _week(client)
    assert len(week["workouts"]) == 2, "план пересобран — тренировок стало больше"
    assert {w["id"] for w in week["workouts"]} == {"w-done", "w-planned"}


def test_replan_remainder_unplaces_workout_without_fact(
    client: TestClient, data_root: Path
):
    """Невыполненная тренировка теряет слот — её можно двигать."""
    version = _seed(data_root)
    _command(client, "replan-1", "replan_remainder", version)

    week = _week(client)
    assert "r-planned" in {u["id"] for u in week["unplaced"]}
    assert "r-planned" not in {a["request_id"] for a in week["assignments"]}


def test_replan_remainder_returns_week_to_proposed(
    client: TestClient, data_root: Path
):
    """После переплана неделя снова proposed."""
    version = _seed(data_root)
    _command(client, "replan-1", "replan_remainder", version)

    assert _week(client)["status"] == "proposed"


def test_replan_remainder_result_can_be_activated(
    client: TestClient, data_root: Path
):
    """После переплана неделю можно активировать — обычный режим."""
    version = _seed(data_root)
    _command(client, "replan-1", "replan_remainder", version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = _command(client, "act-1", "activate_week", version)
    assert response.status_code == 200, response.text
    assert _week(client)["status"] == "active"
