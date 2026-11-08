"""Тесты метрик формы.

Метрики: объём в зонах пульса, темп в зоне, нагрузка (TSS), форма,
эффективность, каденция. Плюс недельный агрегат.

Имена тестов — по смыслу, не по номерам инвариантов: метрики новые,
инвариантов на них нет.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import ActualSession, Split, WorkoutDetail
from app.domain.enums import FactSource, Sport
from app.domain.metrics import (
    cadence_in_work,
    efficiency,
    estimate_ftp,
    pace_in_zone,
    tss_from_power,
    week_metrics,
    workout_metrics,
)


def make_detail(**kw) -> WorkoutDetail:
    """Разбор тренировки — с заданными величинами."""
    detail = WorkoutDetail(
        actual_id="a1",
        source=FactSource.GARMIN,
        duration_s=3600.0,
        elapsed_s=3600.0,
        distance_m=10000.0,
        avg_hr=140,
        avg_cadence=80,
    )
    for key, value in kw.items():
        setattr(detail, key, value)
    return detail


def make_session(**kw) -> ActualSession:
    """Факт тренировки — с заданными величинами."""
    base = ActualSession(
        id="a1",
        date=date(2026, 10, 15),
        sport=Sport.RUN,
        duration_min=60,
        distance_m=10000.0,
        hr_avg=140,
    )
    for key, value in kw.items():
        setattr(base, key, value)
    return base


# ------------------------------------------------------------------ зоны


def test_zone_minutes_are_read_from_detail():
    """Метрики 1–3: минуты в зонах пульса — из разбора."""
    detail = make_detail(hr_zone_minutes={
        "Z1": 10.0, "Z2": 30.0, "Z3": 12.0, "Z4": 5.0,
        "Z5": 3.0, "Z6": 1.0, "Z7": 2.0,
    })

    metrics = workout_metrics(detail=detail, session=make_session())

    assert metrics.z2_min == 30.0
    assert metrics.z3_min == 12.0
    assert metrics.z4_min == 5.0
    # Интенсивность — Z5–Z7 вместе.
    assert metrics.hi_min == 6.0


def test_metrics_without_detail_have_no_zones():
    """Без разбора метрик нет — а не нули."""
    metrics = workout_metrics(detail=None, session=make_session())

    assert metrics.z2_min is None
    assert metrics.z3_min is None
    assert metrics.hi_min is None
    assert metrics.workout_counted is False


def test_empty_zone_is_none_not_zero():
    """Зона, в которой тренировки не было, — `None`, а не ноль.

    Ноль означал бы «было 0 минут в зоне», а `None` — «не знаем».
    """
    detail = make_detail(hr_zone_minutes={"Z2": 30.0})

    metrics = workout_metrics(detail=detail, session=make_session())

    assert metrics.z2_min == 30.0
    assert metrics.z3_min is None


# ------------------------------------------------------------------ темп в зоне


def test_pace_in_zone_uses_only_running_seconds():
    """Метрика 5: темп в Z2 — по секундным рядам, без отдыха.

    Разминка (пульс 110) и работа (пульс 160) в ответ не входят:
    иначе «темп на пульсе до 135» отвечал бы на другой вопрос.
    """
    detail = make_detail(
        hr_zone_minutes={"Z1": 10.0, "Z2": 20.0, "Z3": 10.0},
        series_hr=[(0, 110), (60, 128), (120, 128), (180, 160)],
        series_distance=[(0, 0.0), (60, 200.0), (120, 400.0), (180, 450.0)],
        series_cadence=[(0, 78), (60, 82), (120, 82), (180, 84)],
    )

    pace = pace_in_zone(detail, "Z2", {"Z2": 20.0})

    # 200 м за 60 с в Z2 → 300 с/км
    assert pace == pytest.approx(300.0)


def test_pace_in_zone_excludes_rest():
    """Отдых внутри зоны не считается: человек стоял, а не бежал.

    Без отсева по каденции «темп в Z2» показывал бы темп трубки.
    """
    detail = make_detail(
        hr_zone_minutes={"Z2": 20.0},
        series_hr=[(0, 125), (60, 125), (120, 125)],
        series_distance=[(0, 0.0), (60, 5.0), (120, 205.0)],
        series_cadence=[(0, 80), (60, 40), (120, 80)],
    )

    pace = pace_in_zone(detail, "Z2", {"Z2": 20.0})

    # Первые 60 с — стоял (каденция 40), в счёт не идут.
    # Осталось 200 м за 60 с → 300 с/км
    assert pace == pytest.approx(300.0)


def test_pace_in_zone_is_none_when_zone_absent():
    """Зоны не было — темпа нет."""
    detail = make_detail(series_hr=[(0, 128), (60, 128)],
                         series_distance=[(0, 0.0), (60, 200.0)])

    assert pace_in_zone(detail, "Z2", {"Z1": 10.0}) is None


def test_pace_in_zone_is_none_without_series():
    """Без рядов темп не посчитать."""
    assert pace_in_zone(make_detail(), "Z2", {"Z2": 10.0}) is None


# ------------------------------------------------------------------ TSS


def test_tss_follows_training_peaks_formula():
    """Метрика 8: TSS = (часы × NP × IF) / FTP × 100.

    Час при NP = FTP даёт TSS 100 — это определение.
    """
    tss = tss_from_power(elapsed_s=3600.0, normalized_power_w=250.0, ftp_w=250.0)

    assert tss == pytest.approx(100.0)


def test_tss_scales_with_intensity():
    """Половинная интенсивность — половина нагрузки."""
    easy = tss_from_power(elapsed_s=3600.0, normalized_power_w=200.0, ftp_w=250.0)
    hard = tss_from_power(elapsed_s=3600.0, normalized_power_w=250.0, ftp_w=250.0)

    assert easy == pytest.approx(64.0)
    assert hard == pytest.approx(100.0)


def test_tss_scales_with_duration():
    """Два часа дают вдвое больше нагрузки, чем час."""
    one_hour = tss_from_power(elapsed_s=3600.0, normalized_power_w=250.0, ftp_w=250.0)
    two_hours = tss_from_power(elapsed_s=7200.0, normalized_power_w=250.0, ftp_w=250.0)

    assert two_hours == pytest.approx(2 * one_hour)


def test_tss_without_ftp_is_none():
    """Без FTP нагрузку не посчитать — метрика не появляется.

    Подставлять выдуманный порог нельзя: получится правдоподобная
    цифра, которой никто не мерил.
    """
    assert tss_from_power(3600.0, 250.0, None) is None
    assert tss_from_power(3600.0, 250.0, 0) is None


def test_metrics_have_no_tss_without_ftp():
    """Тренировка без FTP в профиле — без нагрузки."""
    detail = make_detail(hr_zone_minutes={"Z2": 30.0},
                          normalized_power_w=250.0)

    metrics = workout_metrics(detail=detail, session=make_session(), ftp_w=None)

    assert metrics.tss is None
    assert metrics.intensity_factor is None


def test_metrics_have_tss_with_ftp():
    """С FTP нагрузка считается."""
    detail = make_detail(hr_zone_minutes={"Z2": 30.0},
                          normalized_power_w=250.0)

    metrics = workout_metrics(detail=detail, session=make_session(), ftp_w=250.0)

    assert metrics.tss == pytest.approx(100.0)
    assert metrics.intensity_factor == pytest.approx(1.0)


# ------------------------------------------------------------------ форма


def test_vo2max_comes_from_fact():
    """Метрика 11: форма — из факта Garmin."""
    metrics = workout_metrics(
        detail=make_detail(), session=make_session(vo2max=51.0))

    assert metrics.vo2max == 51.0


def test_efficiency_compares_actual_pace_to_form_pace():
    """Метрика 12: эффективность формы.

    Темп по форме 240 с/км, фактический 260 с/км → 0,923:
    фактический темп хуже расчётного.
    """
    detail = make_detail(duration_s=2600.0, distance_m=10000.0)

    metrics = workout_metrics(
        detail=detail, session=make_session(), vdot_pace_sec_per_km=240.0)

    assert metrics.efficiency == pytest.approx(240.0 / 260.0, abs=0.001)


def test_efficiency_is_none_without_form_pace():
    """Без темпа по форме эффективности нет."""
    metrics = workout_metrics(
        detail=make_detail(), session=make_session(), vdot_pace_sec_per_km=None)

    assert metrics.efficiency is None


def test_efficiency_helper_directly():
    """Проверка самого правила: больше 1 — фактический темп лучше."""
    assert efficiency(240.0, 260.0) == pytest.approx(260.0 / 240.0)
    assert efficiency(None, 260.0) is None


# ------------------------------------------------------------------ каденция


def test_cadence_in_work_excludes_warmup():
    """Метрика 14: каденция в рабочей части — без разминки.

    Сплит с пульсом 100 — разминка, в счёт не идёт.
    """
    detail = make_detail(splits=[
        Split(index=1, duration_s=600.0, distance_m=2500.0, avg_hr=100,
              avg_cadence=60),
        Split(index=2, duration_s=600.0, distance_m=2500.0, avg_hr=150,
              avg_cadence=82),
        Split(index=3, duration_s=600.0, distance_m=2500.0, avg_hr=155,
              avg_cadence=86),
    ])

    assert cadence_in_work(detail) == 84


def test_cadence_work_is_none_without_splits():
    """Без сплитов каденции в работе нет."""
    assert cadence_in_work(make_detail()) is None


def test_cadence_avg_comes_from_detail():
    """Средняя каденция — из разбора."""
    metrics = workout_metrics(detail=make_detail(avg_cadence=79),
                              session=make_session())

    assert metrics.cadence_avg == 79


# ------------------------------------------------------------------ неделя


def test_week_metrics_sum_zones_and_tss():
    """Метрики недели — сумма по тренировкам."""
    first = workout_metrics(
        detail=make_detail(hr_zone_minutes={"Z2": 30.0, "Z3": 10.0},
                           normalized_power_w=250.0),
        session=make_session(id="a1"), ftp_w=250.0)
    second = workout_metrics(
        detail=make_detail(hr_zone_minutes={"Z2": 20.0, "Z3": 5.0},
                           normalized_power_w=200.0),
        session=make_session(id="a2"), ftp_w=250.0)

    week = week_metrics("W1", [first, second], vo2max_values=[51.0, 50.0])

    assert week.z2_min == 50.0
    assert week.z3_min == 15.0
    assert week.tss == pytest.approx(100.0 + 64.0)
    assert week.vo2max == pytest.approx(50.5)
    assert week.workouts_counted == 2


def test_week_metrics_are_empty_without_details():
    """Неделя без разборов — нули, а не выдумки."""
    week = week_metrics("W1", [])

    assert week.z2_min == 0.0
    assert week.tss == 0.0
    assert week.pace_z2_sec_per_km is None
    assert week.workouts_counted == 0


def test_week_pace_in_z2_is_weighted_by_distance():
    """Темп недели в Z2 — средневзвешенный по расстоянию.

    «65 км лёгких» и «65 км в пороге» — разные недели, и сумма минут
    в Z2 этого различия не показывает. Показывает темп.
    """
    first = workout_metrics(
        detail=make_detail(hr_zone_minutes={"Z2": 30.0},
                           distance_m=10000.0),
        session=make_session(id="a1"))
    first.pace_z2_sec_per_km = 300.0
    second = workout_metrics(
        detail=make_detail(hr_zone_minutes={"Z2": 10.0},
                           distance_m=1000.0),
        session=make_session(id="a2"))
    second.pace_z2_sec_per_km = 240.0

    week = week_metrics("W1", [first, second])

    # (300×10 + 240×1) / 11
    assert week.pace_z2_sec_per_km == pytest.approx((3000.0 + 240.0) / 11.0)


def test_week_metrics_average_efficiency():
    """Эффективность недели — средняя по тренировкам."""
    first = workout_metrics(detail=make_detail(duration_s=2600.0,
                                              distance_m=10000.0),
                           session=make_session(id="a1"),
                           vdot_pace_sec_per_km=240.0)
    second = workout_metrics(detail=make_detail(duration_s=2600.0,
                                               distance_m=10000.0),
                            session=make_session(id="a2"),
                            vdot_pace_sec_per_km=260.0)

    week = week_metrics("W1", [first, second])

    assert first.efficiency == pytest.approx(240.0 / 260.0)
    assert second.efficiency == pytest.approx(260.0 / 260.0)
    assert week.efficiency == pytest.approx(
        (240.0 / 260.0 + 1.0) / 2)


def test_week_metrics_dict_has_all_fields():
    """В ответе API — все метрики, даже пустые."""
    week = week_metrics("W1", [])

    data = week.as_dict()

    for key in ("z2_min", "z3_min", "z4_min", "hi_min", "tss",
                "pace_z2_sec_per_km", "pace_z2", "vo2max", "efficiency",
                "cadence_avg", "cadence_work", "workouts_counted"):
        assert key in data, f"нет метрики {key}"


def test_workout_metrics_dict_has_all_fields():
    """Метрики тренировки — те же поля."""
    metrics = workout_metrics(detail=make_detail(), session=make_session())

    data = metrics.as_dict()

    for key in ("actual_id", "z2_min", "z3_min", "z4_min", "hi_min",
                "pace_z2_sec_per_km", "pace_z2", "tss", "intensity_factor",
                "normalized_power_w", "vo2max", "efficiency",
                "cadence_avg", "cadence_work", "zones"):
        assert key in data, f"нет метрики {key}"


# ------------------------------------------------------------------ инварианты


def test_i46_metrics_need_fit_detail():
    """I46: метрики формы — только из разбора FIT.

    Без разбора метрик нет: пустое значение честнее выдуманного.
    """
    metrics = workout_metrics(detail=None, session=make_session())

    assert metrics.workout_counted is False
    assert metrics.z2_min is None
    assert metrics.pace_z2_sec_per_km is None
    assert metrics.tss is None


def test_i47_tss_needs_ftp():
    """I47: нагрузка — только при заданном FTP."""
    detail = make_detail(normalized_power_w=300.0)

    without = workout_metrics(detail=detail, session=make_session(), ftp_w=None)
    with_ftp = workout_metrics(detail=detail, session=make_session(),
                              ftp_w=411.0)

    assert without.tss is None
    assert with_ftp.tss is not None
    assert with_ftp.tss > 0


def test_i48_pace_in_zone_excludes_rest():
    """I48: темп в зоне — без отдыха."""
    detail = make_detail(
        hr_zone_minutes={"Z2": 20.0},
        series_hr=[(0, 125), (60, 125), (120, 125)],
        series_distance=[(0, 0.0), (60, 5.0), (120, 205.0)],
        series_cadence=[(0, 80), (60, 40), (120, 80)],
    )

    # 60 с стоял (каденция 40) — в счёт не идут. Осталось 200 м за 60 с.
    assert pace_in_zone(detail, "Z2", {"Z2": 20.0}) == pytest.approx(300.0)


def test_ftp_estimate_is_p95_of_power():
    """Оценка FTP — 95-й перцентиль мощности.

    Максимум занижен пиками, среднее занижено тем, что в тренировке
    много лёгкого.
    """
    detail = make_detail(series_power=[(i, 200) for i in range(0, 200)]
                         + [(200 + i, 400) for i in range(0, 20)])

    estimate = estimate_ftp([detail])

    assert estimate == 400.0


def test_ftp_estimate_without_power_is_none():
    """Без мощности порог не оценить."""
    assert estimate_ftp([make_detail()]) is None
