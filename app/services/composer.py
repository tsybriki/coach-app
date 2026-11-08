"""Сервис «предложить тренировку».

Связывает три вещи: текст пожеланий, модель (через порт) и домен.

**Домен решает числа.** Модель возвращает намерения («порог», «8 км»),
домен по профилю атлета и таблице Дэниэлса подставляет зону пульса, темп
и длительность. Если модель ошиблась в числах — это ошибка домена, а не
модели, и её видно.

**Деградация вместо отказа.** Если модель недоступна — понятное
сообщение, а не поломка планирования: обычная неделя планируется как
раньше.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.composition import (
    Composition,
    CompositionError,
    WorkoutIntent,
    build_steps,
    workout_from_composition,
)
from app.domain.entities import Athlete, Week, Workout
from app.ports.storage import (
    ComposeContext,
    WorkoutComposerPort,
)


@dataclass
class ComposeOutcome:
    """Разбор текста: тренировка и что модель додумала.

    `workout` — готовая тренировка домена. `workout_id`/`request_id`
    заполняются только при добавлении в неделю: пока тренировка просто
    показана, она нигде не живёт.
    """

    composition: Composition
    source_text: str

    def as_dict(self) -> dict[str, object]:
        data = self.composition.as_dict()
        data["source_text"] = self.source_text
        return data


class WorkoutComposer:
    """Разбор пожеланий в тренировку."""

    def __init__(self, port: WorkoutComposerPort) -> None:
        self.port = port

    @property
    def available(self) -> bool:
        """Доступен ли разбор.

        Нет ключа модели — кнопку «Предложить тренировку» лучше не
        показывать, чем показывать и отказывать.
        """
        return bool(getattr(self.port, "available", True))

    def compose(
        self,
        text: str,
        athlete: Athlete,
        pace_by_zone: dict[str, float],
        *,
        week: Week | None = None,
    ) -> ComposeOutcome:
        """Текст пожеланий → структура тренировки.

        `pace_by_zone` — темпы по зонам правила, секунды на километр: по ним
        домен считает минуты шага.
        """
        text = (text or "").strip()
        if not text:
            raise CompositionError("опиши тренировку — пустым текстом её не сделать")

        context = self._context(athlete, pace_by_zone, week)
        plan = self.port.compose(text, context)
        intents: list[WorkoutIntent] = [
            intent for intent in plan.intents
            if isinstance(intent, WorkoutIntent)
        ]
        if not intents:
            raise CompositionError("из текста не получилось сделать ни одного шага")

        composition = build_steps(
            intents,
            athlete=athlete,
            pace_by_zone=pace_by_zone,
            assumptions=list(plan.assumptions),
        )
        # Название от модели приоритетнее собранного из состава: человек
        # назвал тренировку сам.
        name = str(getattr(plan, "name", "") or "").strip() or composition.name
        return ComposeOutcome(
            composition=Composition(
                name=name,
                sport=composition.sport,
                steps=composition.steps,
                assumptions=composition.assumptions,
                source_text=text,
            ),
            source_text=text,
        )

    def workout_from(
        self,
        outcome: ComposeOutcome,
        *,
        workout_id: str,
        request_id: str,
    ) -> Workout:
        """Готовая тренировка домена из разбора."""
        return workout_from_composition(
            outcome.composition,
            workout_id=workout_id,
            request_id=request_id,
        )

    def _context(
        self,
        athlete: Athlete,
        pace_by_zone: dict[str, float],
        week: Week | None,
    ) -> ComposeContext:
        """Контекст для модели: кто спортсмен и какая сейчас неделя."""
        zones = {
            name: (int(low), int(high))
            for name, (low, high) in (athlete.hr_zones or {}).items()
        }
        target = (week.load_target or {}) if week else {}
        return ComposeContext(
            vdot=athlete.vdot,
            hr_zones=zones,
            hr_max=athlete.hr_max,
            week_load_km=float(target.get("distance_m") or 0.0) / 1000.0,
            week_load_hours=float(target.get("hours") or 0.0),
            pace_by_zone=pace_by_zone,
        )


__all__ = ["ComposeOutcome", "WorkoutComposer"]
