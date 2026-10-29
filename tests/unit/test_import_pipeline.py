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
from app.domain.entities import ActualSession, Season  # noqa: E402
from app.domain.enums import FactSource, Sport  # noqa: E402


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
