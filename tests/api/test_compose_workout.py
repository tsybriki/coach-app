"""API: разбор тренировки из текста и удаление тренировки.

Проверяем маршрут `/compose` (чтение: неделя не меняется) и команды
`add_composed_workout` и `remove_workout` (изменение состояния).

Модель в тестах — заглушка: тесты не ходят в сеть.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.composer import ModelPlan
from app.adapters.storage.files import FileStorage
from app.domain.composition import WorkoutIntent
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
from app.domain.enums import (
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)
from app.ports.storage import ComposeContext, ExternalSourceError


class StubComposer:
    """Заглушка вместо модели: отдаёт заранее заданные намерения."""

    available = True

    def __init__(self, plan: ModelPlan | None = None,
                 error: Exception | None = None) -> None:
        self.plan = plan or ModelPlan(
            name="Фартлек",
            sport=Sport.RUN,
            intents=[
                WorkoutIntent(
                    role=StepRole.WARMUP, sport=Sport.RUN,
                    target_type=TargetType.DISTANCE, target_value=3000.0,
                    intent="easy", label="Разминка",
                ),
                WorkoutIntent(
                    role=StepRole.WORK, sport=Sport.RUN,
                    target_type=TargetType.DISTANCE, target_value=8000.0,
                    intent="threshold", label="Фартлек",
                ),
            ],
            assumptions=["объём фартлека не указан — 8 км"],
        )
        self.error = error

    def compose(self, text: str, context: ComposeContext) -> ModelPlan:
        if self.error is not None:
            raise self.error
        return self.plan


@pytest.fixture
def stub_composer(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Подменить композитор в контейнере приложения.

    Контейнер собирается в lifespan — при создании клиента. Поэтому
    заглушка ставится прямо в готовый контейнер: `app.state.container`.
    """
    from app.services.composer import WorkoutComposer

    def _install(composer: StubComposer) -> None:
        container = client.app.state.container
        container.composer_port = composer
        container.composer = WorkoutComposer(composer)

    return _install


def seed_week(root: Path, status: WeekStatus = WeekStatus.PROPOSED) -> int:
    """Неделя с одной тренировкой. Возвращает версию."""
    storage = FileStorage(root)
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=status, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN,
                          kind="easy", focus="base", steps=[step],
                          duration_min=60.0, time="18:45")],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[],
               slots=[Slot(id="s1", day=1, start="18:45", end="20:15",
                           capacity_min=90)]),
        expected_version=0,
    )
    return storage.put_week(week, expected_version=1)


# ------------------------------------------------------------------ разбор


