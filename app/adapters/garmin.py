"""
Адаптер Garmin: единственный источник активностей.

Garmin Connect отдаёт typeKey вида спорта: running, cycling, indoor_cycling,
lap_swimming, hiit, strength_training. Имя тренировки при этом может быть
любым — Кирилл записывает ОФП как «High Intensity Interval Training».

Активность без расстояния (HIIT, силовая) — это нормальная тренировка,
а не ошибка: distance может отсутствовать.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.domain.entities import ActualSession
from app.domain.enums import FactSource, Sport
from app.ports.storage import ExternalSourceError

GARMIN_TOOLS = Path(
    os.environ.get("GARMIN_TOOLS_PATH", str(Path.home() / "projects" / "garmin_tools"))
)
VENV_PYTHON = GARMIN_TOOLS / ".venv" / "bin" / "python"
PULL_SCRIPT = GARMIN_TOOLS / "latest_pull.py"

# Виды спорта, которые тянем. hiit и strength_training нужны отдельно:
# Garmin отдаёт их отдельными typeKey, а в названии может стоять что угодно.
SPORTS = ("running", "cycling", "swimming", "hiit", "strength_training")

# typeKey Garmin → вид спорта в домене.
SPORT_BY_TYPE = {
    "running": Sport.RUN,
    "cycling": Sport.BIKE,
    "indoor_cycling": Sport.BIKE,
    "road_biking": Sport.BIKE,
    "mountain_biking": Sport.BIKE,
    "gravel_cycling": Sport.BIKE,
    "virtual_ride": Sport.BIKE,
    "lap_swimming": Sport.SWIM,
    "pool_swimming": Sport.SWIM,
    "open_water_swimming": Sport.SWIM,
    "swimming": Sport.SWIM,
    "hiit": Sport.HIIT,
    "strength_training": Sport.STRENGTH,
}


class GarminActivityPort:
    """Факт из Garmin Connect.

    Тянет через garmin_tools: тот умеет логиниться и разбирать FIT. Здесь
    только перевод ответа Garmin в домен.
    """

    def pull(
        self, start: date, end: date, sport: str | None = None
    ) -> list[ActualSession]:
        """Активности за период.

        Источник недоступен → `ExternalSourceError`, а не пустой список:
        пустой список означал бы «тренировок не было».
        """
        if not VENV_PYTHON.exists() or not PULL_SCRIPT.exists():
            raise ExternalSourceError(
                "garmin", f"не найден garmin_tools: {GARMIN_TOOLS}")

        wanted = [sport] if sport else list(SPORTS)
        out_dir = Path(os.environ.get("COACH_APP_GARMIN_TMP", "/tmp/coach_app_garmin"))

        activities: list[dict[str, Any]] = []
        for one in wanted:
            result = subprocess.run(
                [str(VENV_PYTHON), str(PULL_SCRIPT),
                 "--sport", one, "--count", "60", "--out", str(out_dir / one)],
                capture_output=True, text=True, timeout=240,
                cwd=str(GARMIN_TOOLS),
            )
            if result.returncode != 0:
                raise ExternalSourceError(
                    "garmin", f"выкачка {one} не удалась: {result.stderr[-200:]}")
            part = out_dir / one / "index.json"
            if part.exists():
                activities.extend(json.loads(part.read_text(encoding="utf-8")))

        sessions = [s for s in (self._to_session(a) for a in activities)
                    if s is not None and start <= s.date <= end]
        return sessions

    def _to_session(self, activity: dict[str, Any]) -> ActualSession | None:
        """Активность Garmin → факт в домене."""
        raw_date = activity.get("date")
        if not raw_date:
            return None
        try:
            day = datetime.fromisoformat(raw_date).date()
        except ValueError:
            return None

        sport = SPORT_BY_TYPE.get(activity.get("sport_type", ""))
        if sport is None:
            return None

        activity_id = activity.get("activity_id")
        duration_s = activity.get("duration_s") or 0
        return ActualSession(
            id=f"g-{activity_id}",
            date=day,
            sport=sport,
            duration_min=int(round(duration_s / 60)),
            distance_m=float((activity.get("distance_km") or 0) * 1000),
            hr_avg=int(activity["avg_hr"]) if activity.get("avg_hr") else None,
            hr_max=int(activity["max_hr"]) if activity.get("max_hr") else None,
            aerobic_te=activity.get("aerobic_te"),
            anaerobic_te=activity.get("anaerobic_te"),
            vo2max=activity.get("vo2max"),
            source=FactSource.GARMIN,
            external_id=str(activity_id),
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )


__all__ = ["GarminActivityPort", "SPORT_BY_TYPE"]
