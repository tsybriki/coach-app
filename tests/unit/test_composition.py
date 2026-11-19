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

# Темпы настоящего спортсмена (VDOT 51) из таблицы Дэниэлса.
# Лёгкая зона здесь — 5:13, но лёгкий бег в приложении всегда 5:40.
REAL_PACE = {"E": 313.0, "M": 267.0, "T": 251.0, "I": 231.0, "R": 215.0}


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
    assert len(rest) == 8, 'у каждого круга свой отдых, включая последний'
    assert work[0].step.target_value == 400.0
    assert work[0].step.round == 1
    assert work[-1].step.round == 8


def repetition_intent(
    reps: int = 6,
    distance_m: float = 200.0,
    rest_m: float = 200.0,
) -> WorkoutIntent:
    """«6 по 200 через 200» — модель так и отдаёт."""
    return WorkoutIntent(
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.DISTANCE,
        target_value=distance_m,
        intent="interval",
        label="Интервальная тренировка",
        reps=reps,
        rest_type=TargetType.DISTANCE,
        rest_value=rest_m,
    )


def test_short_repeats_use_repetition_pace():
    """6 по 200 — повторный темп (R), а не интервальный (I).

    Короткие отрезки с отдыхом трусцой — это R по Дэниэлсу. Если взять
    темп зоны I, 200-метровые отрезки получатся заметно медленнее, чем
    должны быть.
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=REAL_PACE)

    work = [s.step for s in composition.steps if s.step.role is StepRole.WORK]
    assert work[0].focus is FocusType.PACE
    assert work[0].focus_value["pace_min_per_km"] == "3:35"  # R = 215 с/км


def test_longer_repeats_keep_interval_zone():
    """6 по 800 — это уже интервалы (I), а не повторный темп."""
    composition = build_steps(
        [repetition_intent(reps=6, distance_m=800.0, rest_m=200.0)],
        athlete=make_athlete(),
        pace_by_zone=REAL_PACE,
    )

    work = [s.step for s in composition.steps if s.step.role is StepRole.WORK]
    assert work[0].focus_value["zone"] == "Z7"
    assert work[0].focus_value["pace_min_per_km"] == "3:51"  # I = 231 с/км


def test_work_and_rest_alternate():
    """Шаги идут вперемешку: работа — отдых — работа.

    Раньше все работы шли подряд, и только после них — весь отдых.
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    roles = [s.step.role for s in composition.steps]
    assert roles.count(StepRole.WORK) == 6
    assert roles.count(StepRole.REST) == 6, 'у каждого круга свой отдых'
    assert roles == [
        StepRole.WORK, StepRole.REST,
        StepRole.WORK, StepRole.REST,
        StepRole.WORK, StepRole.REST,
        StepRole.WORK, StepRole.REST,
        StepRole.WORK, StepRole.REST,
        StepRole.WORK, StepRole.REST,
    ]


def test_set_distance_includes_rest():
    """Дистанция набора — работа ПЛЮС отдых.

    «6 по 200 через 200» — это 6 × (200 + 200) = 2400 м, а не 1200.
    Отдых на бегу — это пройденные метры, и итог должен совпадать с тем,
    что человек реально пробежал.
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    work_m = sum(
        s.step.target_value for s in composition.steps
        if s.step.role is StepRole.WORK
    )
    rest_m = sum(
        s.step.target_value for s in composition.steps
        if s.step.role is StepRole.REST
    )
    assert work_m == 1200.0
    assert rest_m == 1200.0
    assert composition.distance_m == 2400.0


def test_set_duration_includes_rest():
    """Время набора — работа ПЛЮС отдых.

    Отдых 200 м по 5:40 — это 1,13 минуты на круг; шесть кругов дают
    6,8 минуты отдыха сверх работы. Время шага округлено до сотых,
    поэтому сумма считается по округлённым шагам — как и показывает
    приложение.
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    work_min = sum(
        s.step.duration_min for s in composition.steps
        if s.step.role is StepRole.WORK
    )
    rest_min = sum(
        s.step.duration_min for s in composition.steps
        if s.step.role is StepRole.REST
    )
    assert work_min == pytest.approx(4.02)
    assert rest_min == pytest.approx(6.8, abs=0.05)
    assert composition.duration_min == pytest.approx(work_min + rest_min)


