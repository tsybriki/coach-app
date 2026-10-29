"""Адаптеры портов хранения поверх файлового хранилища.

`FileStorage` знает формат. Эти классы — реализации портов: у каждого порта
свои имена методов, и один класс не может реализовать два порта с разными
сигнатурами `get`.

Разделение нужно, чтобы домен и сервисы не зависели от формата и чтобы
конфликт имён не маскировался.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    ActualSession,
    Athlete,
    Command,
    LoadModel,
    PlanModel,
    Season,
    Week,
)


class SeasonRepoAdapter:
    """Порт `SeasonRepo`: состояние сезона."""

    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage

    def load(self) -> Season:
        return self._storage.load()

    def save(self, season: Season, expected_version: int) -> int:
        return self._storage.save(season, expected_version)

    def week(self, season_week: int) -> Week | None:
        return self._storage.week(season_week)

    def put_week(self, week: Week, expected_version: int) -> int:
        return self._storage.put_week(week, expected_version)

    def weeks(self) -> list[Week]:
        return self._storage.weeks()


class FactRepoAdapter:
    """Порт `FactRepo`: выполненные тренировки."""

    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage

    def list_for_week(self, season_week: int) -> list[ActualSession]:
        return self._storage.list_for_week(season_week)

    def list_in_range(self, start: date, end: date) -> list[ActualSession]:
        return self._storage.list_in_range(start, end)

    def get(self, actual_id: str) -> ActualSession | None:
        return self._storage.get(actual_id)

    def upsert(self, session: ActualSession) -> ActualSession:
        return self._storage.upsert(session)

    def link(self, actual_id: str, workout_id: str | None) -> None:
        self._storage.link(actual_id, workout_id)


class AthleteRepoAdapter:
    """Порт `AthleteRepo`: профиль атлета."""

    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage

    def get(self) -> Athlete:
        return self._storage.get_athlete()

    def update(self, athlete: Athlete) -> None:
        self._storage.update_athlete(athlete)


class MethodologyRepoAdapter:
    """Порт `MethodologyRepo`: правила методики."""

    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage

    def plan_models(self) -> list[PlanModel]:
        return []

    def load_model(self) -> LoadModel:
        return self._storage.load_methodology_model()

    def workout_templates(self) -> dict[str, Any]:
        return self._storage.load_workout_templates()


class CommandLogAdapter:
    """Порт `CommandLog`: журнал команд для идемпотентности."""

    def __init__(self, storage: FileStorage) -> None:
        self._storage = storage

    def get(self, command_id: str) -> dict[str, object] | None:
        return self._storage.get_command(command_id)

    def append(self, command: Command, result: dict[str, object]) -> None:
        self._storage.append_command(command, result)


__all__ = [
    "AthleteRepoAdapter",
    "CommandLogAdapter",
    "FactRepoAdapter",
    "MethodologyRepoAdapter",
    "SeasonRepoAdapter",
]
