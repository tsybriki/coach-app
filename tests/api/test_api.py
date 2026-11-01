"""Тесты BFF: маршруты, форматы ответов, команды.

Проверяется контракт HTTP: форма ответа, коды ошибок, идемпотентность,
деградация. Доменная логика проверяется отдельно.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    Assignment,
    Athlete,
    Goal,
    MacroWeek,
    Phase,
    Plan,
    Request,
    Season,
    Slot,
    Step,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import (
    PlanStatus,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    shutil.rmtree(root, ignore_errors=True)
    return root


@pytest.fixture
def client(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Клиент с чистым хранилищем и без Garmin.

    Garmin в тестах не нужен: адаптер ходит в сеть. Источник активностей
    подменяется заглушкой — проверка деградации должна быть быстрой
    и без внешних зависимостей.
    """
    monkeypatch.setenv("COACH_APP_DATA", str(data_root))

    # Контейнер собирается в lifespan — подмена класса до старта.
    from app.api import dependencies
    from app.main import create_app

    monkeypatch.setattr(dependencies, "GarminActivityPort",
                        dependencies.UnavailableActivityPort)

    with TestClient(create_app()) as test_client:
        yield test_client


def seed_week(root: Path) -> int:
    """Положить неделю в хранилище. Вернуть версию."""
    storage = FileStorage(root)
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.PROPOSED, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN, kind="easy",
                          focus="base", steps=[step], duration_min=60.0,
                          time="18:45")],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )
    return storage.put_week(week, expected_version=1)


def seed_macro_plan(root: Path) -> int:
    """Положить сезон с макро-планом: фазы и недели.

    Макро-план нужен вкладке «Сезон»: без него нечего показывать.
    """
    storage = FileStorage(root)
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[]),
        expected_version=0,
    )
    goal = Goal(id="g1", discipline="run_10k", race_date=date(2027, 4, 18),
                metric_type="time_sec", metric_target=2400.0,
                target_friendly="40:00", venue="S25 Berlin 10K")
    plan = Plan(
        id="g1", status=PlanStatus.ACTIVE, goal=goal,
        period_start=date(2026, 10, 11), period_end=date(2027, 9, 12),
        phases=[
            Phase(id="run_base", objective="Поднимаем базовый объём",
                  load_range=(4.96, 9.74), volume_range=(27.0, 50.0)),
            Phase(id="run_taper", objective="Снижаем объём"),
        ],
        macro_weeks=[
            MacroWeek(season_week=1, phase_id="run_base",
                      focus="progression", goal_text="Развиваем базу",
                      run_km=27.0, total_h=4.99, sessions_target=6),
            MacroWeek(season_week=2, phase_id="run_base",
                      focus="vo2max", goal_text="Развиваем VO2max",
                      run_km=35.0, total_h=6.24, sessions_target=7),
            MacroWeek(season_week=3, phase_id="run_taper",
                      focus="taper_race_pace", goal_text="Снимаем объём",
                      run_km=16.0, total_h=3.15, sessions_target=5,
                      deload=True),
        ],
    )
    return storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49,
               plans=[plan]),
        expected_version=storage.version(),
    )


def seed_stored_week(storage: FileStorage, season_week: int,
                     status: WeekStatus) -> None:
    """Положить неделю в хранилище с нужным статусом."""
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    week = Week(
        id=f"W{season_week}", plan_id="p1", season_week=season_week,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=status, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN, kind="easy",
                          focus="base", steps=[step], duration_min=60.0)],
        summary=WeekSummary(week_id=f"W{season_week}")
        if status is WeekStatus.CLOSED else None,
    )
    storage.put_week(week, expected_version=storage.version())


# ------------------------------------------------------------------ чтение


