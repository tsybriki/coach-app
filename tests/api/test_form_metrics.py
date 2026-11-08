"""Тесты API: метрики формы и разбор как часть выкачки.

Проверяется контракт HTTP: метрики недели в ответе недели, метрики
тренировки — отдельным маршрутом, разбор FIT — частью выкачки факта.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    ActualSession,
    Assignment,
    Request,
    Season,
    Slot,
    Split,
    Step,
    Week,
    Workout,
    WorkoutDetail,
)
from app.domain.enums import FactSource, Sport, StepRole, TargetType, WeekStatus


def _step() -> Step:
    return Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)


def seed_week(root: Path) -> int:
    """Неделя с одной тренировкой."""
    storage = FileStorage(root)
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    week = Week(
        id="W1", plan_id="p1", season_week=1,
        start=date(2026, 10, 11), end=date(2026, 10, 17),
        status=WeekStatus.ACTIVE, requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="s1", start="18:45",
                                duration_min=60)],
        workouts=[Workout(id="w1", request_id="r1", sport=Sport.RUN, kind="easy",
                          focus="base", steps=[_step()], duration_min=60.0,
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


def seed_fact_with_detail(root: Path) -> str:
    """Факт с разбором FIT — чтобы метрики было из чего считать."""
    storage = FileStorage(root)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 10, 14), sport=Sport.RUN, duration_min=51,
        distance_m=8000.0, hr_avg=140, source=FactSource.GARMIN,
        external_id="ext-1",
    ))
    detail = WorkoutDetail(
        actual_id="a1",
        source=FactSource.GARMIN,
        duration_s=3060.0,
        elapsed_s=3060.0,
        distance_m=8000.0,
        avg_hr=140,
        max_hr=160,
        avg_cadence=82,
        hr_zone_minutes={"Z1": 5.0, "Z2": 30.0, "Z3": 10.0, "Z4": 4.0,
                         "Z5": 2.0},
        splits=[
            Split(index=1, duration_s=600.0, distance_m=2500.0, avg_hr=110,
                  avg_cadence=70),
            Split(index=2, duration_s=1200.0, distance_m=4000.0, avg_hr=128,
                  avg_cadence=84),
            Split(index=3, duration_s=600.0, distance_m=1500.0, avg_hr=155,
                  avg_cadence=80),
        ],
        # Секундные ряды: по ним считается темп в зоне.
        series_hr=[(0, 120), (60, 128), (120, 128), (180, 155)],
        series_distance=[(0, 0.0), (60, 200.0), (120, 400.0), (180, 450.0)],
        series_cadence=[(0, 78), (60, 82), (120, 82), (180, 84)],
        # Ряд мощности: без него нагрузку (TSS) считать не из чего.
        series_power=[(0, 200), (15, 220), (30, 240), (45, 260), (60, 250)],
    )
    storage.put_detail(detail)
    return "a1"


# ------------------------------------------------------------------ метрики недели


def test_week_response_carries_metrics(client: TestClient, data_root: Path):
    """Метрики формы недели — в ответе недели."""
    seed_week(data_root)
    seed_fact_with_detail(data_root)

    response = client.get("/api/v1/week/1")
    assert response.status_code == 200
    metrics = response.json()["data"]["metrics"]

    assert metrics["z2_min"] == 30.0
    assert metrics["z3_min"] == 10.0
    assert metrics["hi_min"] == 2.0
    assert metrics["workouts_counted"] == 1


def test_week_metrics_without_details_are_empty(
    client: TestClient, data_root: Path
):
    """Без разборов метрики пустые, а не выдуманные."""
    seed_week(data_root)

    metrics = client.get("/api/v1/week/1").json()["data"]["metrics"]

    assert metrics["workouts_counted"] == 0
    assert metrics["z2_min"] == 0.0
    assert metrics["tss"] == 0.0


def test_week_metrics_pace_in_z2(client: TestClient, data_root: Path):
    """Темп в Z2 — по сплитам, где пульс был в Z2."""
    seed_week(data_root)
    seed_fact_with_detail(data_root)

    metrics = client.get("/api/v1/week/1").json()["data"]["metrics"]

    # сплит 2: 4000 м за 1200 с = 300 с/км
    assert metrics["pace_z2_sec_per_km"] == 300.0
    assert metrics["pace_z2"] == "5:00 на км"


def test_week_metrics_need_ftp_for_tss(client: TestClient, data_root: Path):
    """Без FTP нагрузки нет — метрика не появляется."""
    seed_week(data_root)
    seed_fact_with_detail(data_root)

    metrics = client.get("/api/v1/week/1").json()["data"]["metrics"]

    assert metrics["tss"] == 0.0


def test_week_metrics_have_tss_with_ftp(client: TestClient, data_root: Path):
    """С FTP нагрузка считается."""
    seed_week(data_root)
    seed_fact_with_detail(data_root)
    storage = FileStorage(data_root)
    athlete = storage.get_athlete()
    storage.update_athlete(type(athlete)(
        vdot=athlete.vdot, hr_zones=athlete.hr_zones, hr_max=athlete.hr_max,
        rhr=athlete.rhr, lth=athlete.lth, weight_kg=athlete.weight_kg,
        injuries=athlete.injuries, form=athlete.form, ftp_w=250.0,
    ))

    metrics = client.get("/api/v1/week/1").json()["data"]["metrics"]

    assert metrics["tss"] is not None
    assert metrics["tss"] > 0


# ------------------------------------------------------------------ метрики тренировки


def test_metrics_endpoint_returns_workout_metrics(
    client: TestClient, data_root: Path
):
    """Метрики одной тренировки — отдельным маршрутом."""
    seed_week(data_root)
    seed_fact_with_detail(data_root)

    response = client.get("/api/v1/metrics/a1")
    assert response.status_code == 200
    metrics = response.json()["data"]

    assert metrics["actual_id"] == "a1"
    assert metrics["z2_min"] == 30.0
    assert metrics["cadence_avg"] == 82
    # Каденция в работе: сплиты с пульсом 128 и 155 → (84 + 80) / 2 = 82
    assert metrics["cadence_work"] == 82
    assert metrics["workout_counted"] is True


def test_metrics_endpoint_for_unknown_fact_is_404(
    client: TestClient, data_root: Path
):
    """Нет факта — 404, а не пустой ответ."""
    seed_week(data_root)

    response = client.get("/api/v1/metrics/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_metrics_endpoint_without_detail_says_so(
    client: TestClient, data_root: Path
):
    """Факт есть, разбора нет — метрики пустые, а не нули."""
    seed_week(data_root)
    storage = FileStorage(data_root)
    storage.upsert(ActualSession(
        id="a2", date=date(2026, 10, 15), sport=Sport.RUN, duration_min=30,
        distance_m=5000.0, hr_avg=140, source=FactSource.GARMIN,
        external_id="ext-2",
    ))

    metrics = client.get("/api/v1/metrics/a2").json()["data"]

    assert metrics["workout_counted"] is False
    assert metrics["z2_min"] is None
    assert metrics["tss"] is None


# ------------------------------------------------------------------ выкачка


def test_pull_fact_parses_fit_as_part_of_pull(
    client: TestClient, data_root: Path, monkeypatch
):
    """Разбор FIT — часть выкачки факта.

    Без разбора у тренировки нет метрик формы, а выкачка — единственный
    момент, когда файлы Garmin доступны.
    """
    seed_week(data_root)

    parsed: list[str] = []

    class _StubImporter:
        def import_many(self, sessions):
            parsed.extend(s.id for s in sessions)
            return {"imported": len(sessions), "skipped": 0}

    class _StubPort:
        def pull(self, start, end, sport=None):
            return [ActualSession(
                id="a9", date=date(2026, 10, 14), sport=Sport.RUN,
                duration_min=45, distance_m=8000.0, source=FactSource.GARMIN,
                external_id="ext-9",
            )]

    container = client.app.state.container
    container.activity_port = _StubPort()
    container.detail_importer = _StubImporter()

    version = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "pull-1", "type": "pull_fact",
        "args": {"season_week": 1}, "reason": "загрузить факт",
        "expected_version": version,
    })

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["parsed"] == 1
    assert body["not_parsed"] == 0
    assert parsed == ["a9"], "разбор не вызван при выкачке"


def test_pull_fact_survives_failing_parser(
    client: TestClient, data_root: Path
):
    """Сбой разбора не роняет выкачку: факт важнее разбора."""
    seed_week(data_root)

    class _StubImporter:
        def import_many(self, sessions):
            return {"imported": 0, "skipped": len(sessions)}

    class _StubPort:
        def pull(self, start, end, sport=None):
            return [ActualSession(
                id="a9", date=date(2026, 10, 14), sport=Sport.RUN,
                duration_min=45, distance_m=8000.0, source=FactSource.GARMIN,
                external_id="ext-9",
            )]

    container = client.app.state.container
    container.activity_port = _StubPort()
    container.detail_importer = _StubImporter()

    version = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "pull-2", "type": "pull_fact",
        "args": {"season_week": 1}, "reason": "загрузить факт",
        "expected_version": version,
    })

    assert response.status_code == 200
    assert response.json()["data"]["parsed"] == 0


def test_close_week_stores_metrics_in_summary(
    client: TestClient, data_root: Path
):
    """При закрытии недели метрики кладутся в саммари.

    До закрытия они меняются, после — нет: закрытая неделя не меняется.
    """
    seed_week(data_root)
    seed_fact_with_detail(data_root)

    version = client.get("/api/v1/snapshot").json()["version"]
    response = client.post("/api/v1/commands", json={
        "id": "close-1", "type": "close_week",
        "args": {"season_week": 1}, "reason": "закрываю неделю",
        "expected_version": version,
    })
    assert response.status_code == 200

    summary = client.get("/api/v1/week/1").json()["data"]["summary"]
    assert summary["metrics"]["z2_min"] == 30.0
    assert summary["metrics"]["workouts_counted"] == 1
