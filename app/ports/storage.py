"""Порты — контракты внешнего мира.

Домен и сервисы знают только эти интерфейсы. Реализации — в `app/adapters/`.

Ни один метод не упоминает формат хранения: нет параметров `path`, `table`,
`collection`, `query`. Всё — на языке домена.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

from app.domain.entities import (
    ActualSession,
    Athlete,
    Command,
    PlanModel,
    Season,
    Week,
)


class SeasonRepo(Protocol):
    """Состояние сезона: план, фазы, недели."""

    def load(self) -> Season:
        """Весь сезон."""
        ...

    def save(self, season: Season, expected_version: int) -> int:
        """Сохранить сезон. Возвращает новую версию.

        `expected_version` не совпал с текущим → отказ (см. `VersionConflictError`).
        """
        ...

    def week(self, season_week: int) -> Week | None:
        """Одна неделя по номеру. Нет — None, не исключение."""
        ...

    def put_week(self, week: Week, expected_version: int) -> int:
        """Сохранить неделю. Возвращает новую версию."""
        ...


class FactRepo(Protocol):
    """Факт: выполненные тренировки."""

    def list_for_week(self, season_week: int) -> list[ActualSession]:
        """Факт недели."""
        ...

    def list_in_range(self, start: date, end: date) -> list[ActualSession]:
        """Факт за период. Границы включительные."""
        ...

    def get(self, actual_id: str) -> ActualSession | None:
        """Одна сессия. Нет — None."""
        ...

    def upsert(self, session: ActualSession) -> ActualSession:
        """Добавить или обновить. Дубликат `external_id` → отказ."""
        ...

    def link(self, actual_id: str, workout_id: str | None) -> None:
        """Связать факт с тренировкой или разорвать связь (None)."""
        ...


class AthleteRepo(Protocol):
    """Профиль атлета."""

    def get(self) -> Athlete:
        """Профиль. Нет профиля — пустой профиль, не ошибка."""
        ...

    def update(self, athlete: Athlete) -> None:
        """Сохранить профиль."""
        ...


class MethodologyRepo(Protocol):
    """Правила методологии: модели, шаблоны, шкала зон."""

    def plan_models(self) -> list[PlanModel]:
        """Набор моделей плана."""
        ...

    def load_model(self) -> LoadModelProtocol:
        """Правило нагрузки."""
        ...

    def workout_templates(self) -> dict[str, object]:
        """Шаблоны тренировок по (goal, scale)."""
        ...


class LoadModelProtocol(Protocol):
    """Правило нагрузки — минимальный контракт для планировщика."""

    intensity_factor: dict[str, float]
    adaptation_rate: dict[str, float]
    budget: dict[str, object]


class CommandLog(Protocol):
    """Журнал команд: идемпотентность."""

    def get(self, command_id: str) -> CommandResultProtocol | None:
        """Результат ранее выполненной команды. Нет — None."""
        ...

    def append(self, command: Command, result: CommandResultProtocol) -> None:
        """Записать команду и её результат."""
        ...


class CommandResultProtocol(Protocol):
    """Минимальный контракт результата команды для журнала."""

    status: str
    new_version: int


class ActivityPort(Protocol):
    """Внешний источник активностей."""

    def pull(self, start: date, end: date, sport: str | None = None) -> list[ActualSession]:
        """Вытянуть активности за период.

        Источник недоступен → исключение `ExternalSourceError` (вызывающий
        превращает в `degraded`), а не молчаливый пустой список.
        """
        ...


class CalendarPort(Protocol):
    """Внешний источник окон тренировок."""

    def windows(self, start: date, end: date) -> list[object]:
        """Окна за период."""
        ...


class NarratorPort(Protocol):
    """Текст, объяснения, варианты. Не считает и не применяет."""

    def explain(self, about: str, diff: list[dict[str, object]] | None = None) -> str:
        """Пояснить план или diff."""
        ...


class Clock(Protocol):
    """Текущее время. В тестах — фиксированное."""

    def now(self) -> date:
        ...


class IdGen(Protocol):
    """Генерация идентификаторов."""

    def new_id(self, prefix: str = "") -> str:
        ...


class ExternalSourceError(Exception):
    """Внешний источник недоступен. Не ошибка домена."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message


class VersionConflictError(Exception):
    """Состояние изменилось: команда отклонена, версия не совпала."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"ожидалась версия {expected}, фактически {actual}")
        self.expected = expected
        self.actual = actual


class StorageBusyError(Exception):
    """Хранилище занято: другая запись идёт."""


class DuplicateExternalIdError(Exception):
    """Дубликат `external_id` — факт с таким id уже есть."""


__all__ = [
    "ActivityPort",
    "AthleteRepo",
    "StorageBusyError",
    "CalendarPort",
    "Clock",
    "CommandLog",
    "CommandResultProtocol",
    "DuplicateExternalIdError",
    "ExternalSourceError",
    "FactRepo",
    "IdGen",
    "LoadModelProtocol",
    "MethodologyRepo",
    "NarratorPort",
    "SeasonRepo",
    "VersionConflictError",
]