def test_health(client: TestClient):
    """health отвечает и не содержит данных."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "data" not in body


def test_snapshot_shape(client: TestClient):
    """snapshot: версия + сезон + атлет."""
    response = client.get("/api/v1/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    assert "season" in body["data"]
    assert "athlete" in body["data"]


def test_missing_week_returns_404(client: TestClient):
    """Нет недели → 404 с кодом ошибки."""
    response = client.get("/api/v1/week/1")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "version" in body


def test_week_returns_data(client: TestClient, data_root: Path):
    """Неделя отдаётся со тренировками и шагами."""
    seed_week(data_root)
    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    week = response.json()["data"]
    assert week["status"] == "proposed"
    assert len(week["workouts"]) == 1
    assert len(week["workouts"][0]["steps"]) == 1


def test_workout_has_day_and_date_from_its_slot(client: TestClient, data_root: Path):
    """У тренировки есть день недели и дата — из окна, в которое она попала.

    Неделя начинается в воскресенье: 11.10.2026 — W1. Окно `s1` стоит в
    понедельник (day=1), значит тренировка в ПН, 12.10.2026.
    """
    seed_week(data_root)
    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    workout = response.json()["data"]["workouts"][0]
    assert workout["day"] == "ПН"
    assert workout["date"] == "2026-10-12"
    assert workout["slot_id"] == "s1"
    # То же самое в objective: клиент берёт день и дату оттуда.
    assert workout["objective"]["day"] == "ПН"
    assert workout["objective"]["date"] == "2026-10-12"


def test_workout_without_slot_has_no_day(client: TestClient, data_root: Path):
    """Висяк (тренировка без окна) не получает чужой день и дату.

    Окна нет — значит и дня нет: показывать дату, выдуманную по умолчанию,
    хуже, чем не показывать ничего.
    """
    seed_week(data_root)
    storage = FileStorage(data_root)
    week = storage.week(1)
    assert week is not None
    # Убираем размещение: тренировка остаётся, окна у неё больше нет.
    week.assignments = []
    storage.put_week(week, expected_version=storage.version())

    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    workout = response.json()["data"]["workouts"][0]
    assert workout["day"] == ""
    assert workout["date"] == ""
    assert workout["slot_id"] == ""


def test_slots_endpoint_lists_training_windows(client: TestClient, data_root: Path):
    """Окна тренировок отдаются отдельным маршрутом — для карточки атлета."""
    seed_week(data_root)
    response = client.get("/api/v1/slots")
    assert response.status_code == 200
    slots = response.json()["data"]["slots"]
    assert len(slots) == 1
    slot = slots[0]
    assert slot["id"] == "s1"
    assert slot["day"] == 1
    assert slot["day_name"] == "ПН"
    assert slot["start"] == "18:45"
    assert slot["end"] == "20:15"
    assert slot["capacity_min"] == 90


def test_numeric_day_in_objective_is_normalised(client: TestClient, data_root: Path):
    """`objective.day` с номером дня нормализуется в название.

    В данных `objective.day` лежит номер (0 — воскресенье): на экране нужен
    «ВС», а не «0». Нормализует API — на границе, где внешние данные
    превращаются в доменные.
    """
    seed_week(data_root)
    storage = FileStorage(data_root)
    week = storage.week(1)
    assert week is not None
    week.workouts[0].objective = {"name": "Вел 60мин", "day": 2}
    storage.put_week(week, expected_version=storage.version())

    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    workout = response.json()["data"]["workouts"][0]
    assert workout["objective"]["day"] == "ВТ"
    assert workout["day"] == "ПН"


def test_slots_endpoint_without_slots_is_empty(client: TestClient):
    """Без окон ответ — пустой список, а не ошибка."""
    response = client.get("/api/v1/slots")
    assert response.status_code == 200
    assert response.json()["data"]["slots"] == []


def test_athlete_form_is_translated(client: TestClient, data_root: Path):
    """Состояние атлета — по-русски, а не кодом из пайплайна.

    `recovering_after_back_injury` на экране читается как ошибка, а не как
    состояние. Код остаётся рядом, в `form_code`.
    """
    storage = FileStorage(data_root)
    storage.update_athlete(Athlete(
        vdot=51.0,
        hr_zones={"Z1": (100, 118), "Z2": (118, 135)},
        hr_max=182, rhr=54, lth=164, weight_kg=101.7,
        form="recovering_after_back_injury",
    ))

    response = client.get("/api/v1/athlete")
    assert response.status_code == 200
    athlete = response.json()["data"]
    assert athlete["form"] == "Восстановление после травмы спины"
    assert athlete["form_code"] == "recovering_after_back_injury"


def test_etag_present(client: TestClient):
    """Ответ несёт ETag по версии."""
    response = client.get("/api/v1/snapshot")
    assert response.headers.get("ETag")


def test_current_week_counts_from_season_start(client: TestClient, data_root: Path):
    """Текущая неделя считается от даты старта сезона — не хардкодом.

    Неделя начинается в воскресенье: 11.10.2026 — W1, значит 18.10 — W2,
    25.10 — W3.
    """
    seed_week(data_root)
    container = client.app.state.container

    from datetime import date

    class FixedClock:
        def __init__(self, day: date) -> None:
            self._day = day

        def now(self) -> date:
            return self._day

    for day, expected in [(date(2026, 10, 11), 1), (date(2026, 10, 17), 1),
                          (date(2026, 10, 18), 2), (date(2026, 10, 25), 3),
                          (date(2026, 10, 31), 3), (date(2026, 11, 1), 4)]:
        container.clock = FixedClock(day)
        response = client.get("/api/v1/current-week")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["season_week"] == expected, f"{day} → W{expected}"
        assert data["today"] == day.isoformat()


def test_current_week_before_season_start_is_first(client: TestClient, data_root: Path):
    """До старта сезона — первая неделя."""
    seed_week(data_root)
    container = client.app.state.container

    from datetime import date

    class FixedClock:
        def now(self) -> date:
            return date(2026, 10, 1)

    container.clock = FixedClock()
    response = client.get("/api/v1/current-week")
    assert response.json()["data"]["season_week"] == 1


def test_athlete_and_season(client: TestClient):
    """Профиль и скелет сезона отдаются."""
    assert client.get("/api/v1/athlete").status_code == 200
    response = client.get("/api/v1/season")
    assert response.status_code == 200
    assert "horizon" in response.json()["data"]


# ------------------------------------------------------------------ команды


def test_command_applies(client: TestClient, data_root: Path):
    """Команда применяется и возвращает diff."""
    version = seed_week(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "activate_week",
        "args": {"season_week": 1}, "reason": "включаю неделю",
        "expected_version": version,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "applied"
    assert body["data"]["diff"]

    week = client.get("/api/v1/week/1").json()["data"]
    assert week["status"] == "active"


def test_command_is_idempotent(client: TestClient, data_root: Path):
    """Повтор с тем же id не применяет команду второй раз."""
    version = seed_week(data_root)
    payload = {
        "id": "cmd-1", "type": "activate_week",
        "args": {"season_week": 1}, "reason": "включаю неделю",
        "expected_version": version,
    }
    first = client.post("/api/v1/commands", json=payload)
    second = client.post("/api/v1/commands", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"].get("replayed") is True


def test_command_with_stale_version_returns_409(client: TestClient, data_root: Path):
    """Устаревшая версия → 409 и текущий снапшот в ответе."""
    seed_week(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "activate_week",
        "args": {"season_week": 1}, "reason": "включаю", "expected_version": 1,
    })
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "version_conflict"
    assert "version" in body


def test_unknown_command_type_returns_400(client: TestClient, data_root: Path):
    """Неизвестный тип команды → 400."""
    seed_week(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "выдумка", "args": {}, "reason": "проверка",
        "expected_version": 2,
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_command"


def test_command_without_reason_is_rejected(client: TestClient, data_root: Path):
    """Команда без причины не принимается."""
    seed_week(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "activate_week",
        "args": {"season_week": 1}, "reason": "", "expected_version": 2,
    })
    assert response.status_code == 422


def test_pull_fact_degrades_when_garmin_unavailable(client: TestClient, data_root: Path):
    """Garmin недоступен → degraded, не 500."""
    seed_week(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "pull_fact",
        "args": {"season_week": 1}, "reason": "загрузить факт",
        "expected_version": 2,
    })
    assert response.status_code == 503


# ------------------------------------------------------------------ макро-план


def test_season_serves_macro_plan(client: TestClient, data_root: Path):
    """Вкладка «Сезон» получает макро-план: фазы и недели целиком."""
    seed_macro_plan(data_root)
    response = client.get("/api/v1/season")
    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data["macro_weeks"]) == 3, "не все недели макро-плана отданы"
    week = data["macro_weeks"][0]
    assert week["season_week"] == 1
    assert week["phase_id"] == "run_base"
    assert week["goal_text"] == "Развиваем базу"
    assert week["run_km"] == 27.0
    assert week["total_h"] == 4.99
    assert week["sessions_target"] == 6
    assert week["status"] is None, "будущей недели нет в хранилище"
    assert week["has_fact"] is False

    phases = {p["id"]: p for p in data["phases"]}
    assert set(phases) == {"run_base", "run_taper"}
    assert phases["run_base"]["objective"] == "Поднимаем базовый объём"
    assert phases["run_base"]["week_from"] == 1
    assert phases["run_base"]["week_to"] == 2
    assert phases["run_taper"]["week_from"] == 3


def test_season_marks_closed_week_with_fact(client: TestClient, data_root: Path):
    """Закрытая неделя в макро-плане: помечена и помечена как с фактом."""
    seed_macro_plan(data_root)
    storage = FileStorage(data_root)
    seed_stored_week(storage, 1, WeekStatus.CLOSED)

    data = client.get("/api/v1/season").json()["data"]
    first = data["macro_weeks"][0]
    assert first["status"] == "closed"
    assert first["has_fact"] is True

    others = data["macro_weeks"][1:]
    assert all(w["has_fact"] is False for w in others), (
        "у будущей недели факта быть не может")


def test_season_without_macro_plan_is_empty(client: TestClient, data_root: Path):
    """Сезон без макро-плана — пустой список, не ошибка."""
    seed_week(data_root)
    data = client.get("/api/v1/season").json()["data"]
    assert data["macro_weeks"] == []
    assert data["phases"] == []


def test_season_survives_macro_plan_roundtrip(client: TestClient, data_root: Path):
    """Макро-план переживает запись и чтение: фазы и недели на месте."""
    seed_macro_plan(data_root)
    storage = FileStorage(data_root)
    loaded = storage.load()
    plan = loaded.plans[0]

    assert len(plan.phases) == 2
    assert plan.phases[0].objective == "Поднимаем базовый объём"
    assert plan.phases[0].load_range == (4.96, 9.74)
    assert plan.phases[0].volume_range == (27.0, 50.0)
    assert len(plan.macro_weeks) == 3
    assert plan.macro_weeks[2].deload is True
    week_two = plan.macro_week(2)
    assert week_two is not None
    assert week_two.goal_text == "Развиваем VO2max"
    assert plan.macro_week(99) is None
    taper = plan.phase_by_id("run_taper")
    assert taper is not None
    assert taper.objective == "Снижаем объём"
    assert plan.phase_by_id("нет") is None


# ------------------------------------------------------------------ жизненный цикл


def _command(client: TestClient, cid: str, ctype: str, version: int,
             season_week: int = 1):
    """Команда с причиной — команды без причины не принимаются."""
    return client.post("/api/v1/commands", json={
        "id": cid, "type": ctype,
        "args": {"season_week": season_week}, "reason": f"проверка {ctype}",
        "expected_version": version,
    })


def test_close_week_requires_active_week(client: TestClient, data_root: Path):
    """Закрыть proposed-неделю нельзя — понятный отказ, не 500."""
    version = seed_week(data_root)
    response = _command(client, "close-1", "close_week", version)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_command"
    assert "active" in body["error"]["message"]

    week = client.get("/api/v1/week/1").json()["data"]
    assert week["status"] == "proposed", "неделя не изменилась"


def test_activate_then_close_works(client: TestClient, data_root: Path):
    """Полный путь: proposed → active → closed."""
    version = seed_week(data_root)

    activated = _command(client, "act-1", "activate_week", version)
    assert activated.status_code == 200
    version = client.get("/api/v1/snapshot").json()["version"]

    closed = _command(client, "close-1", "close_week", version)
    assert closed.status_code == 200

    week = client.get("/api/v1/week/1").json()["data"]
    assert week["status"] == "closed"
    assert week["summary"] is not None


def test_close_week_sets_closed_at(client: TestClient, data_root: Path):
    """Закрытая неделя помнит, когда её закрыли."""
    version = seed_week(data_root)
    _command(client, "act-1", "activate_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]
    _command(client, "close-1", "close_week", version)

    summary = client.get("/api/v1/week/1").json()["data"]["summary"]
    assert summary["closed_at"], "время закрытия не проставлено"


def test_propose_on_closed_week_is_rejected(client: TestClient, data_root: Path):
    """I23: закрытая неделя не меняется — propose на неё отказ."""
    version = seed_week(data_root)
    _command(client, "act-1", "activate_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]
    _command(client, "close-1", "close_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]

    before = client.get("/api/v1/week/1").json()["data"]
    response = _command(client, "prop-1", "propose_week", version)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_command"

    after = client.get("/api/v1/week/1").json()["data"]
    assert after["status"] == "closed", "закрытая неделя переоткрылась"
    assert after["summary"] is not None, "саммари затёрто"
    assert len(after["workouts"]) == len(before["workouts"])


def test_propose_on_active_week_is_rejected(client: TestClient, data_root: Path):
    """Предлагать заново можно только proposed-неделю."""
    version = seed_week(data_root)
    _command(client, "act-1", "activate_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = _command(client, "prop-1", "propose_week", version)
    assert response.status_code == 400
    assert "proposed" in response.json()["error"]["message"]


def test_close_week_survives_unavailable_garmin(
    client: TestClient, data_root: Path
):
    """Garmin недоступен — неделя всё равно закрывается.

    Ритуал закрытия вытягивает остаток факта, но отсутствие источника не
    должно блокировать закрытие: пользователь решил закрыть.
    """
    version = seed_week(data_root)
    _command(client, "act-1", "activate_week", version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = _command(client, "close-1", "close_week", version)
    assert response.status_code == 200
    week = client.get("/api/v1/week/1").json()["data"]
    assert week["status"] == "closed"


def test_batch_commands(client: TestClient, data_root: Path):
    """Батч: команды подряд, у каждой свой id."""
    version = seed_week(data_root)
    response = client.post("/api/v1/commands/batch", json={
        "commands": [
            {"id": "cmd-1", "type": "activate_week", "args": {"season_week": 1},
             "reason": "включаю", "expected_version": version},
            {"id": "cmd-2", "type": "activate_week", "args": {"season_week": 1},
             "reason": "повтор", "expected_version": version + 1},
        ]
    })
    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert len(results) == 2


def test_pull_fact_does_not_require_week(client: TestClient):
    """pull_fact не требует существующей недели — факт грузится всегда."""
    response = client.post("/api/v1/commands", json={
        "id": "cmd-1", "type": "pull_fact",
        "args": {}, "reason": "загрузить факт", "expected_version": 0,
    })
    # Garmin не подключён → degraded, но НЕ «неделя не найдена»
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "degraded"
    assert "неделя" not in response.json()["error"]["message"]


def test_narrate_returns_text(client: TestClient):
    """Нарратор возвращает текст, не считает."""
    response = client.post("/api/v1/narrate", json={"about": "почему такая нагрузка"})
    assert response.status_code == 200
    assert "text" in response.json()["data"]


def test_no_authorization_header_required(client: TestClient):
    """Авторизации в базе нет: запрос без заголовка проходит."""
    response = client.get("/api/v1/snapshot")
    assert response.status_code == 200


# ------------------------------------------------------------------ связывание


def test_link_actual_sets_backlink_on_session(client: TestClient, data_root: Path):
    """Связь сохраняется на обеих сторонах: у тренировки и у факта.

    Без обратной ссылки факт остаётся свободным — и снова предлагается
    к связыванию, хотя уже занят.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource, Sport

    version = seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60,
        distance_m=10000.0, source=FactSource.GARMIN, external_id="ext-1",
    ))

    response = client.post("/api/v1/commands", json={
        "id": "cmd-link", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w1"},
        "reason": "связываю факт с тренировкой",
        "expected_version": version,
    })
    assert response.status_code == 200

    week = client.get("/api/v1/week/1").json()["data"]
    assert week["workouts"][0]["actual_id"] == "a1"

    actual = client.get("/api/v1/actual/1").json()["data"]["sessions"]
    assert actual[0]["linked_workout_id"] == "w1", "ссылка на факте должна стоять"