def test_set_has_round_blocks():
    """Набор разбит на круги, а у круга — свои блоки: работа и отдых.

    «6 по 200 через 200» — это повтор из 6 кругов, каждый круг — два
    блока: «200 м по 3:35» и «200 м по 5:40».
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    rounds = {s.step.round for s in composition.steps}
    assert rounds == {1, 2, 3, 4, 5, 6}
    # У круга два блока: работа и отдых.
    first_round = [s for s in composition.steps if s.step.round == 1]
    assert len(first_round) == 2
    assert first_round[0].step.role is StepRole.WORK
    assert first_round[1].step.role is StepRole.REST
    # Блок работы помечен: он первый в круге.
    assert first_round[0].step.focus_value["set_block"] == 1
    assert first_round[1].step.focus_value["set_block"] == 2


def test_set_round_carries_reps_and_block_count():
    """Шаг знает, в каком круге он и сколько блоков в круге."""
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    work = [s.step for s in composition.steps if s.step.role is StepRole.WORK]
    assert work[0].focus_value["set_reps"] == 6
    assert work[0].focus_value["set_blocks"] == 2


def test_rest_block_has_its_pace():
    """У блока отдыха свой темп: отдых 200 м — это «200 м по 5:40».

    Без темпа отдых в структуре выглядит пустым: «отдых» без объёма
    и скорости.
    """
    composition = build_steps(
        [repetition_intent()], athlete=make_athlete(), pace_by_zone=PACE)

    rest = [s.step for s in composition.steps if s.step.role is StepRole.REST]
    assert rest[0].focus_value["pace_min_per_km"] == "5:40"
    assert rest[0].focus_value["zone"] == "Z2"


def test_each_set_is_its_own_group():
    """Два набора — две группы, а не один блок на всю тренировку."""
    composition = build_steps(
        [repetition_intent(reps=6, distance_m=200.0, rest_m=200.0),
         repetition_intent(reps=5, distance_m=400.0, rest_m=0.0)],
        athlete=make_athlete(),
        pace_by_zone=PACE,
    )

    groups = {s.step.group for s in composition.steps if s.step.group}
    assert len(groups) == 2
    reps_by_group = {
        group: next(
            s.step.focus_value["set_reps"]
            for s in composition.steps
            if s.step.group == group and "set_reps" in s.step.focus_value
        )
        for group in groups
    }
    assert sorted(reps_by_group.values()) == [5, 6]


def test_group_name_describes_the_set():
    """Название группы — сам набор: сколько повторов, какой объём, отдых."""
    composition = build_steps(
        [repetition_intent(reps=6, distance_m=200.0, rest_m=200.0),
         repetition_intent(reps=5, distance_m=400.0, rest_m=0.0)],
        athlete=make_athlete(),
        pace_by_zone=PACE,
    )

    groups = {s.step.group for s in composition.steps if s.step.group}
    assert any("6×200" in g and "через 200" in g for g in groups)
    assert any("5×400" in g for g in groups)


def test_easy_steps_use_easy_pace_5_40():
    """Лёгкий бег — 5:40 на всех местах, включая разбор текста."""
    composition = build_steps(
        [easy_intent(5000.0)], athlete=make_athlete(), pace_by_zone=REAL_PACE)

    step = composition.steps[0].step
    assert step.focus_value["pace_min_per_km"] == "5:40"
    assert step.duration_min == pytest.approx(5000.0 / 1000.0 * 340.0 / 60.0, abs=0.01)


def test_composition_carries_intents_for_round_trip():
    """Намерения едут вместе с разбором — иначе повторы теряются."""
    intents = [easy_intent(5000.0), repetition_intent()]

    composition = build_steps(intents, athlete=make_athlete(), pace_by_zone=PACE)

    data = composition.as_dict()
    assert data["intents"][1]["reps"] == 6
    assert data["intents"][1]["rest_value"] == 200.0
    assert data["intents"][1]["rest_type"] == "distance"


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
