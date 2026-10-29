"""Контрактные тесты хранилища.

Один набор тестов на все порты хранения. Сейчас работает против файлового
адаптера; когда появится SQLite-адаптер, тот же набор прогоняется против него.

Проверяется поведение, а не формат: сохранил → прочитал то же; версия
не совпала → отказ; несуществующий id → None; дубликат external_id → отказ.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    ActualSession,
    Assignment,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FactSource,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(tmp_path / "data")


def make_season(version: int = 0) -> Season:
    return Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 12),
        season_week_count=49,
        version=version,
        plans=[],
    )


def make_week(season_week: int = 1) -> Week:
    request = Request(id="r1", sport=Sport.RUN, kind="easy", focus="base",
                      duration_min=60)
    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0, duration_min=60.0)
    return Week(
        id=f"W{season_week}",
        plan_id="p1",
        season_week=season_week,
        start=date(2026, 10, 11),
        end=date(2026, 10, 17),
        status=WeekStatus.PROPOSED,
        requests=[request],
        assignments=[Assignment(request_id="r1", slot_id="sl1", start="18:45",
                                duration_min=60)],
        workouts=[
            Workout(
                id="w1", request_id="r1", sport=Sport.RUN, kind="easy", focus="base",
                steps=[step], duration_min=60.0,
            )
        ],
    )


def make_session(sid: str = "a1", external_id: str | None = "ext-1") -> ActualSession:
    return ActualSession(
        id=sid,
        date=date(2026, 10, 14),
        sport=Sport.RUN,
        duration_min=60,
        distance_m=10000.0,
        moderate_min=30,
        vigorous_min=10,
        source=FactSource.GARMIN,
        external_id=external_id,
    )


# ------------------------------------------------------------------ SeasonRepo


def test_save_and_load_roundtrip(storage: FileStorage):
    """Сохранил → прочитал то же."""
    season = make_season()
    version = storage.save(season, expected_version=0)
    assert version == 1

    loaded = storage.load()
    assert loaded.id == season.id
    assert loaded.horizon_start == season.horizon_start
    assert loaded.season_week_count == 49
    assert loaded.version == 1


def test_save_with_stale_version_is_rejected(storage: FileStorage):
    """Версия не совпала → отказ, состояние не меняется."""
    storage.save(make_season(), expected_version=0)

    with pytest.raises(Exception) as error:
        storage.save(make_season(), expected_version=0)
    assert "версия" in str(error.value)

    assert storage.load().version == 1


def test_version_is_global_across_season_and_week(storage: FileStorage):
    """Версия одна на всё состояние: изменение недели двигает её тоже.

    Раньше версия недели и версия сезона были разными счётчиками — команда
    сравнивала одно с другим и получался ложные конфликты.
    """
    storage.save(make_season(), expected_version=0)
    assert storage.version() == 1

    storage.put_week(make_week(), expected_version=1)
    assert storage.version() == 2, "запись недели двигает глобальную версию"

    with pytest.raises(Exception, match="версия"):
        storage.put_week(make_week(2), expected_version=1)


def test_week_roundtrip(storage: FileStorage):
    """Неделя сохраняется и читается."""
    storage.save(make_season(), expected_version=0)
    week = make_week()
    storage.put_week(week, expected_version=1)

    loaded = storage.week(1)
    assert loaded is not None
    assert loaded.id == "W1"
    assert loaded.status is WeekStatus.PROPOSED
    assert len(loaded.requests) == 1
    assert len(loaded.assignments) == 1
    assert len(loaded.workouts) == 1
    assert loaded.workouts[0].steps[0].duration_min == 60.0


def test_missing_week_returns_none(storage: FileStorage):
    """Несуществующий id → None, не исключение."""
    assert storage.week(99) is None


def test_week_preserves_unplaced_and_actual_link(storage: FileStorage):
    """Висяки и привязка факта переживают запись."""
    storage.save(make_season(), expected_version=0)
    week = make_week()
    week.unplaced = [Request(id="r2", sport=Sport.SWIM, kind="easy", focus="base",
                              duration_min=30)]
    week.workouts[0].actual_id = "a1"
    storage.put_week(week, expected_version=1)

    loaded = storage.week(1)
    assert loaded is not None
    assert [r.id for r in loaded.unplaced] == ["r2"]
    assert loaded.workouts[0].actual_id == "a1"


# ------------------------------------------------------------------ FactRepo


def test_upsert_and_get(storage: FileStorage):
    """Факт сохраняется и читается."""
    session = make_session()
    storage.upsert(session)

    loaded = storage.get("a1")
    assert loaded is not None
    assert loaded.duration_min == 60
    assert loaded.moderate_min == 30
    assert loaded.external_id == "ext-1"


def test_upsert_same_id_updates(storage: FileStorage):
    """Повторная запись с тем же id — обновление, не новая запись."""
    storage.upsert(make_session())
    updated = make_session()
    updated.duration_min = 90
    storage.upsert(updated)

    assert len(storage.list_for_week(1)) == 1
    loaded = storage.get("a1")
    assert loaded is not None
    assert loaded.duration_min == 90


def test_upsert_duplicate_external_id_is_rejected(storage: FileStorage):
    """Дубликат external_id → отказ."""
    storage.upsert(make_session("a1", "ext-1"))

    with pytest.raises(Exception) as error:
        storage.upsert(make_session("a2", "ext-1"))
    assert "external_id" in str(error.value)


def test_link_sets_and_clears(storage: FileStorage):
    """Связь факта с тренировкой ставится и снимается."""
    storage.upsert(make_session())
    storage.link("a1", "w1")

    loaded = storage.get("a1")
    assert loaded is not None
    assert loaded.linked_workout_id == "w1"

    storage.link("a1", None)
    loaded = storage.get("a1")
    assert loaded is not None
    assert loaded.linked_workout_id is None


def test_list_in_range_filters_by_date(storage: FileStorage):
    """Факт за период — только то, что попадает в диапазон."""
    inside = make_session("a1", "ext-1")
    outside = make_session("a2", "ext-2")
    outside.date = date(2026, 11, 1)
    storage.upsert(inside)
    storage.upsert(outside)

    result = storage.list_in_range(date(2026, 10, 11), date(2026, 10, 17))
    assert [s.id for s in result] == ["a1"]


def test_missing_fact_returns_none(storage: FileStorage):
    """Нет факта → None."""
    assert storage.get("нет-такого") is None


# ------------------------------------------------------------------ атомарность


def test_write_is_atomic_no_tmp_left(storage: FileStorage):
    """После записи временных файлов не остаётся."""
    storage.save(make_season(), expected_version=0)
    leftovers = list(storage.root.rglob("*.tmp"))
    assert leftovers == []


def test_write_replaces_whole_file(storage: FileStorage):
    """Запись перезаписывает файл целиком, а не дописывает."""
    storage.save(make_season(), expected_version=0)
    storage.save(make_season(), expected_version=1)
    text = (storage.root / "season.json").read_text(encoding="utf-8")
    assert text.count('"id"') == 1


def test_broken_file_gives_clear_error(storage: FileStorage):
    """Битый файл → понятное сообщение, не случайное исключение."""
    storage.save(make_season(), expected_version=0)
    (storage.root / "season.json").write_text("{не json", encoding="utf-8")

    with pytest.raises(ValueError, match="битый JSON"):
        storage.load()


def test_empty_file_is_treated_as_empty(storage: FileStorage):
    """Пустой файл → пустое состояние, не ошибка."""
    (storage.root / "season.json").write_text("", encoding="utf-8")
    assert storage.load().id == "S1"


# ------------------------------------------------------------------ блокировка


def test_concurrent_write_is_rejected(storage: FileStorage):
    """Вторая запись, пока лок занят, отклоняется."""
    storage.save(make_season(), expected_version=0)

    handle = storage._lock()
    try:
        with pytest.raises(Exception) as error:
            storage.save(make_season(), expected_version=1)
        assert "занят" in str(error.value)
    finally:
        handle.close()


def test_write_succeeds_after_lock_released(storage: FileStorage):
    """После освобождения лока запись проходит."""
    storage.save(make_season(), expected_version=0)
    handle = storage._lock()
    handle.close()

    version = storage.save(make_season(), expected_version=1)
    assert version == 2


# ------------------------------------------------------------------ AthleteRepo


def test_athlete_roundtrip(storage: FileStorage):
    """Профиль атлета сохраняется и читается."""
    from app.domain.entities import Athlete

    athlete = Athlete(vdot=46.4, hr_zones={"Z2": "118-135"}, hr_max=182,
                      rhr=54, lth=164, weight_kg=101.7)
    storage.update_athlete(athlete)

    loaded = storage.get_athlete()
    assert loaded.vdot == 46.4
    assert loaded.lth == 164
    assert loaded.weight_kg == 101.7


def test_missing_athlete_gives_empty_profile(storage: FileStorage):
    """Нет профиля → пустой профиль, не ошибка."""
    loaded = storage.get_athlete()
    assert loaded.vdot == 0.0


# ------------------------------------------------------------------ CommandLog


def test_command_log_is_idempotent(storage: FileStorage):
    """Повтор команды с тем же id — одна запись в журнале."""
    from app.domain.entities import Command
    from app.domain.enums import CommandType

    command = Command(id="c1", type=CommandType.PROPOSE_WEEK, reason="план")
    storage.append_command(command, {"status": "applied", "new_version": 1})
    storage.append_command(command, {"status": "applied", "new_version": 1})

    assert storage.get_command("c1") is not None
    assert storage.get_command("нет") is None


def test_slot_equipment_validation(storage: FileStorage):
    """Слот ссылается на реестр — проверка на уровне сезона."""
    from app.domain.entities import Goal, Plan
    from app.domain.enums import PlanStatus

    season = make_season()
    season.plans = [Plan(
        id="p1", status=PlanStatus.ACTIVE,
        goal=Goal(id="g1", discipline="run_10k", race_date=date(2027, 4, 18),
                  metric_type="time_sec", metric_target=2400.0,
                  target_friendly="10К за 40:00"),
        period_start=date(2026, 10, 11), period_end=date(2027, 9, 12),
    )]
    season.slots = [Slot(id="sl1", day=0, start="18:45", end="20:15",
                          capacity_min=90, equipment_ids=("pool",))]
    with pytest.raises(Exception, match="I3"):
        season.validate()
