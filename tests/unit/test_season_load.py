"""Нагрузка сезона: суммарный TSS и динамика по неделям.

Кирилл (22.11.2026): «Нужно куда то добавить суммарный tss недели,
который, я надеюсь, не теряется при закрытии недели. Например, добавить
какую то аналитику на вкладку сезон. Сейчас там только план на сезон».

Ответ на «не теряется ли»: **не теряется**. Нагрузка пишется в саммари
недели при закрытии (`WeekSummary.metrics.tss`), а разборы FIT лежат в
хранилище — значит, TSS можно пересчитать в любой момент. Проверено на
живых данных: W5 → 394.9, W6 → 414.2.

Здесь — доменная агрегация: TSS по сезону, средняя в неделю, средняя за
последние недели, динамика по неделям и форма (VO₂max).

Вход — метрики тренировок по неделям: результат `week_metrics`, то есть
те же словари, что отдаются в API. Клиент и сервер одинаково понимают
эти данные.

Имена тестов = номера инвариантов из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

import pytest

from app.domain.derivations import season_load_summary


def workout(tss: float | None = None, vo2max: float | None = None,
            actual_id: str = "a1", date: str = "2026-11-15"
            ) -> dict[str, object]:
    """Метрики тренировки — как их отдаёт домен."""
    return {
        "actual_id": actual_id,
        "tss": tss,
        "vo2max": vo2max,
        "distance_m": 0.0,
        "date": date,
    }


# ------------------------------------------------------------------ I50


def test_i50_season_load_sums_tss_of_all_weeks():
    """I50: нагрузка сезона — сумма нагрузки по неделям."""
    weeks = {
        3: [workout(100.0, actual_id="a1"), workout(50.0, actual_id="a2")],
        4: [workout(120.0, actual_id="a3")],
    }

    summary = season_load_summary(weeks)

    assert summary["tss_total"] == 270.0
    assert summary["weeks_counted"] == 2


def test_i50_season_load_averages_per_week():
    """I50: средняя нагрузка в неделю — по неделям с нагрузкой.

    Не по всем неделям сезона: план на 49 недель, а факт — за месяц.
    Делить на все недели — значит показать несуществующую цифру.
    """
    weeks = {
        3: [workout(100.0)],
        4: [workout(120.0)],
    }

    summary = season_load_summary(weeks)

    assert summary["tss_avg_week"] == 110.0


def test_i50_season_load_without_fact_is_empty():
    """I50: без факта нагрузки нет — это «не задано», а не ноль.

    Ноль на экране читается как «посчитали — ноль».
    """
    summary = season_load_summary({})

    assert summary["tss_total"] == 0.0
    assert summary["weeks_counted"] == 0
    assert summary["tss_avg_week"] is None
    assert summary["tss_avg_recent"] is None


def test_i50_season_load_ignores_workout_without_tss():
    """Тренировка без нагрузки в неделю не делает неделю «нулевой».

    Нет FTP или нет мощности — нагрузки не из чего считать. Такая
    тренировка не должна обнулять неделю.
    """
    weeks = {
        3: [workout(100.0, actual_id="a1"), workout(None, actual_id="a2")],
    }

    summary = season_load_summary(weeks)

    assert summary["weeks_counted"] == 1
    assert summary["tss_total"] == 100.0
    assert summary["tss_avg_week"] == 100.0


def test_i50_season_load_ignores_week_without_tss():
    """Неделя без нагрузки в средней не участвует.

    Там нагрузки нет — не «ноль», а её не из чего считать.
    """
    weeks = {
        3: [workout(100.0)],
        4: [],   # факт есть, разбора нет
    }

    summary = season_load_summary(weeks)

    assert summary["weeks_counted"] == 1
    assert summary["tss_avg_week"] == 100.0


def test_i50_season_load_reports_form():
    """I50: форма сезона — последний известный VO₂max.

    VO₂max приезжает с каждой тренировки от Garmin; форма — это он.
    Берётся последний по дате, а не первый попавшийся.
    """
    weeks = {
        3: [workout(100.0, vo2max=50.0, actual_id="a1",
                    date="2026-11-08")],
        4: [workout(120.0, vo2max=52.0, actual_id="a2",
                    date="2026-11-14"),
             workout(80.0, vo2max=51.0, actual_id="a3",
                     date="2026-11-16")],
    }

    summary = season_load_summary(weeks)

    # Последнее измерение по дате — 51.0, а не первое попавшееся.
    assert summary["vo2max"] == 51.0


def test_i50_season_load_has_weekly_series():
    """I50: динамика по неделям — для графика.

    Каждая неделя с нагрузкой: её номер и TSS. Недели без нагрузки в
    ряд не попадают: график должен показывать нагрузку, а не пустоты.
    """
    weeks = {
        3: [workout(100.0)],
        4: [workout(120.0)],
        7: [workout(90.0)],
    }

    summary = season_load_summary(weeks)

    series = summary["weekly"]
    assert [row["season_week"] for row in series] == [3, 4, 7]
    assert [row["tss"] for row in series] == [100.0, 120.0, 90.0]


def test_i50_season_load_weekly_series_sorted_by_week():
    """Динамика — по порядку недель, а не по порядку обработки."""
    weeks = {
        7: [workout(90.0)],
        3: [workout(100.0)],
        4: [workout(120.0)],
    }

    summary = season_load_summary(weeks)

    assert [row["season_week"] for row in summary["weekly"]] == [3, 4, 7]


def test_i50_season_load_recent_average():
    """I50: средняя за последние 4 недели с нагрузкой.

    Это то, что показывает, набирает ли форма: среднее за месяц, а не
    за весь сезон.
    """
    weeks = {n: [workout(float(n * 10))] for n in range(1, 8)}

    summary = season_load_summary(weeks)

    # Последние четыре недели с нагрузкой: 4, 5, 6, 7 → 40, 50, 60, 70.
    assert summary["tss_avg_recent"] == 55.0
    assert summary["recent_weeks"] == 4


def test_i50_season_load_recent_average_with_fewer_weeks():
    """Недель меньше четырёх — средняя по тем, что есть.

    Иначе деление на четыре дало бы несуществующую цифру.
    """
    weeks = {3: [workout(100.0)], 4: [workout(120.0)]}

    summary = season_load_summary(weeks)

    assert summary["tss_avg_recent"] == 110.0
    assert summary["recent_weeks"] == 2


def test_i50_season_load_reports_total_distance():
    """I50: объём сезона в километрах — рядом с нагрузкой.

    Нагрузка без объёма не читается: 400 TSS — это 40 км лёгкого или
    200 км с интервалами.
    """
    weeks = {
        3: [{"actual_id": "a1", "tss": 100.0, "vo2max": None,
              "distance_m": 14000.0}],
        4: [{"actual_id": "a2", "tss": 120.0, "vo2max": None,
              "distance_m": 11000.0}],
    }

    summary = season_load_summary(weeks)

    assert summary["distance_km"] == 25.0


# ------------------------------------------- незакрытая неделя


def test_i51_season_load_marks_unfinished_week():
    """I51: незакрытая неделя помечена — нагрузка в ней ещё не полная.

    Неделя в процессе: 96 TSS из ~400. Рядом с закрытыми неделями
    это читается как «нагрузка рухнула», хотя ничего не рухнуло.
    """
    weeks = {
        6: [workout(400.0)],
        7: [workout(96.0)],
    }

    summary = season_load_summary(weeks, closed_weeks={6})

    by_week = {row["season_week"]: row for row in summary["weekly"]}
    assert by_week[6]["complete"] is True
    assert by_week[7]["complete"] is False


def test_i51_season_load_average_ignores_unfinished_week():
    """I51: средняя — по закрытым неделям.

    Незакрытая неделя занижала бы среднюю: в ней 96 TSS из ~400, и
    деление на неё дало бы цифру, которой никогда не было.
    """
    weeks = {
        5: [workout(400.0)],
        6: [workout(400.0)],
        7: [workout(96.0)],
    }

    summary = season_load_summary(weeks, closed_weeks={5, 6})

    assert summary["tss_avg_week"] == 400.0
    assert summary["weeks_closed"] == 2


def test_i51_season_load_total_includes_unfinished_week():
    """I51: сумма включает всё сделанное, включая текущую неделю.

    Сделано — значит сделано. Незакрытая неделя не обнуляет сумму,
    накопленное за сезон.
    """
    weeks = {
        6: [workout(400.0)],
        7: [workout(96.0)],
    }

    summary = season_load_summary(weeks, closed_weeks={6})

    assert summary["tss_total"] == 496.0


def test_i51_season_load_recent_average_uses_closed_weeks():
    """I51: средняя за последние недели — по закрытым.

    Та же причина: неделя в процессе тянула бы среднее вниз.
    """
    weeks = {
        4: [workout(300.0)],
        5: [workout(400.0)],
        6: [workout(400.0)],
        7: [workout(96.0)],
    }

    summary = season_load_summary(weeks, closed_weeks={4, 5, 6})

    # Закрытых недель три: 300, 400, 400. W7 (96) в среднюю не входит.
    assert summary["tss_avg_recent"] == pytest.approx(366.67, abs=0.01)
    assert summary["recent_weeks"] == 3


def test_i51_season_load_without_closed_weeks_uses_all():
    """Без списка закрытых недель считаем все — как раньше.

    Статус недели может быть неизвестен; тогда не выдумываем.
    """
    weeks = {3: [workout(100.0)], 4: [workout(120.0)]}

    summary = season_load_summary(weeks)

    assert summary["tss_avg_week"] == 110.0
    assert summary["weeks_closed"] == 2
