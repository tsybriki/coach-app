"""
Разбор FIT-файла Garmin в детали тренировки.

Источник — `garmin_tools/fit_inspect.py json --include-streams`. Он уже
разбирает FIT и отдаёт: session (агрегаты), laps (отрезки), streams
(секундные записи). Здесь эти данные переводятся в домен и считается то,
что в FIT не хранится: время в зонах пульса атлета, темп на отрезке.

Правила из скилла `personal-data-integrations`:
- каденция: `cadence_stryd` приоритетнее `cadence_watch` — разные датчики;
- высота и скорость в этом FIT отсутствуют (null) — значит и в разборе их нет;
- «движущееся время» считается по разрывам в `t_sec`, а не по elapsed.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.domain.entities import Split, WorkoutDetail
from app.domain.enums import FactSource
from app.ports.storage import ExternalSourceError

GARMIN_TOOLS = Path(
    os.environ.get("GARMIN_TOOLS_PATH", str(Path.home() / "projects" / "garmin_tools"))
)
VENV_PYTHON = GARMIN_TOOLS / ".venv" / "bin" / "python"
INSPECT = GARMIN_TOOLS / "fit_inspect.py"

# Границы зон пульса атлета (bpm) — если профиль не отдан, этот запасной
# набор. Источник правды — профиль атлета, он приходит параметром.
DEFAULT_ZONES: dict[str, tuple[int, int]] = {
    "Z1": (100, 118),
    "Z2": (118, 135),
    "Z3": (135, 150),
    "Z4": (150, 160),
    "Z5": (160, 168),
    "Z6": (168, 172),
    "Z7": (172, 182),
}

# Разрыв в секундах, после которого считаем паузу (не движение).
PAUSE_GAP_S = 3.0

# Шаг ряда для графика: раз в N секунд. Минута — достаточно для чтения
# графика и не раздувает ответ.
SERIES_STEP_S = 15


def parse_fit(
    fit_path: str | Path,
    hr_max: int = 182,
    zones: dict[str, tuple[int, int]] | None = None,
) -> WorkoutDetail:
    """FIT-файл → детали тренировки.

    `zones` — границы зон пульса атлета; без них берётся запасной набор.
    Источник недоступен или файл не разобран → `ExternalSourceError`.
    """
    path = Path(fit_path)
    if not path.exists():
        raise ExternalSourceError("garmin", f"нет FIT-файла: {path}")
    if not VENV_PYTHON.exists() or not INSPECT.exists():
        raise ExternalSourceError("garmin", f"не найден garmin_tools: {GARMIN_TOOLS}")

    result = subprocess.run(
        [str(VENV_PYTHON), str(INSPECT), "json", "--include-streams",
         "--hr-max", str(hr_max), str(path)],
        capture_output=True, text=True, timeout=300, cwd=str(GARMIN_TOOLS),
    )
    if result.returncode != 0:
        raise ExternalSourceError(
            "garmin", f"разбор FIT не удался: {result.stderr[-200:]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ExternalSourceError("garmin", f"FIT не разобран: {error}") from error

    return build_detail(payload, hr_max)


def build_detail(
    payload: dict[str, Any],
    hr_max: int = 182,
    zones: dict[str, tuple[int, int]] | None = None,
) -> WorkoutDetail:
    """Разобранный FIT → доменный объект."""
    session = payload.get("session") or {}
    streams = payload.get("streams") or []

    detail = WorkoutDetail(
        actual_id="",
        source=FactSource.GARMIN,
        duration_s=float(session.get("total_timer_s") or 0.0),
        elapsed_s=float(session.get("total_elapsed_s") or 0.0),
        distance_m=float(session.get("total_distance_m") or 0.0),
        ascent_m=float(session.get("total_ascent") or 0.0),
        descent_m=float(session.get("total_descent") or 0.0),
        avg_hr=_int(session.get("avg_hr")),
        max_hr=_int(session.get("max_hr")),
        avg_cadence=_int(session.get("avg_cadence")),
        max_cadence=_int(session.get("max_cadence")),
        avg_power_w=_int(session.get("avg_power")),
        max_power_w=_int(session.get("max_power")),
        normalized_power_w=_int(session.get("normalized_power")),
        calories=_int(session.get("total_calories")),
    )

    detail.splits = _splits(payload.get("laps") or [])
    detail.hr_zone_minutes = _zone_minutes(streams, zones or DEFAULT_ZONES)

    _series(detail, streams)
    _sources(detail, streams)

    return detail


def _splits(laps: list[dict[str, Any]]) -> list[Split]:
    """Отрезки из лапсов Garmin."""
    result: list[Split] = []
    for index, lap in enumerate(laps, 1):
        duration = float(lap.get("duration_s") or 0.0)
        distance = float(lap.get("distance_m") or 0.0)
        speed = None
        if duration > 0 and distance > 0:
            speed = distance / duration
        result.append(Split(
            index=index,
            duration_s=duration,
            distance_m=distance,
            avg_hr=_int(lap.get("avg_hr")),
            max_hr=_int(lap.get("max_hr")),
            avg_cadence=_int(lap.get("avg_cadence")),
            avg_speed_mps=speed,
            ascent_m=lap.get("ascent_m"),
        ))
    return result


def _zone_minutes(
    streams: list[dict[str, Any]],
    zones: dict[str, tuple[int, int]],
) -> dict[str, float]:
    """Минуты в зонах пульса атлета.

    Считается по секундным записям: каждая запись — одна секунда в зоне.
    Записи с пульсом null в счёт не идут, паузы (разрыв по t_sec) — тоже.
    """
    minutes: dict[str, float] = {}
    previous_t: int | None = None
    for record in streams:
        t_sec = record.get("t_sec")
        hr = record.get("hr")
        if t_sec is None or hr is None:
            previous_t = t_sec if isinstance(t_sec, int) else previous_t
            continue
        # пауза: после разрыва секунды не идут подряд — запись не движение
        if previous_t is not None and t_sec - previous_t > PAUSE_GAP_S:
            previous_t = t_sec
            continue
        previous_t = t_sec

        zone = _zone_of(int(hr), zones)
        if zone:
            minutes[zone] = minutes.get(zone, 0.0) + 1 / 60

    # без округления: короткие интервалы в зоне иначе обнуляются
    return dict(sorted(minutes.items()))


def _zone_of(hr: int, zones: dict[str, tuple[int, int]]) -> str | None:
    """Зона пульса атлета по значению. Границы — из профиля атлета."""
    for zone, (low, high) in sorted(
        zones.items(), key=lambda item: item[1][0]
    ):
        if low <= hr < high:
            return zone
    last = sorted(zones.items(), key=lambda item: item[1][0])
    if last and hr >= last[-1][1][0]:
        return last[-1][0]
    return None


def _series(detail: WorkoutDetail, streams: list[dict[str, Any]]) -> None:
    """Ряды для графика: пульс, каденция, мощность, дистанция."""
    previous_t: int | None = None
    for record in streams:
        t_sec = record.get("t_sec")
        if not isinstance(t_sec, int):
            continue
        # пауза: прыжок по времени — не движение, точку не рисуем
        if previous_t is not None and t_sec - previous_t > PAUSE_GAP_S:
            previous_t = t_sec
            continue
        previous_t = t_sec

        if t_sec % SERIES_STEP_S != 0:
            continue

        hr = record.get("hr")
        if hr is not None:
            detail.series_hr.append((t_sec, int(hr)))

        cadence = record.get("cadence_stryd") or record.get("cadence_watch")
        if cadence is not None:
            detail.series_cadence.append((t_sec, int(cadence)))

        power = record.get("stryd_power_w")
        if power is None:
            power = record.get("power")
        if power is not None:
            detail.series_power.append((t_sec, int(power)))

        distance = record.get("dist_m")
        if distance is not None:
            detail.series_distance.append((t_sec, float(distance)))


def _sources(detail: WorkoutDetail, streams: list[dict[str, Any]]) -> None:
    """Каким датчиком взяты каденция и мощность.

    `cadence_stryd` — нагрудный ремень (Stryd), `cadence_watch` — акселерометр
    часов. Это разные датчики, смешивать их нельзя.
    """
    has_stryd_cadence = any(r.get("cadence_stryd") is not None for r in streams)
    has_watch_cadence = any(r.get("cadence_watch") is not None for r in streams)
    if has_stryd_cadence:
        detail.cadence_source = "stryd"
    elif has_watch_cadence:
        detail.cadence_source = "watch"

    has_stryd_power = any(r.get("stryd_power_w") is not None for r in streams)
    has_garmin_power = any(r.get("power") is not None for r in streams)
    if has_stryd_power:
        detail.power_source = "stryd"
    elif has_garmin_power:
        detail.power_source = "garmin"


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["parse_fit", "build_detail", "DEFAULT_ZONES", "SERIES_STEP_S"]
