"""
Название тренировки — из её состава.

Дефект, который это ловит: все пробежки недели назывались «Проверяем
форму на контрольной точке» (фокус недели копировался в каждую
тренировку). По такому названию нельзя отличить лёгкую пробежку от
длинной, а «Длинный бег + отрезки» от «Лёгкого бега» — тем более.

И название собирается из шагов, поэтому разойтись с содержимым оно не
может: нет отрезков — нет и слова «отрезки».
"""
from __future__ import annotations

from typing import Any

from app.domain.entities import Step
from app.domain.enums import FocusType, Sport, StepRole, TargetType
from app.domain.session_name import (
    EASY_PACE_MIN_PER_KM,
    EASY_PACE_SEC_PER_KM,
    easy_pace_sec_per_km,
    session_name,
    step_description,
)


def step(**kw: Any) -> Step:
    base: dict[str, Any] = dict(
        id="s1",
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=40.0,
        focus=FocusType.HR,
        focus_value={},
        duration_min=40.0,
    )
    base.update(kw)
    return Step(**base)


def easy_step(minutes: float = 40.0) -> Step:
    return step(focus_value={"zone": "Z2", "pace_min_per_km": "5:30"},
                duration_min=minutes)


def stride_step() -> Step:
    return step(
        id="s2",
        target_type=TargetType.DISTANCE,
        target_value=100.0,
        focus_value={"pace_min_per_km": "3:35", "set_reps": 8,
                     "daniels_zone": "R"},
        duration_min=0.36,
    )


def ofp_step() -> Step:
    return step(
        id="s3",
        target_type=TargetType.REPS,
        target_value=1.0,
        focus_value={"ofp": True, "reps": "3×45с"},
        duration_min=1.8,
    )


def test_easy_run_is_named_by_its_composition():
    """Лёгкая пробежка без отрезков — «Лёгкий бег»."""
    name = session_name("easy", Sport.RUN, [easy_step()])
    assert name == "Лёгкий бег"


def test_long_run_has_its_own_name():
    """Длинный пробежек — «Длинный бег», а не «Лёгкий бег»."""
    name = session_name("long", Sport.RUN, [easy_step(77.0)])
    assert name == "Длинный бег"


def test_easy_run_with_strides_says_so():
    """Есть отрезки — название их называет."""
    name = session_name("easy", Sport.RUN, [easy_step(), stride_step()])
    assert name == "Лёгкий бег + отрезки"


def test_easy_run_with_ofp_says_so():
    """Есть ОФП — название его называет."""
    name = session_name("easy", Sport.RUN, [easy_step(), ofp_step()])
    assert name == "Лёгкий бег + ОФП"


def test_easy_run_with_strides_and_ofp():
    """Отрезки и ОФП вместе — оба в названии."""
    name = session_name("easy", Sport.RUN,
                        [easy_step(), stride_step(), ofp_step()])
    assert name == "Лёгкий бег + отрезки + ОФП"


def test_name_never_mentions_control_point():
    """В названии тренировки нет цели недели.

    Цель недели — про объём, а название тренировки — про её состав.
    """
    for kind in ("easy", "long", "quality"):
        name = session_name(kind, Sport.RUN, [easy_step()])
        assert "контрольной точке" not in name.lower(), name
        assert "проверяем форму" not in name.lower(), name


def test_bike_and_swim_named_by_sport():
    """Вел и плавание — по виду спорта."""
    assert session_name("bike", Sport.BIKE, [step(sport=Sport.BIKE)]) \
        == "Велосипед"
    assert session_name("swim", Sport.SWIM, [step(sport=Sport.SWIM)]) \
        == "Плавание"


def test_base_name_wins_over_kind():
    """Заданная основа важнее вида работы.

    Форма фазы даёт «Длинный бег» для пробежки, у которой вид работы —
    `easy`: основа оттуда и есть настоящая.
    """
    name = session_name("easy", Sport.RUN, [easy_step(77.0)],
                        base="Длинный бег")
    assert name == "Длинный бег"


def test_easy_pace_is_530_not_daniels_top_of_zone():
    """Лёгкий темп — 5:30, а не 5:13.

    «E» по таблице Дэниэлса для VDOT 51 — это верх лёгкой зоны: на
    длинной дистанции в нём HR упирается в верх Z2, и «лёгкий бег»
    перестаёт быть лёгким. Середина зоны — 5:30.
    """
    assert EASY_PACE_MIN_PER_KM == "5:30"
    assert EASY_PACE_SEC_PER_KM == 330.0


def test_easy_pace_ignores_daniels_table():
    """Таблица Дэниэлса не переопределяет решение по лёгкому темпу."""
    # Таблица даёт 313 секунд на км (5:13) для зоны E.
    table = {"E": 313.0, "R": 215.0}
    assert easy_pace_sec_per_km(table) == 330.0


def test_easy_pace_is_none_without_table():
    """Нет таблицы — нет темпа, а не выдуманный."""
    assert easy_pace_sec_per_km({}) is None


def test_step_description_of_distance_step():
    """Описание шага с дистанцией — расстояние."""
    s = step(target_type=TargetType.DISTANCE, target_value=7348.0,
             duration_min=38.33,
             focus_value={"zone": "Z2", "pace_min_per_km": "5:30"})
    text = step_description(s)
    assert "7.3 км" in text, text
    assert "5:30" in text, text


def test_step_description_of_time_step():
    """Описание шага со временем — время."""
    s = step(target_type=TargetType.TIME, target_value=15.0, duration_min=15.0,
             focus_value={"zone": "Z1"})
    assert "15 мин" in step_description(s), step_description(s)


def test_step_description_of_ofp_step():
    """Описание шага ОФП — упражнение."""
    s = ofp_step()
    assert "ОФП" in step_description(s)
    assert "3×45с" in step_description(s)