def test_compose_returns_steps_without_touching_the_week(
    client: TestClient, data_root: Path, stub_composer
):
    """Разбор — чтение: неделя не меняется, а структура приходит."""
    version = seed_week(data_root)
    stub_composer(StubComposer())
    # Профиль с зонами: без них домен не может вывести зону пульса и
    # показывает шаг по темпу.
    storage = FileStorage(data_root)
    storage.update_athlete(Athlete(
        vdot=50.0,
        hr_zones={"Z1": (95, 110), "Z2": (111, 130), "Z3": (131, 145),
                  "Z4": (146, 158), "Z5": (159, 168), "Z7": (172, 182)},
        hr_max=182, rhr=50, lth=164,
    ))

    response = client.post("/api/v1/compose", json={
        "text": "12 км, 3 км разминка, дальше фартлек",
        "season_week": 1,
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Фартлек"
    assert len(data["steps"]) == 2
    assert data["assumptions"]
    # Зона и темп — от домена, по профилю.
    work = data["steps"][1]["step"]
    assert work["focus_value"]["zone"] == "Z5"
    assert work["focus_value"]["pace_min_per_km"]
    # Минуты посчитал домен, а не модель.
    assert work["duration_min"] > 0
    # Неделя не тронута.
    assert client.get("/api/v1/week/1").json()["data"]["id"] == "W1"
    assert client.get("/api/v1/week/1").json()["version"] == version


def test_compose_without_key_is_degraded(
    client: TestClient, data_root: Path, stub_composer
):
    """Без ключа модели — 503, а не падение."""
    seed_week(data_root)

    class NoKey:
        available = False

    stub_composer(NoKey())

    response = client.post("/api/v1/compose", json={"text": "любая тренировка"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "degraded"


def test_compose_with_broken_model_is_degraded(
    client: TestClient, data_root: Path, stub_composer
):
    """Модель недоступна — 503 с понятным сообщением."""
    seed_week(data_root)
    stub_composer(StubComposer(error=ExternalSourceError(
        "minimax", "модель недоступна")))

    response = client.post("/api/v1/compose", json={"text": "любая тренировка"})

    assert response.status_code == 503
    assert "модель" in response.json()["error"]["message"].lower()


def test_compose_with_empty_text_is_rejected(
    client: TestClient, data_root: Path, stub_composer
):
    """Пустой текст — понятный отказ."""
    seed_week(data_root)
    stub_composer(StubComposer())

    response = client.post("/api/v1/compose", json={"text": "   "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


# ------------------------------------------------- добавление в неделю


def test_add_composed_workout_creates_unplaced_training(
    client: TestClient, data_root: Path, stub_composer
):
    """Разобранная тренировка добавляется в неделю висяком."""
    version = seed_week(data_root)
    stub_composer(StubComposer())

    response = client.post("/api/v1/commands", json={
        "id": "cmd-compose",
        "type": "add_composed_workout",
        "args": {
            "season_week": 1,
            "name": "Фартлек",
            "assumptions": ["объём фартлека не указан — 8 км"],
            "source_text": "12 км, фартлек",
            "intents": [
                {"role": "warmup", "sport": "run", "target_type": "distance",
                 "target_value": 3000, "intent": "easy", "label": "Разминка"},
                {"role": "work", "sport": "run", "target_type": "distance",
                 "target_value": 8000, "intent": "threshold", "label": "Фартлек"},
            ],
        },
        "reason": "тренировка из твоего описания",
        "expected_version": version,
    })

    assert response.status_code == 200
    week = client.get("/api/v1/week/1").json()["data"]
    # Тренировка появилась и висит: время выбирает пользователь.
    composed = [w for w in week["workouts"] if w["kind"] == "composed"]
    assert len(composed) == 1
    assert composed[0]["objective"]["name"] == "Фартлек"
    assert composed[0]["objective"]["source_text"] == "12 км, фартлек"
    assert composed[0]["objective"]["assumptions"]
    # Висяк: день не назначен.
    assert composed[0]["objective"].get("day") in (None, "")
    assert any(u["id"].startswith("r-composed")
               for u in week["unplaced"])


def test_add_composed_workout_needs_intents(
    client: TestClient, data_root: Path, stub_composer
):
    """Без намерений команда не проходит."""
    version = seed_week(data_root)
    stub_composer(StubComposer())

    response = client.post("/api/v1/commands", json={
        "id": "cmd-compose",
        "type": "add_composed_workout",
        "args": {"season_week": 1, "name": "Пусто", "intents": []},
        "reason": "тренировка из твоего описания",
        "expected_version": version,
    })

    assert response.status_code == 400


def test_add_composed_workout_creates_week_if_missing(
    client: TestClient, data_root: Path, stub_composer
):
    """Тренировку можно предложить и для ещё не спланированной недели.

    Неделя создаётся — с этой одной тренировкой, а не по макро-плану:
    пользователь описал конкретную тренировку, а не всю неделю.
    """
    from app.adapters.storage.files import FileStorage

    storage = FileStorage(data_root)
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[]),
        expected_version=0,
    )
    stub_composer(StubComposer())

    response = client.post("/api/v1/commands", json={
        "id": "cmd-compose",
        "type": "add_composed_workout",
        "args": {
            "season_week": 3,
            "name": "Фартлек",
            "intents": [
                {"role": "work", "sport": "run", "target_type": "distance",
                 "target_value": 8000, "intent": "threshold", "label": "Фартлек"},
            ],
        },
        "reason": "тренировка из твоего описания",
        "expected_version": 1,
    })

    assert response.status_code == 200
    week = client.get("/api/v1/week/3").json()["data"]
    assert week["id"] == "W3"
    assert week["status"] == "proposed"
    composed = [w for w in week["workouts"] if w["kind"] == "composed"]
    assert len(composed) == 1
    # Висяк: время выбирает пользователь.
    assert composed[0]["objective"].get("day") in (None, "")
    assert len(week["unplaced"]) == 1


# ------------------------------------------------------------------ удаление


def test_remove_workout_command_removes_it(
    client: TestClient, data_root: Path
):
    """Команда удаления убирает тренировку из недели."""
    version = seed_week(data_root)

    response = client.post("/api/v1/commands", json={
        "id": "cmd-remove",
        "type": "remove_workout",
        "args": {"season_week": 1, "workout_id": "w1"},
        "reason": "удаление тренировки из недели",
        "expected_version": version,
    })

    assert response.status_code == 200
    week = client.get("/api/v1/week/1").json()["data"]
    assert week["workouts"] == []
    assert week["unplaced"] == []


def test_remove_workout_in_active_week_is_rejected(
    client: TestClient, data_root: Path
):
    """В активной неделе удалять нельзя."""
    version = seed_week(data_root, WeekStatus.ACTIVE)

    response = client.post("/api/v1/commands", json={
        "id": "cmd-remove",
        "type": "remove_workout",
        "args": {"season_week": 1, "workout_id": "w1"},
        "reason": "удаление тренировки из недели",
        "expected_version": version,
    })

    assert response.status_code == 400
    week = client.get("/api/v1/week/1").json()["data"]
    assert len(week["workouts"]) == 1, 'тренировка не должна исчезнуть'


def test_week_response_reports_compose_availability(
    client: TestClient, data_root: Path, stub_composer
):
    """Клиент знает, показывать ли кнопку предложения."""
    seed_week(data_root)
    stub_composer(StubComposer())

    week = client.get("/api/v1/week/1").json()["data"]
    assert week["compose_available"] is True
