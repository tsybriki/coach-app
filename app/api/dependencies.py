"""Сборка зависимостей.

Одно место, где собирается приложение: адаптеры, порты, сервисы. Ничего не
знает о порядке — только явные зависимости.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fastapi import Request

from app.adapters.composer import MiniMaxComposer
from app.adapters.garmin import GarminActivityPort, GarminFitPort
from app.adapters.storage.files import FileStorage
from app.adapters.storage.ports import (
    AthleteRepoAdapter,
    CommandLogAdapter,
    DetailRepoAdapter,
    FactRepoAdapter,
    MethodologyRepoAdapter,
    SeasonRepoAdapter,
)
from app.domain.entities import ActualSession, Goal
from app.ports.storage import (
    ActivityPort,
    AthleteRepo,
    Clock,
    CommandLog,
    DetailRepo,
    ExternalSourceError,
    FactRepo,
    MethodologyRepo,
    NarratorPort,
    SeasonRepo,
    WorkoutComposerPort,
)
from app.services.assessment import Assessor
from app.services.composer import WorkoutComposer
from app.services.detail_import import DetailImporter
from app.services.form_metrics import MetricsCollector
from app.services.goal_feasibility import GoalFeasibility, StubGrowthRule
from app.services.week_planner import WeekPlanner


class StubNarrator(NarratorPort):
    """Нарратор-заглушка.

    Работает без ключа и без сети: тексты собираются из шаблонов. По правилу
    «деградация вместо отказа» приложение не ломается, если нарратор недоступен.
    """

    def explain(self, about: str, diff: list[dict[str, object]] | None = None) -> str:
        if diff:
            changed = len(diff)
            return f"Изменений: {changed}. Подробности — в разделе «Связи»."
        return f"Объяснение: {about}."


class UnavailableActivityPort(ActivityPort):
    """Заглушка источника активностей.

    Используется в тестах: Garmin подключён не везде. Основной адаптер —
    `GarminActivityPort`, он подставляется в контейнер.
    """

    def pull(self, start: date, end: date, sport: str | None = None) -> list[ActualSession]:
        raise ExternalSourceError("garmin", "источник активностей не подключён")


class SystemClock(Clock):
    """Календарное время системы.

    В тестах подменяется на фиксированное — иначе «текущая неделя» в тестах
    плывёт вместе с реальной датой.
    """

    def now(self) -> date:
        return date.today()


def reference_dir() -> Path | None:
    """Каталог справочника методики.

    Справочник — часть репозитория: таблицы Дэниэлса и программа тренировок.
    Это версионируемые правила, а не состояние, поэтому они лежат рядом с
    кодом, а не в хранилище.
    """
    env = os.environ.get("COACH_APP_REFERENCE")
    if env:
        return Path(env)
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidate = repo_root / "reference" / "daniels"
    return candidate if candidate.is_dir() else None


@dataclass
class AppContainer:
    """Собранное приложение. Передаётся в FastAPI как зависимость."""

    storage: FileStorage
    season_repo: SeasonRepo
    fact_repo: FactRepo
    athlete_repo: AthleteRepo
    methodology_repo: MethodologyRepo
    detail_repo: DetailRepo
    command_log: CommandLog
    activity_port: ActivityPort
    fit_port: GarminFitPort
    narrator_port: NarratorPort
    assessor: Assessor
    feasibility: GoalFeasibility
    planner: WeekPlanner
    clock: Clock
    metrics: MetricsCollector
    detail_importer: DetailImporter
    composer: WorkoutComposer
    composer_port: WorkoutComposerPort


def build_container(data_root: Path | None = None) -> AppContainer:
    """Собрать зависимости.

    Путь к данным — из `COACH_APP_DATA` или `~/.local/share/coach-app`.
    """
    if data_root is None:
        env = os.environ.get("COACH_APP_DATA")
        data_root = (
            Path(env) if env else Path.home() / ".local" / "share" / "coach-app"
        )

    storage = FileStorage(data_root)
    methodology = MethodologyRepoAdapter(storage, reference_dir=reference_dir())
    templates = methodology.workout_templates()
    load_model = methodology.load_model()
    athlete = AthleteRepoAdapter(storage).get()

    planner = WeekPlanner(
        templates=templates,
        load_model=load_model,
        athlete=athlete,
        paces=methodology.training_paces(),
        plan=methodology.method_plan(),
    )

    feasibility = GoalFeasibility(
        growth_rule=StubGrowthRule(),
        target_vdot_for_metric=_target_vdot_for_metric,
    )

    detail_repo = DetailRepoAdapter(storage)
    fact_repo = FactRepoAdapter(storage)
    athlete_repo = AthleteRepoAdapter(storage)
    fit_port = GarminFitPort()

    # Темп по VDOT — по таблице Дэниэлса: он нужен для эффективности
    # формы (фактический темп против темпа, который даёт форма).
    paces = methodology.training_paces()

    def vdot_pace(vdot: float) -> float | None:
        # Зоны справочника Дэниэлса: E (лёгкая), M (марафонская),
        # T (порог), R (повторная). Порог — та зона, которая отвечает
        # на вопрос «какой темп даёт эта форма».
        return paces.pace_sec_per_km("T", vdot)

    metrics = MetricsCollector(
        detail_repo=detail_repo,
        fact_repo=fact_repo,
        athlete_repo=athlete_repo,
        vdot_pace_lookup=vdot_pace,
    )
    detail_importer = DetailImporter(
        fit_port=fit_port,
        detail_repo=detail_repo,
        fact_repo=fact_repo,
        athlete_repo=athlete_repo,
    )

    # Разбор текста пожеланий — через модель. Ключ в окружении сервиса;
    # без него кнопка «Предложить тренировку» просто недоступна, а
    # обычное планирование не ломается.
    composer_port = MiniMaxComposer()

    return AppContainer(
        storage=storage,
        season_repo=SeasonRepoAdapter(storage),
        fact_repo=fact_repo,
        athlete_repo=athlete_repo,
        methodology_repo=methodology,
        detail_repo=detail_repo,
        command_log=CommandLogAdapter(storage),
        activity_port=GarminActivityPort(),
        fit_port=fit_port,
        narrator_port=StubNarrator(),
        assessor=Assessor(),
        feasibility=feasibility,
        planner=planner,
        clock=SystemClock(),
        metrics=metrics,
        detail_importer=detail_importer,
        composer=WorkoutComposer(composer_port),
        composer_port=composer_port,
    )


def _target_vdot_for_metric(goal: Goal) -> float | None:
    """Перевести цель в целевой VDOT.

    Для дистанционных целей — по таблице Дэниэлса. Функция придёт из
    методологии после этапа 3б; пока работает простая формула по 10К.
    """
    if goal.discipline == "run_10k" and goal.metric_target:
        seconds = float(goal.metric_target)
        # приближение: VDOT ≈ 52 на 40:00, линейно по времени
        return max(30.0, 52.0 * (40 * 60) / seconds)
    return None


def get_container(request: Request) -> AppContainer:
    """Зависимость: собранное приложение.

    Контейнер один на процесс: он держит хранилище и сервисы, которые
    переиспользуются между запросами.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container


__all__ = [
    "AppContainer",
    "build_container",
    "get_container",
    "StubNarrator",
    "SystemClock",
]