def test_unlink_actual_clears_backlink(client: TestClient, data_root: Path):
    """Разрыв связи снимает ссылку с факта — иначе он навсегда занят."""
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource, Sport

    version = seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60,
        source=FactSource.GARMIN, external_id="ext-1",
    ))

    client.post("/api/v1/commands", json={
        "id": "cmd-link", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w1"},
        "reason": "связываю", "expected_version": version,
    })

    current = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "cmd-unlink", "type": "unlink_actual",
        "args": {"season_week": 1, "workout_id": "w1"},
        "reason": "разрываю", "expected_version": current,
    })
    assert response.status_code == 200

    actual = client.get("/api/v1/actual/1").json()["data"]["sessions"]
    assert actual[0]["linked_workout_id"] is None


def test_link_actual_rejects_binding_to_another_workout(client: TestClient, data_root: Path):
    """Факт нельзя связать с двумя разными тренировками — связь 1:1.

    Повторная связка с той же тренировкой — не нарушение: это та же операция.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource, Sport

    version = seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60,
        source=FactSource.GARMIN, external_id="ext-1",
    ))

    client.post("/api/v1/commands", json={
        "id": "cmd-link", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w1"},
        "reason": "связываю", "expected_version": version,
    })

    # Вторая тренировка в неделе — факт уже занят первой.
    week = storage.week(1)
    week.workouts.append(Workout(
        id="w2", request_id="r2", sport=Sport.RUN, kind="easy", focus="base",
        steps=[Step(id="s2", role=StepRole.WORK, sport=Sport.RUN,
                    target_type=TargetType.TIME, target_value=60.0,
                    duration_min=60.0)],
        duration_min=60.0,
    ))
    week.requests.append(Request(id="r2", sport=Sport.RUN, kind="easy",
                                 focus="base", duration_min=60))
    week.assignments.append(Assignment(request_id="r2", slot_id="s2",
                                         start="18:45", duration_min=60))
    week.validate()
    current = storage.version()
    storage.put_week(week, expected_version=current)

    response = client.post("/api/v1/commands", json={
        "id": "cmd-link-2", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w2"},
        "reason": "связываю с другой тренировкой",
        "expected_version": storage.version(),
    })
    assert response.status_code == 400
    assert "1:1" in response.json()["error"]["message"]


def test_i44_link_stored_on_both_sides(client: TestClient, data_root: Path):
    """I44: связь хранится с обеих сторон.

    Тренировка знает факт (`actual_id`), факт знает тренировку
    (`linked_workout_id`). Без обратной ссылки факт снова предлагается
    к связыванию.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource, Sport

    version = seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60,
        source=FactSource.GARMIN, external_id="ext-1",
    ))

    client.post("/api/v1/commands", json={
        "id": "cmd-link", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w1"},
        "reason": "связываю", "expected_version": version,
    })

    week = client.get("/api/v1/week/1").json()["data"]
    actual = client.get("/api/v1/actual/1").json()["data"]["sessions"]
    assert week["workouts"][0]["actual_id"] == "a1"
    assert actual[0]["linked_workout_id"] == "w1"


