"""Разбор FIT: агрегаты, отрезки, зоны пульса, ряды для графика."""

from __future__ import annotations

from typing import Any

from app.adapters.fit import _zone_of, build_detail


def _payload(
    session: dict[str, Any] | None = None,
    laps: list[dict[str, Any]] | None = None,
    streams: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "session": session or {},
        "laps": laps or [],
        "streams": streams or [],
    }


def test_aggregates_from_session() -> None:
    detail = build_detail(_payload(session={
        "total_timer_s": 1800.0,
        "total_elapsed_s": 2000.0,
        "total_distance_m": 5000.0,
        "total_ascent": 42.0,
        "total_descent": 40.0,
        "avg_hr": 142,
        "max_hr": 168,
        "avg_cadence": 82,
        "max_cadence": 95,
        "total_calories": 640,
    }))
    assert detail.duration_s == 1800.0
    assert detail.elapsed_s == 2000.0
    assert detail.distance_m == 5000.0
    assert detail.ascent_m == 42.0
    assert detail.avg_hr == 142
    assert detail.max_hr == 168
    assert detail.avg_cadence == 82
    assert detail.calories == 640


def test_splits_from_laps() -> None:
    detail = build_detail(_payload(laps=[
        {"duration_s": 600.0, "distance_m": 2000.0, "avg_hr": 140, "max_hr": 150,
         "avg_cadence": 84},
        {"duration_s": 300.0, "distance_m": 500.0, "avg_hr": 150, "max_hr": 160,
         "avg_cadence": 80},
    ]))
    assert len(detail.splits) == 2
    first = detail.splits[0]
    assert first.index == 1
    assert first.distance_m == 2000.0
    assert first.avg_hr == 140
    # скорость: 2000 м за 600 с
    assert first.avg_speed_mps == 2000.0 / 600.0


def test_zone_minutes_count_seconds() -> None:
    zones = {"Z1": (100, 118), "Z2": (118, 135)}
    streams = [
        {"t_sec": 0, "hr": 110},
        {"t_sec": 1, "hr": 120},
        {"t_sec": 2, "hr": 125},
    ]
    detail = build_detail(_payload(streams=streams), zones=zones)
    assert detail.hr_zone_minutes["Z1"] == 1 / 60
    assert detail.hr_zone_minutes["Z2"] == 2 / 60


def test_zone_minutes_skip_pauses() -> None:
    """Разрыв по времени — пауза, в минуты не идёт."""
    zones = {"Z2": (118, 135)}
    streams = [
        {"t_sec": 0, "hr": 120},
        {"t_sec": 120, "hr": 125},   # пауза — разрыв больше секунды
    ]
    detail = build_detail(_payload(streams=streams), zones=zones)
    assert detail.hr_zone_minutes.get("Z2", 0.0) == 1 / 60


def test_zone_minutes_skip_records_without_hr() -> None:
    zones = {"Z2": (118, 135)}
    streams = [
        {"t_sec": 0, "hr": None},
        {"t_sec": 1, "hr": 120},
    ]
    detail = build_detail(_payload(streams=streams), zones=zones)
    assert detail.hr_zone_minutes["Z2"] == 1 / 60


def test_zone_of_boundaries() -> None:
    zones = {"Z1": (100, 118), "Z2": (118, 135), "Z3": (135, 150)}
    assert _zone_of(100, zones) == "Z1"
    assert _zone_of(117, zones) == "Z1"
    assert _zone_of(118, zones) == "Z2"
    assert _zone_of(135, zones) == "Z3"
    # ниже нижней границы — зоны нет
    assert _zone_of(99, zones) is None
    # выше верхней — последняя зона
    assert _zone_of(200, zones) == "Z3"


def test_series_thinned_to_step() -> None:
    streams = [
        {"t_sec": second, "hr": 140, "cadence": 80, "distance_m": second * 3.0}
        for second in range(0, 60)
    ]
    detail = build_detail(_payload(streams=streams))
    # шаг 15 секунд → 0, 15, 30, 45
    assert len(detail.series_hr) == 4
    assert detail.series_hr[0][0] == 0
    assert detail.series_hr[1][0] == 15


def test_series_empty_without_streams() -> None:
    detail = build_detail(_payload())
    assert detail.series_hr == []
    assert detail.series_cadence == []
    assert detail.hr_zone_minutes == {}


def test_cadence_source_detected() -> None:
    """Нагрудный ремень важнее часов — они разные датчики."""
    streams = [
        {"t_sec": 0, "hr": 140, "cadence": 80,
         "cadence_stryd": 81, "cadence_watch": 70},
    ]
    detail = build_detail(_payload(streams=streams))
    assert detail.cadence_source == "stryd"


def test_cadence_source_watch_without_stryd() -> None:
    streams = [{"t_sec": 0, "hr": 140, "cadence": 80, "cadence_watch": 70}]
    detail = build_detail(_payload(streams=streams))
    assert detail.cadence_source == "watch"
