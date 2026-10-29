"""Сборка зависимостей.

Одно место, где собирается приложение: адаптеры, порты, сервисы. Ничего не
знает о порядке — только явные зависимости.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.adapters.storage.files import FileStorage
from app.adapters.storage.ports import (
    AthleteRepoAdapter,
    CommandLogAdapter,
    FactRepoAdapter,
    MethodologyRepoAdapter,
    SeasonRepoAdapter,
)
from app.domain.entities import ActualSession, Goal
from app.ports.storage import (
    ActivityPort,
    AthleteRepo,
    CommandLog,
    ExternalSourceError,
    FactRepo,
    MethodologyRepo,
    NarratorPort,
    SeasonRepo,
)
from app.services.assessment import Assessor
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

    На старте Garmin не подключён: команда `pull_fact` возвращает `degraded`.
    Подключение — отдельная задача (этап 6).
    """

    def pull(self, start: date, end: date, sport: str | None = None) -> list[ActualSession]:
        raise ExternalSourceError("garmin", "источник активностей не подключён")


@dataclass
class AppContainer:
    """Собранное приложение. Передаётся в FastAPI как зависимость."""

    storage: FileStorage
    season_repo: SeasonRepo
    fact_repo: FactRepo
    athlete_repo: AthleteRepo
    methodology_repo: MethodologyRepo
    command_log: CommandLog
    activity_port: ActivityPort
    narrator_port: NarratorPort
    assessor: Assessor
    feasibility: GoalFeasibility
    planner: WeekPlanner


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
    methodology = MethodologyRepoAdapter(storage)
    templates = methodology.workout_templates()
    load_model = methodology.load_model()
    athlete = AthleteRepoAdapter(storage).get()

    planner = WeekPlanner(
        templates=templates,
        load_model=load_model,
        athlete=athlete,
    )

    feasibility = GoalFeasibility(
        growth_rule=StubGrowthRule(),
        target_vdot_for_metric=_target_vdot_for_metric,
    )

    return AppContainer(
        storage=storage,
        season_repo=SeasonRepoAdapter(storage),
        fact_repo=FactRepoAdapter(storage),
        athlete_repo=AthleteRepoAdapter(storage),
        methodology_repo=methodology,
        command_log=CommandLogAdapter(storage),
        activity_port=UnavailableActivityPort(),
        narrator_port=StubNarrator(),
        assessor=Assessor(),
        feasibility=feasibility,
        planner=planner,
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


__all__ = ["AppContainer", "build_container", "StubNarrator"]
