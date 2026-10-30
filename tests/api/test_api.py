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
    Request,
    Season,
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
                          focus="base", steps=[step], duration_min=60.0)],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49, plans=[]),
        expected_version=0,
    )
    return storage.put_week(week, expected_version=1)


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
    assert response.json()["error"]["code"] == "degraded"


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
