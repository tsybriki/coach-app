"""Импорт из пайплайна: факты и связи.

Главное правило импорта: он переносит план и факты, но не трогает то, что
задал пользователь, — привязку факта к тренировке.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from import_pipeline import preserve_links  # noqa: E402

from app.adapters.storage.files import FileStorage  # noqa: E402
from app.domain.entities import (  # noqa: E402
    ActualSession,
    Goal,
    MacroWeek,
    Plan,
    Season,
    Week,
)
from app.domain.enums import (  # noqa: E402
    FactSource,
    PlanStatus,
    Sport,
    WeekStatus,
)


def make_season() -> Season:
    return Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 12),
        season_week_count=49,
        version=0,
        plans=[],
    )


def make_session(sid: str = "a1") -> ActualSession:
    return ActualSession(
        id=sid,
        date=date(2026, 10, 14),
        sport=Sport.RUN,
        duration_min=60,
        source=FactSource.GARMIN,
        external_id=f"ext-{sid}",
    )


def test_import_builds_slots_with_location_rules(tmp_path: Path) -> None:
    """Импорт окон выводит запреты из места.

    Дефект, который это ловит: вел вставал во вторник, где
    велосипеда нет. Окно хранило только строку места, и запретов из
    неё не выводилось.
    """
    from import_pipeline import build_slots

    constraints = {
        "weekly_windows": {
            "ВТ": [{"start": "09:00", "end": "09:30", "duration_min": 30,
                    "location": "asphalt_commuter"}],
            "ЧТ": [{"start": "10:30", "end": "11:15", "duration_min": 45,
                    "location": "home_stationary_bike"}],
        }
    }

    slots = build_slots(constraints)

    by_id = {s.id: s for s in slots}
    tuesday = by_id["win-ВТ-1"]
    thursday = by_id["win-ЧТ-1"]
    assert Sport.BIKE in tuesday.forbidden_sports, \
        "во вторнике окно на асфальте — велосипеда там нет"
    assert Sport.BIKE not in thursday.forbidden_sports, \
        "в четверге домашний станок — велосипед есть"


def test_import_preserves_existing_link(tmp_path: Path) -> None:
    """Повторный импорт не стирает привязку факта к тренировке."""
    storage = FileStorage(tmp_path / "data")
    storage.save(make_season(), expected_version=0)
    stored = make_session()
    storage.upsert(stored)
    storage.link(stored.id, "w-1")

    # тот же факт приходит из выкачки снова — уже без связи
    incoming = [make_session()]

    result = preserve_links(storage, incoming)

    assert result[0].linked_workout_id == "w-1"


def test_import_keeps_link_for_new_session(tmp_path: Path) -> None:
    """Новый факт без связи остаётся без связи."""
    storage = FileStorage(tmp_path / "data")

    result = preserve_links(storage, [make_session("a2")])

    assert result[0].linked_workout_id is None


def test_season_only_refresh_keeps_week_untouched(tmp_path: Path) -> None:
    """Обновление сезона не переписывает неделю.

    Описание недели в макро-плане может устареть (пересборка макро
    меняет цель недели, а текст остаётся прежним). Обновление сезона
    обязано это чинить — но содержимое раскладки недели (тренировки,
    время, висяки) трогать нельзя: неделю собирает планировщик, и импорт
    макро не имеет права переписывать её жизнь.
    """
    storage = FileStorage(tmp_path / "data")
    plan = Plan(
        id="g1",
        status=PlanStatus.ACTIVE,
        goal=Goal(
            id="g1",
            discipline="run_10k",
            race_date=date(2027, 4, 18),
            metric_type="time_sec",
            metric_target=2400.0,
            target_friendly="40:00",
        ),
        period_start=date(2026, 10, 11),
        period_end=date(2027, 9, 12),
        macro_weeks=[MacroWeek(season_week=1, phase_id="run_base",
                                focus="progression", goal_text="Старая цель")],
    )
    storage.save(Season(id="S1", horizon_start=date(2026, 10, 11),
                        horizon_end=date(2027, 9, 12),
                        season_week_count=49, plans=[plan]),
                 expected_version=0)

    # Неделя в хранилище — её содержимое import не должен менять.
    week = Week(id="W1", plan_id="g1", season_week=1,
                start=date(2026, 10, 11), end=date(2026, 10, 17),
                status=WeekStatus.PROPOSED)
    storage.put_week(week, expected_version=storage.version())
    before = storage.week(1)
    assert before is not None

    # Сезон пересобирается с новым текстом цели.
    new_plan = Plan(
        id="g1",
        status=PlanStatus.ACTIVE,
        goal=plan.goal,
        period_start=date(2026, 10, 11),
        period_end=date(2027, 9, 12),
        macro_weeks=[MacroWeek(season_week=1, phase_id="run_base",
                                focus="progression", goal_text="Новая цель")],
    )
    storage.save(Season(id="S1", horizon_start=date(2026, 10, 11),
                        horizon_end=date(2027, 9, 12),
                        season_week_count=49, plans=[new_plan]),
                 expected_version=storage.version())

    loaded = storage.load()
    assert loaded.plans[0].macro_weeks[0].goal_text == "Новая цель"

    after = storage.week(1)
    assert after is not None
    assert after.status is WeekStatus.PROPOSED
    assert after.season_week == before.season_week
    assert after.version == before.version, "неделя была переписана импортом сезона"
