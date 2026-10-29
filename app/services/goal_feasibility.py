"""Достижимость цели: шаг 1 планировщика.

Функция методологии (решение №5): правило роста формы живёт в методологии,
вердикт считает планировщик. Пока правило — заглушка, ответ честный:
«не могу оценить», а не выдуманное число.

Вход: Goal (метрика + дата) + профиль атлета + правило роста.
Выход: вердикт + варианты, если цель недостижима.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

from app.domain.entities import Athlete, Goal


class VerdictKind(StrEnum):
    """Вердикт по достижимости цели."""

    ACHIEVABLE = "achievable"
    ACHIEVABLE_WITH_CAVEATS = "achievable_with_caveats"
    NOT_ACHIEVABLE = "not_achievable"
    CANNOT_ESTIMATE = "cannot_estimate"


@dataclass
class FeasibilityVerdict:
    """Вердикт по цели: достижима ли и что предлагать."""

    kind: VerdictKind
    reason: str
    target_metric: float | None = None
    current_metric: float | None = None
    gap: float | None = None
    options: list[str] = field(default_factory=list)

    @property
    def is_achievable(self) -> bool:
        return self.kind in (VerdictKind.ACHIEVABLE, VerdictKind.ACHIEVABLE_WITH_CAVEATS)


class GrowthRule(Protocol):
    """Правило роста формы — часть методологии.

    Пока это заглушка: правила нет, и вердикту не из чего выводиться.
    """

    def estimate(self, current: float, target: float, days: int) -> float | None:
        """Потолок формы к дате цели. None — оценить нечем."""
        ...


class MetricToVdot(Protocol):
    """Перевод метрики цели в целевой VDOT."""

    def __call__(self, goal: Goal) -> float | None:
        ...


@dataclass
class StubGrowthRule:
    """Заглушка правила роста формы.

    Правило не задано — вердикт честно отвечает «не могу оценить».
    Заглушка ставится явно, чтобы её нельзя было принять за рабочее правило.
    """

    reason: str = "правило роста формы не задано"

    def estimate(self, current: float, target: float, days: int) -> float | None:
        """Потолок формы к дате цели. None — оценить нечем."""
        return None


@dataclass
class LinearGrowthRule:
    """Простое линейное правило: прирост в единицах VDOT за неделю.

    Заглушка заменяется этим, когда рабочее правило будет выбрано. Пока
    используется только как пример формата, не как утверждённая методика.
    """

    vdot_per_week: float

    def estimate(self, current: float, target: float, days: int) -> float | None:
        weeks = days / 7.0
        return current + self.vdot_per_week * weeks


@dataclass
class GoalFeasibility:
    """Оценка достижимости цели.

    Держит правило роста формы и умеет переводить цель в целевой VDOT.
    """

    growth_rule: GrowthRule
    target_vdot_for_metric: MetricToVdot

    def assess(
        self,
        goal: Goal,
        athlete: Athlete,
        today: date,
    ) -> FeasibilityVerdict:
        """Оценить достижимость цели.

        Шаги:
        1. перевести цель в целевой VDOT;
        2. взять текущую форму атлета;
        3. оценить потолок к дате цели по правилу роста;
        4. вынести вердикт.
        """
        target_vdot = self.target_vdot_for_metric(goal)
        if target_vdot is None:
            return FeasibilityVerdict(
                kind=VerdictKind.CANNOT_ESTIMATE,
                reason="цель не переводится в целевой VDOT",
            )

        current_vdot = athlete.vdot
        days = (goal.race_date - today).days
        if days < 0:
            return FeasibilityVerdict(
                kind=VerdictKind.NOT_ACHIEVABLE,
                reason="дата цели уже прошла",
                target_metric=target_vdot,
                current_metric=current_vdot,
            )

        ceiling = self.growth_rule.estimate(current_vdot, target_vdot, days)
        if ceiling is None:
            return FeasibilityVerdict(
                kind=VerdictKind.CANNOT_ESTIMATE,
                reason="правило роста формы не задано — оценить потолок нечем",
                target_metric=target_vdot,
                current_metric=current_vdot,
                gap=target_vdot - current_vdot,
                options=[
                    "задать правило роста формы в методологии",
                    "выбрать другую цель",
                ],
            )

        gap = target_vdot - current_vdot
        if ceiling >= target_vdot:
            return FeasibilityVerdict(
                kind=VerdictKind.ACHIEVABLE,
                reason=f"потолок {ceiling:.1f} VDOT покрывает цель {target_vdot:.1f}",
                target_metric=target_vdot,
                current_metric=current_vdot,
                gap=gap,
            )
        if ceiling >= current_vdot + gap * 0.8:
            return FeasibilityVerdict(
                kind=VerdictKind.ACHIEVABLE_WITH_CAVEATS,
                reason=(
                    f"потолок {ceiling:.1f} VDOT покрывает цель {target_vdot:.1f} "
                    f"не полностью — разрыв {gap:.1f}"
                ),
                target_metric=target_vdot,
                current_metric=current_vdot,
                gap=gap,
                options=["сдвинуть дату цели", "принять меньшую амбицию"],
            )
        return FeasibilityVerdict(
            kind=VerdictKind.NOT_ACHIEVABLE,
            reason=(
                f"потолок {ceiling:.1f} VDOT не дотягивает до цели {target_vdot:.1f} "
                f"(разрыв {gap:.1f})"
            ),
            target_metric=target_vdot,
            current_metric=current_vdot,
            gap=gap,
            options=[
                "смягчить метрику цели",
                "сдвинуть дату цели",
                "взять наилучшую достижимую цель",
            ],
        )
