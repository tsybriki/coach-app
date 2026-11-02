"""Адаптер правил методологии: разобранные данные Дэниэлса → доменные правила.

Адаптер знает формат файлов справочника. Домен и сервисы знают только
`app.domain.methodology` — язык правил, а не формат хранения.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.methodology import (
    DanielsPaces,
    MethodPlan,
    PaceRow,
    PhaseShape,
    PhaseWeek,
    RecipeSegment,
    RecipeSet,
    WeekSchedule,
    WorkoutRecipe,
    ZoneCap,
)

# Зоны таблицы темпов → зоны правил. Ключ — колонка исходного разбора.
PACE_ZONE_KEYS = {
    "easy": "E",
    "marathon": "M",
    "threshold": "T",
    "interval": "I",
    "repetition": "R",
}


class ReferenceNotFoundError(Exception):
    """Справочник не найден. Не доменная ошибка: данных методики нет."""


def load_paces(reference_dir: Path) -> DanielsPaces:
    """Таблица темпов Дэниэлса: VDOT → темпы зон.

    В исходной таблице у каждой зоны несколько колонок (400 м, 1000 м,
    миля). Канон — секунды на километр: он один на зону, и колонки обязаны
    его давать. Берется колонка километра — она есть у каждой зоны.
    """
    path = reference_dir / "daniels_paces.json"
    if not path.exists():
        raise ReferenceNotFoundError(f"нет справочника темпов: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[PaceRow] = []
    for entry in data.get("training_paces", []):
        paces: dict[str, float] = {}
        for source_key, zone in PACE_ZONE_KEYS.items():
            block = entry.get(source_key) or {}
            value = block.get("pace_per_km")
            if value is None and source_key in ("easy", "marathon"):
                value = block.get("km")
            if value is not None:
                paces[zone] = float(value)
        if paces:
            rows.append(PaceRow(vdot=int(entry["vdot"]), paces_sec_per_km=paces))
    return DanielsPaces(rows=tuple(rows))


def _segment_from_dict(data: dict[str, Any]) -> RecipeSegment:
    """Кусок работы из разобранных данных."""
    alternatives = tuple(
        _segment_from_dict(item) for item in data.get("alternatives", [])
    )
    return RecipeSegment(
        zone=data.get("zone", ""),
        distance_m=data.get("distance_m"),
        minutes=data.get("minutes"),
        seconds=data.get("seconds"),
        alternatives=alternatives,
    )


def _recipe_from_dict(data: dict[str, Any]) -> WorkoutRecipe:
    """Рецепт тренировки из разобранных данных."""
    sets = tuple(
        RecipeSet(
            reps_min=int(s["reps_min"]),
            reps_max=int(s["reps_max"]),
            segments=tuple(_segment_from_dict(seg) for seg in s["segments"]),
            label=s.get("label", ""),
        )
        for s in data.get("sets", [])
    )
    flat = tuple(_segment_from_dict(seg) for seg in data.get("flat", []))
    return WorkoutRecipe(
        kind=data.get("kind", ""),
        label=data.get("label", ""),
        sets=sets,
        flat=flat,
        note=data.get("note", ""),
        distance_m=float(data.get("distance_m", 0.0)),
        pace_growth_sec_per_400m=float(data.get("pace_growth_sec_per_400m", 0.0)),
        final_zone=data.get("final_zone", ""),
    )


def load_plan(reference_dir: Path) -> MethodPlan:
    """Программа тренировок из разобранной Табл. 19.1."""
    path = reference_dir / "training_plan_19_1.json"
    if not path.exists():
        raise ReferenceNotFoundError(f"нет программы тренировок: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    weeks: list[PhaseWeek] = []
    for phase_entries in data.get("phases", {}).values():
        for entry in phase_entries:
            recipes = tuple(_recipe_from_dict(r) for r in entry.get("sessions", []))
            caps = tuple(
                ZoneCap(
                    zone=c["zone"],
                    fraction_of_week=float(c["fraction_of_week"]),
                    ceiling_km=c.get("ceiling_km"),
                )
                for c in entry.get("caps", [])
            )
            weeks.append(PhaseWeek(
                phase=int(entry["phase"]),
                week=int(entry["week"]),
                recipes=recipes,
                caps=caps,
            ))

    schedules = tuple(
        WeekSchedule(
            weeks=int(s["weeks"]),
            phases={
                int(k): tuple(int(w) for w in v)
                for k, v in s.get("phases", {}).items()
            },
        )
        for s in data.get("schedules", [])
    )
    base = data.get("base_schedule")
    base_schedule = None
    if base:
        base_schedule = WeekSchedule(
            weeks=int(base["weeks"]),
            phases={
                int(k): tuple(int(w) for w in v)
                for k, v in base.get("phases", {}).items()
            },
        )

    return MethodPlan(
        weeks=tuple(sorted(weeks, key=lambda w: (w.phase, w.week))),
        schedules=schedules,
        base_schedule=base_schedule,
        extra_phases=tuple(
            int(p) for p in data.get("extra_phases", []) if p
        ),
        extra_plans={
            int(k): tuple(int(w) for w in v)
            for k, v in (data.get("extra_plans") or {}).items()
        },
        front_phases=tuple(
            int(p) for p in data.get("front_phases", []) if p
        ),
        program_weeks={
            int(k): tuple(int(w) for w in v)
            for k, v in (data.get("program_weeks") or {}).items()
        },
        phase_shapes={
            int(k): _shape_from_dict(v)
            for k, v in (data.get("phase_shapes") or {}).items()
        },
    )


def _shape_from_dict(data: dict[str, Any]) -> PhaseShape:
    """Форма фазы — из разобранных данных справочника."""
    reps = data.get("stride_reps") or {}
    if isinstance(reps, dict):
        reps_min = int(reps.get("min", 0))
        reps_max = int(reps.get("max", reps_min))
    else:
        reps_min = reps_max = int(reps or 0)
    return PhaseShape(
        phase=int(data.get("phase", 0)),
        runs_per_week=int(data.get("runs", 0) or 0),
        easy_zone=str(data.get("easy_zone", "E")),
        long_from_week=int(data.get("long_from_week", 1) or 1),
        stride_runs=int(data.get("stride_runs", 0) or 0),
        stride_reps_min=reps_min,
        stride_reps_max=reps_max,
        stride_distance_m=int(data.get("stride_distance_m", 100) or 100),
        stride_recovery_m=int(data.get("stride_recovery_m", 100) or 100),
        stride_zone=str(data.get("stride_zone", "R")),
        stride_from_week=int(data.get("stride_from_week", 1) or 1),
        ofp_runs=int(data.get("ofp_runs", 0) or 0),
        ofp_minutes=int(data.get("ofp_minutes", 0) or 0),
        weekly_km_min=float(data.get("km_min", 0.0) or 0.0),
        weekly_km_max=float(data.get("km_max", 0.0) or 0.0),
    )


__all__ = ["ReferenceNotFoundError", "load_paces", "load_plan"]
