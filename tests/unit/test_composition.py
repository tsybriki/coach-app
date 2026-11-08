"""Намерения тренировки и сборка из них шагов.

Модель возвращает намерения («порог», «8 км»), домен считает по ним
зоны, темпы и минуты. Здесь проверяется именно эта граница: модель не
придумывает числа, домен не выдумывает объём.
"""
from __future__ import annotations

import pytest

from app.domain.composition import (
    CompositionError,
    WorkoutIntent,
    build_steps,
    workout_from_composition,
)
from app.domain.entities import Athlete
from app.domain.enums import FocusType, Sport, StepRole, TargetType

# Темпы по зонам: E=лёгкая, T=порог, I=интервальная, R=повторная.
# Секунды на километр.
PACE = {"E": 330.0, "T": 240.0, "I": 220.0, "R": 200.0, "M": 270.0}


def make_athlete() -> Athlete:
    return Athlete(
        vdot=50.0,
        hr_zones={
            "Z1": (95, 110),
            "Z2": (111, 130),
            "Z3": (131, 145),
            "Z4": (146, 158),
            "Z5": (159, 168),
            "Z7": (172, 182),
        },
        hr_max=182,
        rhr=50,
        lth=164,
    )


def easy_intent(distance_m: float = 3000.0) -> WorkoutIntent:
    return WorkoutIntent(
        role=StepRole.WARMUP,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=distance_m,
        intent="easy",
        label="Разминка",
    )


def test_threshold_intent_gives_pulse_zone_of_athlete():
    """«Порог» → зона пульса атлета и темп по его форме."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=8000.0,
        intent="threshold",
        label="Фартлек",
    )]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    step = composition.steps[0].step
    assert step.focus is FocusType.HR
    assert step.focus_value["zone"] == "Z5"
    assert step.focus_value["pace_min_per_km"] == "4:00"
    # Намерение сохраняется в шаге: по нему видно, что за работа.
    assert step.focus_value["intent"] == "threshold"


def test_duration_is_counted_by_domain_not_by_model():
    """Модель сказала метры — домен посчитал минуты по темпу."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=8000.0,
        intent="threshold",
    )]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    # 8 км по 240 с/км = 1920 с = 32 минуты.
    assert composition.steps[0].step.duration_min == pytest.approx(32.0)
    assert composition.duration_min == pytest.approx(32.0)


def test_time_intent_keeps_its_minutes():
    """Шаг «по времени» — минуты из текста."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=20.0,
        intent="threshold",
    )]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    assert composition.steps[0].step.duration_min == 20.0
    assert composition.distance_m == 0.0


def test_reps_become_separate_steps():
    """«8 по 400» — восемь шагов по 400 метров."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=400.0,
        intent="interval",
        label="8 по 400",
        reps=8,
        rest_type=TargetType.TIME,
        rest_value=1.5,
    )]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    work = [s for s in composition.steps if s.step.role is StepRole.WORK]
    rest = [s for s in composition.steps if s.step.role is StepRole.REST]
    assert len(work) == 8
    assert len(rest) == 7, 'отдых — между повторами, не после последнего'
    assert work[0].step.target_value == 400.0
    assert work[0].step.round == 1
    assert work[-1].step.round == 8


def test_assumptions_are_carried_through():
    """Что модель додумала — видно в разборе."""
    intents = [easy_intent()]

    composition = build_steps(
        intents,
        athlete=make_athlete(),
        pace_by_zone=PACE,
        assumptions=["разминка добавлена мной"],
    )

    assert "разминка добавлена мной" in composition.assumptions
    assert composition.as_dict()["assumptions"] == ["разминка добавлена мной"]


def test_steps_without_distance_get_no_time_and_say_so():
    """Нет темпа — время шага неизвестно, и это сказано вслух."""
    intents = [WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=5000.0,
        intent="threshold",
    )]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone={})

    assert composition.steps[0].step.duration_min == 0.0
    assert composition.steps[0].assumption
    assert any("темп" in a for a in composition.assumptions)


def test_empty_intents_is_an_error():
    """Нет шагов — это ошибка, а не пустая тренировка."""
    with pytest.raises(CompositionError):
        build_steps([], athlete=make_athlete(), pace_by_zone=PACE)


def test_workout_from_composition_is_ordinary_workout():
    """Разбор даёт обычную тренировку: те же поля, те же инварианты."""
    intents = [easy_intent(3000.0), WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=8000.0,
        intent="threshold",
        label="Фартлек",
    )]
    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    workout = workout_from_composition(
        composition, workout_id="w-1", request_id="r-1")

    assert workout.id == "w-1"
    assert workout.request_id == "r-1"
    assert len(workout.steps) == 2
    assert workout.duration_min == pytest.approx(
        sum(s.duration_min for s in workout.steps), abs=0.01)
    assert workout.objective["name"]
    # Инварианты тренировки должны держаться: длительность = Σ шагов.
    workout.validate()
