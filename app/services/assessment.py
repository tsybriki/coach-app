"""Оценка: сопоставить план с фактом и посчитать итог недели.

Связь план↔факт ставится **вручную**: автоматики нет. Всё, что не связано,
учитывается в actuals: связывание уточняет отчёт, но не решает, что считать
сделанным.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.derivations import (
    actual_intensity_min,
    facts_in_week_range,
    plan_week_totals,
    unplaced_without_fact_is_missed,
    week_contributions,
)
from app.domain.entities import ActualSession, Week, WeekSummary, Workout
from app.domain.enums import Verdict, WorkoutStatus


@dataclass
class LinkRequest:
    """Запрос на связывание: факт с плановой тренировкой."""

    actual_id: str
    workout_id: str


@dataclass
class AssessmentResult:
    """Результат оценки недели: сводка и свод по сессиям."""

    summary: WeekSummary
    linked: list[LinkRequest]
    unlinked_facts: list[str]


class Assessor:
    """Считает итог недели по плану и факту."""

    def assess(
        self,
        week: Week,
        sessions: list[ActualSession],
        closed_at: str | None = None,
    ) -> AssessmentResult:
        """Оценить неделю.

        Шаги: берём факт недели по датам → считаем contributions → строим
        саммари → определяем вердикты по сессиям.
        """
        in_range = facts_in_week_range(week, sessions)

        linked: list[LinkRequest] = []
        for workout in week.workouts:
            if workout.actual_id:
                linked.append(LinkRequest(actual_id=workout.actual_id,
                                          workout_id=workout.id))

        unlinked = [s.id for s in in_range if s.linked_workout_id is None]

        plan_totals = plan_week_totals(week)
        intensity = actual_intensity_min(in_range)
        contributions = week_contributions(week, in_range)

        summary = WeekSummary(
            week_id=week.id,
            closed_at=closed_at,
            totals={
                "planned_minutes": plan_totals["minutes"],
                "actual_minutes": float(sum(s.duration_min for s in in_range)),
                "planned_sessions": plan_totals["sessions"],
                "actual_sessions": float(len(in_range)),
            },
            per_session=self._per_session(week, in_range),
            verdict=self._verdict(week, in_range),
            missed=unplaced_without_fact_is_missed(week, in_range),
            extra=unlinked,
            deviations=self._deviations(plan_totals, in_range),
            intensity={
                "actual_moderate": intensity["moderate"],
                "actual_vigorous": intensity["vigorous"],
                "contributions": contributions,
            },
        )
        return AssessmentResult(summary=summary, linked=linked,
                                 unlinked_facts=unlinked)

    def _per_session(
        self,
        week: Week,
        sessions: list[ActualSession],
    ) -> list[dict[str, object]]:
        """Сопоставление по сессиям: request_id, actual_id, verdict."""
        by_workout = {s.linked_workout_id: s for s in sessions if s.linked_workout_id}
        rows: list[dict[str, object]] = []
        for workout in week.workouts:
            actual = by_workout.get(workout.id)
            rows.append({
                "request_id": workout.request_id,
                "actual_id": actual.id if actual else None,
                "verdict": self._session_verdict(workout, actual),
            })
        return rows

    def _session_verdict(
        self,
        workout: Workout,
        actual: ActualSession | None,
    ) -> Verdict:
        """Вердикт по сессии: по связанному факту."""
        if actual is None:
            if workout.status is WorkoutStatus.SKIPPED:
                return Verdict.MISSED
            return Verdict.MISSED
        return Verdict.DONE

    def _verdict(
        self,
        week: Week,
        sessions: list[ActualSession],
    ) -> dict[str, int]:
        """Счётчики вердиктов по всей неделе."""
        counts = {v.value: 0 for v in Verdict}
        for row in self._per_session(week, sessions):
            verdict = row["verdict"]
            if isinstance(verdict, Verdict):
                counts[verdict.value] += 1
        for actual in sessions:
            if actual.linked_workout_id is None:
                counts[Verdict.EXTRA.value] += 1
        return counts

    def _deviations(
        self,
        plan_totals: dict[str, float],
        sessions: list[ActualSession],
    ) -> list[dict[str, object]]:
        """Отклонения недели: факт − план по каждой метрике."""
        actual_minutes = float(sum(s.duration_min for s in sessions))
        actual_distance = float(sum(s.distance_m for s in sessions))
        planned_distance = 0.0

        deviations: list[dict[str, object]] = []
        deviations.append({
            "metric": "minutes",
            "planned": plan_totals["minutes"],
            "actual": actual_minutes,
            "reason": "",
        })
        deviations.append({
            "metric": "distance_m",
            "planned": planned_distance,
            "actual": actual_distance,
            "reason": "",
        })
        return deviations