def test_pull_fact_keeps_user_links(client: TestClient, data_root: Path):
    """Выкачка факта не стирает связи, поставленные пользователем.

    Garmin приходит без `linked_workout_id` — связь ставит человек.
    Если её терять при перезаписи факта, после любой выкачки все
    привязки исчезают.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource, Sport

    version = seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=60,
        source=FactSource.GARMIN, external_id="ext-1",
    ))

    # связываем факт с тренировкой
    client.post("/api/v1/commands", json={
        "id": "cmd-link", "type": "link_actual",
        "args": {"season_week": 1, "actual_id": "a1", "workout_id": "w1"},
        "reason": "связываю", "expected_version": version,
    })
    assert storage.get("a1").linked_workout_id == "w1"

    # источник отдаёт тот же факт, но уже без связи
    pulled = ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=61,
        source=FactSource.GARMIN, external_id="ext-1",
    )
    container = client.app.state.container
    container.activity_port = _StubActivityPort(pulled)

    current = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "cmd-pull", "type": "pull_fact",
        "args": {"season_week": 1}, "reason": "выкачка",
        "expected_version": current,
    })
    assert response.status_code == 200

    assert storage.get("a1").linked_workout_id == "w1"


class _StubActivityPort:
    """Источник активностей для теста: отдаёт заранее заданные факты."""

    def __init__(self, *sessions):
        self._sessions = sessions

    def pull(self, start, end, sport=None):
        return list(self._sessions)


# ------------------------------------------------------- поток изменений (SSE)


def test_events_version_matches_snapshot(client: TestClient, data_root: Path):
    """SSE отдаёт ту же версию, что и снапшот.

    Если они разойдутся, клиент будет считать, что состояние изменилось,
    и перезагружать все данные при каждом событии — отсюда «долгое
    переключение меню».
    """
    version = seed_week(data_root)

    with client.stream("GET", "/api/v1/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # Сжатие потока ломает его: буферизация съедает heartbeat.
        assert response.headers.get("content-encoding", "identity") == "identity"

        # первое событие приходит сразу
        for line in response.iter_lines():
            if line.startswith("data:"):
                break

    payload = json.loads(line[len("data:"):].strip())
    assert payload["version"] == version


def test_events_version_equals_snapshot_body(client: TestClient, data_root: Path):
    """Версия в потоке и в снапшоте — одно и то же число."""
    seed_week(data_root)

    with client.stream("GET", "/api/v1/events") as response:
        for line in response.iter_lines():
            if line.startswith("data:"):
                break

    from_events = json.loads(line[len("data:"):].strip())["version"]
    from_snapshot = client.get("/api/v1/snapshot").json()["version"]

    assert from_events == from_snapshot


def test_static_is_compressed(client: TestClient):
    """Статика сжимается: без gzip клиент тянет 53 КБ JS открытым текстом."""
    response = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_static_is_not_cached_stale(client: TestClient):
    """Статика отдаётся с запретом кэширования.

    На обычном HTTP service worker не работает (только HTTPS/localhost),
    и телефон держит `app.js` в браузерном кэше: без `Cache-Control`
    правка в коде есть, а на экране её нет.
    """
    for path in ("/app.js", "/api.js", "/style.css", "/sw.js", "/"):
        response = client.get(path)
        assert response.status_code == 200, path
        cache_control = response.headers.get("cache-control", "")
        assert "no-cache" in cache_control, (
            f"{path}: Cache-Control={cache_control!r} — телефон будет "
            f"показывать старую версию"
        )
