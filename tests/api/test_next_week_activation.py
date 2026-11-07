"""Тесты серверного правила: активация следующей недели.

Правило I45: планировать следующую неделю можно до закрытия текущей,
но активировать её — только после закрытия предыдущей.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    Assignment,
    Request,
    Season,
    Slot,
    Step,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import Sport, StepRole, TargetType, WeekStatus
from app.services.week_lifecycle import (
    TransitionError,
    activate_week,
    activation_blocker,
)

WEEK_START = date(2026, 10, 11)


def _step() -> Step:
    return Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)


def make_week(season_week: int, status: WeekStatus) -> Week:
    """Неделя сезона с одной тренировкой."""
    start = WEEK_START + timedelta(days=7 * (season_week - 1))
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    return Week(
        id=f"W{season_week}", plan_id="p1", season_week=season_week,
        start=start, end=start + timedelta(days=6),
        status=status, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN,
                          kind="easy", focus="base", steps=[_step()],
                          duration_min=60.0)],
        summary=WeekSummary(week_id=f"W{season_week}")
        if status is WeekStatus.CLOSED else None,
    )


# ------------------------------------------------------------------ домен


def test_i45_activation_blocked_while_earlier_week_is_not_closed():
    """I45: активировать нельзя, пока предыдущая неделя не закрыта."""
    current = make_week(4, WeekStatus.PROPOSED)
    earlier = [make_week(3, WeekStatus.ACTIVE)]

    assert activation_blocker(current, earlier) == "W3"
    with pytest.raises(TransitionError, match="W3"):
        activate_week(current, earlier)


def test_i45_activation_allowed_after_earlier_week_closed():
    """I45: закрыли предыдущую — активировать можно."""
    current = make_week(4, WeekStatus.PROPOSED)
    earlier = [make_week(3, WeekStatus.CLOSED)]

    assert activation_blocker(current, earlier) is None
    activated = activate_week(current, earlier)
    assert activated.status is WeekStatus.ACTIVE


def test_i45_activation_blocked_by_any_unclosed_earlier_week():
    """Блокирует любая не закрытая неделя впереди, а не только соседняя."""
    current = make_week(5, WeekStatus.PROPOSED)
    earlier = [make_week(3, WeekStatus.CLOSED), make_week(4, WeekStatus.ACTIVE)]

    assert activation_blocker(current, earlier) == "W4"
    with pytest.raises(TransitionError, match="W4"):
        activate_week(current, earlier)


def test_i45_week_itself_does_not_block():
    """Неделя не блокирует саму себя: смотрят только более ранние."""
    current = make_week(4, WeekStatus.PROPOSED)

    assert activation_blocker(current, [current]) is None
    assert activate_week(current, [current]).status is WeekStatus.ACTIVE


def test_i45_activation_without_earlier_weeks_is_allowed():
    """Первую неделю активировать можно: впереди ничего нет."""
    current = make_week(1, WeekStatus.PROPOSED)

    assert activation_blocker(current, []) is None
    assert activate_week(current, []).status is WeekStatus.ACTIVE


# ------------------------------------------------------------------ API


def _seed_two_weeks(root) -> None:
    """Две недели: W3 активна, W4 предложена. Плюс план с макро-неделями.

    План нужен: `propose_week` берёт объём из макро-плана сезона, а без
    активного плана неделя не собирается.
    """
    from app.domain.entities import Goal, MacroWeek, Plan
    from app.domain.enums import PlanStatus

    storage = FileStorage(root)
    goal = Goal(id="g1", discipline="run_10k", race_date=date(2027, 4, 18),
                metric_type="time_sec", metric_target=2400.0,
                target_friendly="40:00", venue="S25 Berlin 10K")
    plan = Plan(id="g1", status=PlanStatus.ACTIVE, goal=goal,
                period_start=WEEK_START, period_end=date(2027, 9, 12),
                macro_weeks=[
                    MacroWeek(season_week=season_week, phase_id="run_base",
                              focus="vo2max", goal_text="Развиваем VO2max",
                              run_km=56.0, total_h=7.21, sessions_target=9,
                              minutes_by_sport={"run": 300.0},
                              long_min=90, easy_min=150,
                              quality_min=60)
                    for season_week in (3, 4)
                ])
    storage.save(
        Season(id="S1", horizon_start=WEEK_START,
               horizon_end=date(2027, 9, 12), season_week_count=49,
               plans=[plan],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )
    storage.put_week(make_week(3, WeekStatus.ACTIVE),
                     expected_version=storage.version())
    storage.put_week(make_week(4, WeekStatus.PROPOSED),
                     expected_version=storage.version())


def test_activate_next_week_is_rejected_before_closing_previous(
    client: TestClient, data_root
):
    """Планировать можно, активировать — нет: предыдущая не закрыта."""
    _seed_two_weeks(data_root)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "act-4", "type": "activate_week",
        "args": {"season_week": 4}, "reason": "активирую неделю",
        "expected_version": version,
    })
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_command"
    assert "W3" in body["error"]["message"]

    week = client.get("/api/v1/week/4").json()["data"]
    assert week["status"] == "proposed", "неделя не изменилась"


def test_week_response_reports_activation_block(
    client: TestClient, data_root
):
    """Ответ недели говорит, что активация закрыта, и кем."""
    _seed_two_weeks(data_root)

    week = client.get("/api/v1/week/4").json()["data"]
    assert week["can_activate"] is False
    assert week["activate_blocked_by"] == "W3"


def test_week_response_allows_activation_when_previous_closed(
    client: TestClient, data_root
):
    """Предыдущая закрыта — активация разрешена."""
    _seed_two_weeks(data_root)
    storage = FileStorage(data_root)
    week3 = storage.week(3)
    assert week3 is not None
    week3.status = WeekStatus.CLOSED
    week3.summary = WeekSummary(week_id="W3")
    storage.put_week(week3, expected_version=storage.version())

    week = client.get("/api/v1/week/4").json()["data"]
    assert week["can_activate"] is True
    assert week["activate_blocked_by"] is None


def test_activate_next_week_works_after_closing_previous(
    client: TestClient, data_root
):
    """Полный путь: закрыли W3 — активировали W4."""
    _seed_two_weeks(data_root)
    storage = FileStorage(data_root)
    week3 = storage.week(3)
    assert week3 is not None
    week3.status = WeekStatus.CLOSED
    week3.summary = WeekSummary(week_id="W3")
    storage.put_week(week3, expected_version=storage.version())

    version = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "act-4", "type": "activate_week",
        "args": {"season_week": 4}, "reason": "активирую неделю",
        "expected_version": version,
    })
    assert response.status_code == 200
    assert client.get("/api/v1/week/4").json()["data"]["status"] == "active"


def test_propose_next_week_allowed_before_closing_previous(
    client: TestClient, data_root
):
    """Планировать следующую неделю можно до закрытия текущей.

    Это и есть новая возможность: `propose_week` не блокируется
    правилом активации — блокируется только `activate_week`.
    """
    _seed_two_weeks(data_root)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "prop-4", "type": "propose_week",
        "args": {"season_week": 4}, "reason": "планирую следующую неделю",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/week/4").json()["data"]["status"] == "proposed"


def test_season_response_carries_week_dates(client: TestClient, data_root):
    """В ответе сезона — даты недель: клиент не считает их сам."""
    _seed_two_weeks(data_root)

    data = client.get("/api/v1/season").json()["data"]
    weeks = {w["season_week"]: w for w in data["macro_weeks"]}
    assert set(weeks) == {3, 4}

    week = weeks[4]
    assert week["start"] == "2026-11-01"
    assert week["end"] == "2026-11-07"
