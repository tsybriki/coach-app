"""Метрики формы: сбор по неделе и по тренировке.

**Что где считается.** Разбор FIT — дорогая операция, поэтому он
хранится (см. `WorkoutDetail`), а метрики считаются из сохранённого
разбора при запросе: считать заново каждый раз незачем, а хранить
вторым экземпляром нельзя (правило «источник правды один»).

**Что считается при загрузке тренировки, а что — при закрытии недели.**
Метрики одной тренировки доступны сразу после загрузки факта — они
считаются из её разбора. Метрики недели — агрегат по тренировкам —
считаются при закрытии недели и кладутся в `WeekSummary`. Для текущей
недели тот же агрегат считается на лету, чтобы видеть его до закрытия.

Метрики без данных — `None`, а не ноль: пустое значение честнее нуля.
"""
from __future__ import annotations

from collections.abc import Callable

from app.domain.entities import ActualSession, Athlete, Week
from app.domain.metrics import (
    WeekMetrics,
    WorkoutMetrics,
    week_metrics,
    workout_metrics,
)
from app.ports.storage import AthleteRepo, DetailRepo, FactRepo


class MetricsCollector:
    """Собирает метрики из факта и разборов.

    Держит доступ к хранилищу: разборы лежат рядом с фактом, а FTP
    и VDOT — в профиле атлета.
    """

    def __init__(
        self,
        detail_repo: DetailRepo,
        fact_repo: FactRepo,
        athlete_repo: AthleteRepo,
        vdot_pace_lookup: Callable[[float], float | None] | None = None,
    ) -> None:
        self._detail_repo = detail_repo
        self._fact_repo = fact_repo
        self._athlete_repo = athlete_repo
        # Темп, соответствующий VDOT: секунды на километр. Приходит
        # снаружи, потому что считается по таблице Дэниэлса.
        self._vdot_pace_lookup = vdot_pace_lookup

    def athlete(self) -> Athlete:
        """Профиль атлета — из порта."""
        return self._athlete_repo.get()

    def workout(self, actual_id: str) -> WorkoutMetrics:
        """Метрики одной тренировки — из её разбора и факта."""
        detail = self._detail_repo.detail(actual_id)
        session = self._detail_repo_session(actual_id)
        athlete = self.athlete()
        return workout_metrics(
            detail=detail,
            session=session,
            ftp_w=athlete.ftp_w,
            vdot=athlete.vdot,
            vdot_pace_sec_per_km=self._vdot_pace(athlete.vdot),
        )

    def week(self, week: Week, sessions: list[ActualSession]) -> WeekMetrics:
        """Метрики недели — по всем её сессиям.

        Считается по **всем** активностям недели, а не по связанным:
        выполненный забег вкладывается в форму независимо от того,
        связал его пользователь с тренировкой или нет.
        """
        per_workout: list[WorkoutMetrics] = []
        vo2max_values: list[float] = []

        for session in sessions:
            detail = self._detail_repo.detail(session.id)
            if detail is None:
                continue
            athlete = self.athlete()
            metrics = workout_metrics(
                detail=detail,
                session=session,
                ftp_w=athlete.ftp_w,
                vdot=athlete.vdot,
                vdot_pace_sec_per_km=self._vdot_pace(athlete.vdot),
            )
            per_workout.append(metrics)
            if session.vo2max:
                vo2max_values.append(float(session.vo2max))

        return week_metrics(
            week_id=week.id,
            per_workout=per_workout,
            vo2max_values=vo2max_values,
        )

    def _detail_repo_session(self, actual_id: str) -> ActualSession | None:
        """Факт по id — через порт факта."""
        return self._fact_repo.get(actual_id) if self._fact_repo else None

    def _vdot_pace(self, vdot: float) -> float | None:
        """Темп по VDOT — секунды на километр."""
        if not self._vdot_pace_lookup or not vdot:
            return None
        pace: float | None = self._vdot_pace_lookup(vdot)
        return pace


__all__ = ["MetricsCollector"]
