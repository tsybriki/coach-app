#!/usr/bin/env python3
"""
import_pipeline.py — импорт данных из пайплайна `~/coach` в хранилище приложения.

Одноразовая операция: пайплайн — источник правды для планов и факта,
приложение — место, где ими пользуются. Импорт ничего не вычисляет: берёт
готовые планы и факты как есть.

Что импортируется:
  - сезон: цель, горизонт, дефолтные окна (constraints → слоты);
  - профиль атлета;
  - правила методологии: шаблоны тренировок, коэффициенты адаптации;
  - план текущей недели: запросы, размещения, тренировки с шагами;
  - факт из Garmin: активности за сезон.

Запуск:
    python3 tools/import_pipeline.py
    python3 tools/import_pipeline.py --week 3 --root ~/.local/share/coach-app
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.storage.files import FileStorage  # noqa: E402
from app.domain.entities import (  # noqa: E402
    ActualSession,
    Assignment,
    Athlete,
    Goal,
    LoadModel,
    Plan,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (  # noqa: E402
    FactSource,
    FocusType,
    PlanStatus,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)

PIPELINE = Path(os.path.expanduser("~/coach"))
STATE = PIPELINE / "state"

# Дни недели тренировки: неделя начинается с воскресенья (вс→сб).
DAY_ORDER = ["ВС", "ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ"]

SPORT_BY_PIPELINE = {
    "running": Sport.RUN,
    "cycling": Sport.BIKE,
    "road_biking": Sport.BIKE,
    "mountain_biking": Sport.BIKE,
    "indoor_cycling": Sport.BIKE,
    "virtual_ride": Sport.BIKE,
    "swimming": Sport.SWIM,
    "lap_swimming": Sport.SWIM,
    "pool_swimming": Sport.SWIM,
    "open_water_swimming": Sport.SWIM,
}

# Куда попадает вид спорта из плана пайплайна.
SPORT_BY_PLAN_KIND = {
    "run": Sport.RUN,
    "bike": Sport.BIKE,
    "swim": Sport.SWIM,
    "strength": Sport.STRENGTH,
    "ofp": Sport.OFP,
    "mobility": Sport.MOBILITY,
}

# Локации из пайплайна — на английском. Приложение на русском.
LOCATION_RU = {
    "asphalt_commuter": "асфальт · дорога",
    "stadium": "стадион",
    "stadium_or_pool": "стадион или бассейн",
    "home_stationary_bike": "дома · велотренажёр",
    "pool_or_asphalt": "бассейн или асфальт",
    "home": "дома",
    "long_ride_or_station": "длинная поездка или станция",
}

# Что взять на тренировку — из места и вида спорта. Логика пайплайна
# (render_html._inventory_for), чтобы приложение показывало то же.
def inventory_for(slot: dict[str, Any]) -> list[dict[str, str]]:
    """Список того, что нужно взять с собой."""
    items: list[dict[str, str]] = []
    kind = slot.get("kind", "")
    location = slot.get("location", "")
    subkind = slot.get("subkind", "")

    if "home_stationary_bike" in location:
        items.append({"icon": "🚴", "name": "Велостанок (Tacx)"})
    elif location == "stadium":
        items.append({"icon": "🏟", "name": "Стадион (400м)"})
    elif location == "stadium_or_pool":
        items.append({"icon": "🏟", "name": "Стадион 400м (или бассейн)"})
    elif location == "pool_or_asphalt":
        if kind == "swim":
            items.append({"icon": "🏊", "name": "Бассейн"})
        else:
            items.append({"icon": "🛣", "name": "Асфальт (коммутер)"})
    elif "long_ride" in location:
        items.append({"icon": "🚴", "name": "Вело (улица или станок)"})

    if kind == "ofp":
        items.append({"icon": "🧘", "name": "Коврик"})
        items.append({"icon": "🎗", "name": "Резинка (опционально)"})

    if subkind in ("key_intervals", "intervals", "race_pace", "tempo", "quality"):
        items.append({"icon": "⌚", "name": "Garmin / часы с HR"})

    return items


# Вид тренировки на русский — из подвида плана пайплайна.
SUBKIND_RU = {
    "easy": "лёгкая",
    "easy_progression": "лёгкая с прогрессией",
    "progression": "прогрессия",
    "quality": "качественная",
    "key_run": "ключевая",
    "long_Z2": "длинная Z2",
    "long_run": "длинная",
    "stationary_z2": "велотренажёр Z2",
    "stationary": "велотренажёр",
    "core": "кор",
    "mobility": "мобильность",
    "strength": "силовая",
    "brick": "брикет",
}

def _subkind_ru(slot: dict[str, Any]) -> str:
    """Вид тренировки по-русски. Пусто, если дублирует название.

    «Вел-станок Z1–Z2 45мин» и тег «велотренажёр Z2» говорят одно и то же —
    лишний тег в шапке только шумит.
    """
    name = str(slot.get("name", "")).lower()
    subkind = SUBKIND_RU.get(slot.get("subkind", ""), slot.get("subkind", ""))
    if not subkind:
        return ""
    if subkind.lower() in name:
        return ""
    return subkind


PHASE_ROLES = {
    "warmup": StepRole.WARMUP,
    "work": StepRole.WORK,
    "main": StepRole.WORK,
    "cooldown": StepRole.COOLDOWN,
    "recovery": StepRole.REST,
    "rest": StepRole.REST,
}


# ------------------------------------------------------------------ даты


def season_start_of(season_plan: dict[str, Any]) -> date:
    """Начало сезона — из плана сезона пайплайна."""
    return date.fromisoformat(season_plan.get("season_start_date", "2026-10-11"))


def season_week_range(start: date, season_week: int) -> tuple[date, date]:
    """W1 = [start, start+6], W2 = [start+7, start+13]."""
    week_start = start + timedelta(days=7 * (season_week - 1))
    return week_start, week_start + timedelta(days=6)


def week_of_date(start: date, day: date) -> int:
    """Номер недели сезона по дате. До старта — 0."""
    if day < start:
        return 0
    return ((day - start).days // 7) + 1


# ------------------------------------------------------------------ чтение пайплайна


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def primary_goal(season_plan: dict[str, Any]) -> dict[str, Any]:
    goals = season_plan.get("goals") or []
    for goal in goals:
        if goal.get("primary"):
            return goal
    return goals[0] if goals else {}


def macro_week(season_plan: dict[str, Any], season_week: int) -> dict[str, Any]:
    for entry in season_plan.get("weekly_macro") or []:
        if entry.get("season_week") == season_week:
            return entry
    return {}


# ------------------------------------------------------------------ сборка сущностей


def build_season(season_plan: dict[str, Any],
                 constraints: dict[str, Any]) -> Season:
    """Сезон: горизонт, цель, дефолтные окна тренировок."""
    horizon = season_plan.get("horizon") or {}
    start = season_start_of(season_plan)
    end = date.fromisoformat(horizon.get("end", "2027-09-12"))
    count = int(horizon.get("season_week_count", 49))

    goal_data = primary_goal(season_plan)
    metric = goal_data.get("goal_metric") or {}
    race = next(
        (r for r in season_plan.get("races") or []
         if r.get("goal_id") == goal_data.get("id")),
        {},
    )
    goal = Goal(
        id=goal_data.get("id", "g1"),
        discipline=goal_data.get("discipline", "run_10k"),
        race_date=date.fromisoformat(race.get("date") or goal_data["race_date"]),
        metric_type=metric.get("type", "time_sec"),
        metric_target=float(metric.get("target", 0)),
        target_friendly=metric.get("target_friendly", ""),
        venue=race.get("name") or goal_data.get("venue"),
        start_time=race.get("start_time"),
        race_pace_min_per_km=_pace_seconds(goal_data.get("race_pace_min_per_km")),
        realistic_fork=goal_data.get("realistic_fork") or {},
    )

    plan = Plan(
        id=goal.id,
        status=PlanStatus.ACTIVE,
        goal=goal,
        period_start=start,
        period_end=end,
        load_budget={"hours_range": [0.0, 20.0]},
        phase_ids=[p["id"] for p in season_plan.get("phases") or []],
    )

    return Season(
        id=horizon.get("season_id", "S1"),
        horizon_start=start,
        horizon_end=end,
        season_week_count=count,
        slots=build_slots(constraints),
        plans=[plan],
    )


def _pace_seconds(value: Any) -> float | None:
    """'4:00' → 240 секунд на километр."""
    if not value or not isinstance(value, str) or ":" not in value:
        return None
    minutes, seconds = value.split(":", 1)
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def build_slots(constraints: dict[str, Any]) -> list[Slot]:
    """Дефолтные окна тренировок — из ограничений пайплайна.

    Оборудование не проставляется: у окон пайплайна нет идентификаторов
    оборудования, а подставлять свои — значит выдумать данные.
    """
    slots: list[Slot] = []
    windows = constraints.get("weekly_windows") or {}
    for day, entries in windows.items():
        if day not in DAY_ORDER:
            continue
        for index, window in enumerate(entries, 1):
            slots.append(Slot(
                id=f"win-{day}-{index}",
                day=DAY_ORDER.index(day),
                start=window.get("start", "00:00"),
                end=window.get("end", "23:59"),
                capacity_min=int(window.get("duration_min", 60)),
                note=window.get("location"),
            ))
    return slots


def build_athlete(athlete_data: dict[str, Any]) -> Athlete:
    """Профиль атлета — из athlete.json пайплайна."""
    zones = athlete_data.get("hr_zones") or {}
    hr_max = int(zones.get("hr_max", 0))
    rhr = int(zones.get("rhr", 0))
    lth = int(zones.get("lth", 0))
    injuries = [
        item.get("type") if isinstance(item, dict) else str(item)
        for item in athlete_data.get("injuries") or []
    ]
    return Athlete(
        vdot=float((athlete_data.get("current_form") or {}).get("vo2max", 0.0)),
        hr_zones={k: v for k, v in zones.get("zones", {}).items()},
        hr_max=hr_max,
        rhr=rhr,
        lth=lth,
        weight_kg=athlete_data.get("weight_kg_current"),
        injuries=[i for i in injuries if i],
        form=athlete_data.get("form_trend_4w"),
    )


def build_week(plan: dict[str, Any], season_plan: dict[str, Any]) -> Week:
    """Неделя из плана пайплайна: запросы, размещения, тренировки."""
    season_week = int(plan["season_week"])
    start = season_start_of(season_plan)
    week_start, week_end = season_week_range(start, season_week)

    macro = macro_week(season_plan, season_week)
    requests: list[Request] = []
    assignments: list[Assignment] = []
    workouts: list[Workout] = []

    for slot in plan.get("slots") or []:
        sport = SPORT_BY_PLAN_KIND.get(slot.get("kind", ""), Sport.RUN)
        duration = int(slot.get("duration_min", 0))
        request = Request(
            id=slot["id"],
            sport=sport,
            kind=slot.get("subkind") or slot.get("kind", ""),
            focus=slot.get("focus", ""),
            duration_min=duration,
            priority=int(slot.get("priority", 0)),
        )
        requests.append(request)
        assignments.append(Assignment(
            request_id=request.id,
            slot_id=slot["id"],
            start=slot.get("time", ""),
            duration_min=duration,
        ))

        steps = build_steps(slot, sport)
        workouts.append(Workout(
            id=f"w-{slot['id']}",
            request_id=request.id,
            sport=sport,
            kind=request.kind,
            focus=request.focus,
            objective={
                "name": slot.get("name", ""),
                "day": slot.get("day", ""),
                "subkind": _subkind_ru(slot),
                "session": slot.get("session") or {},
                "inventory": inventory_for(slot),
            },
            location=LOCATION_RU.get(slot.get("location"), slot.get("location")),
            time=slot.get("time"),
            steps=steps,
            duration_min=round(sum(s.duration_min for s in steps), 2),
            priority=request.priority,
            rationale=slot.get("rationale"),
        ))

    quality = macro.get("quality") or {}
    load_target = {
        "hours": float(macro.get("total_h", 0.0)),
        "sessions": float(macro.get("sessions_target", 0)),
        "distance_m": float(macro.get("run_km", 0)) * 1000.0,
        "intensity_pct": float(macro.get("intensity_pct", 0.0)),
    }

    week = Week(
        id=f"W{season_week}",
        plan_id=primary_goal(season_plan).get("id", "g1"),
        season_week=season_week,
        start=week_start,
        end=week_end,
        status=WeekStatus.PROPOSED,
        focus=quality.get("goal_text"),
        load_target=load_target,
        requests=requests,
        assignments=assignments,
        workouts=workouts,
    )
    week.validate()
    return week


def build_steps(slot: dict[str, Any], sport: Sport) -> list[Step]:
    """Шаги тренировки — плоский список из structure пайплайна.

    Вложенные set_repeats разворачиваются в отдельные шаги: домен хранит
    прогрессию отдельными шагами, а не вложенной структурой. Шаги сета
    помечаются `group` (название сета) и `round` (номер повтора) — по ним
    клиент собирает сет обратно.
    """
    steps: list[Step] = []
    structure = slot.get("structure") or []
    for index, item in enumerate(structure):
        repeats = item.get("set_repeats")
        if repeats:
            share = float(item.get("duration_min", 0)) / len(repeats)
            for position, repeat in enumerate(repeats, 1):
                steps.append(_step(
                    item, repeat, sport,
                    step_id=f"{slot['id']}-s{index}-{position}",
                    duration=share,
                    group=item.get("label"),
                    round_number=position,
                    reps=item.get("reps"),
                ))
            continue

        exercises = (item.get("set") or {}).get("exercises")
        if exercises:
            share = float(item.get("duration_min", 0)) / len(exercises)
            for position, exercise in enumerate(exercises, 1):
                steps.append(_exercise_step(
                    slot, item, exercise, sport,
                    step_id=f"{slot['id']}-s{index}-{position}",
                    duration=share,
                    group=item.get("set", {}).get("name") or item.get("phase"),
                    round_number=position,
                ))
            continue

        steps.append(_step(
            item, item, sport,
            step_id=f"{slot['id']}-s{index}",
            duration=float(item.get("duration_min", 0)),
            group=item.get("label"),
        ))
    return steps


def _exercise_step(slot: dict[str, Any], item: dict[str, Any],
                   exercise: dict[str, Any], sport: Sport,
                   step_id: str, duration: float,
                   group: str | None, round_number: int) -> Step:
    """Одно упражнение из сета ОФП."""
    reps = str(exercise.get("reps", ""))
    # «3×45с» → повторов 3, «2×12/стор» → 2. Первое число до «×».
    count = 0
    head = reps.split("×")[0] if "×" in reps else reps
    digits = "".join(ch for ch in head if ch.isdigit())
    if digits:
        count = int(digits)

    notes = exercise.get("notes")
    if exercise.get("rest"):
        notes = f"{notes} Отдых {exercise['rest']}." if notes else f"Отдых {exercise['rest']}."

    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=sport,
        target_type=TargetType.REPS,
        target_value=float(count),
        focus=FocusType.STRENGTH_PATTERN,
        focus_value={"reps": reps},
        group=group,
        round=round_number,
        label=exercise.get("name"),
        notes=notes,
        duration_min=duration,
    )


def _step(item: dict[str, Any], repeat: dict[str, Any], sport: Sport,
          step_id: str, duration: float, group: str | None = None,
          round_number: int | None = None,
          reps: int | None = None) -> Step:
    """Один шаг из элемента structure."""
    phase = repeat.get("phase") or item.get("phase") or "work"
    role = PHASE_ROLES.get(phase, StepRole.WORK)

    basis = repeat.get("basis") or item.get("basis")
    if basis == "distance":
        target_type = TargetType.DISTANCE
        target_value = float(repeat.get("distance_m", 0))
    elif basis == "time":
        target_type = TargetType.TIME
        target_value = duration
    elif repeat.get("reps") or reps:
        target_type = TargetType.REPS
        target_value = float(reps or repeat.get("reps") or 0)
    else:
        target_type = TargetType.OPEN
        target_value = duration

    zone = repeat.get("zone") or item.get("zone")
    focus_value: dict[str, Any] = {}
    if reps:
        focus_value["set_reps"] = reps
    if zone:
        focus = FocusType.HR
        focus_value["zone"] = zone
        if repeat.get("hr_target"):
            focus_value["hr_target"] = repeat["hr_target"]
        if repeat.get("pace_min_per_km"):
            focus_value["pace_min_per_km"] = repeat["pace_min_per_km"]
    elif repeat.get("pace_min_per_km"):
        focus = FocusType.PACE
        focus_value["pace_min_per_km"] = repeat["pace_min_per_km"]
    else:
        focus = FocusType.NONE

    notes = repeat.get("notes") or item.get("notes")
    if repeat.get("exercise"):
        notes = f"{repeat['exercise']}. {notes}" if notes else repeat["exercise"]

    return Step(
        id=step_id,
        role=role,
        sport=sport,
        target_type=target_type,
        target_value=target_value,
        focus=focus,
        focus_value=focus_value,
        group=group,
        round=round_number,
        label=repeat.get("label"),
        notes=notes,
        duration_min=duration,
    )


def build_sessions(cache: dict[str, Any], start: date) -> list[ActualSession]:
    """Факт из активностей Garmin: только за сезон."""
    sessions: list[ActualSession] = []
    for activity in cache.get("activities") or []:
        raw_date = activity.get("date")
        if not raw_date:
            continue
        try:
            day = datetime.fromisoformat(raw_date).date()
        except ValueError:
            continue
        if day < start:
            continue
        sport = SPORT_BY_PIPELINE.get(activity.get("sport_type", ""))
        if sport is None:
            continue
        activity_id = activity.get("activity_id")
        sessions.append(ActualSession(
            id=f"g-{activity_id}",
            date=day,
            sport=sport,
            duration_min=int(round((activity.get("duration_s") or 0) / 60)),
            distance_m=float((activity.get("distance_km") or 0) * 1000),
            hr_avg=int(activity["avg_hr"]) if activity.get("avg_hr") else None,
            hr_max=int(activity["max_hr"]) if activity.get("max_hr") else None,
            aerobic_te=activity.get("aerobic_te"),
            anaerobic_te=activity.get("anaerobic_te"),
            vo2max=activity.get("vo2max"),
            source=FactSource.GARMIN,
            external_id=str(activity_id),
            fetched_at=cache.get("pulled_at"),
        ))
    return sessions


def build_load_model(athlete_data: dict[str, Any]) -> dict[str, Any]:
    """Правило нагрузки.

    Коэффициенты адаптации — из пайплайна (реальные). Доли зон по
    VO2max — заглушка: разбор таблиц Дэниэлса ещё не сделан, и выдумывать
    числа значит показывать пользователю правдоподобную неправду.
    """
    rates = athlete_data.get("adaptation_rates") or {}
    return {
        "intensity_factor": {},
        "adaptation_rate": {
            k: float(v) for k, v in rates.items() if isinstance(v, (int, float))
        },
        "formula": "adaptation_rate — из пайплайна; intensity_factor — заглушка (этап 3б)",
        "budget": {},
    }


# ------------------------------------------------------------------ запись


def write_methodology(storage: FileStorage, season_plan: dict[str, Any],
                      athlete_data: dict[str, Any]) -> None:
    """Шаблоны тренировок и правило нагрузки — в методологию хранилища."""
    templates_path = STATE / "workout_templates.json"
    if templates_path.exists():
        storage.save_workout_templates(load_json(templates_path).get("templates", {}))
    model = build_load_model(athlete_data)
    storage.save_load_model(LoadModel(
        intensity_factor=model["intensity_factor"],
        adaptation_rate=model["adaptation_rate"],
        formula=model["formula"],
        budget=model["budget"],
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, default=None,
                        help="номер недели (по умолчанию — текущая по дате)")
    parser.add_argument("--root", default=None,
                        help="корень данных приложения")
    parser.add_argument("--today", default=None,
                        help="дата «сегодня» (для тестов)")
    args = parser.parse_args()

    season_plan = load_json(STATE / "season_plan.json")
    athlete_data = load_json(STATE / "athlete.json")
    constraints = load_json(STATE / "constraints.json")
    start = season_start_of(season_plan)
    today = date.fromisoformat(args.today) if args.today else date.today()

    season_week = args.week or week_of_date(start, today)
    plan_path = STATE / f"plan-w{season_week}.json"
    if not plan_path.exists():
        print(f"нет плана: {plan_path}", file=sys.stderr)
        return 2
    plan = load_json(plan_path)

    root = Path(args.root) if args.root else Path(
        os.environ.get("COACH_APP_DATA",
                       Path.home() / ".local" / "share" / "coach-app")
    )
    storage = FileStorage(root)

    season = build_season(season_plan, constraints)
    storage.save(season, expected_version=storage.version())
    storage.update_athlete(build_athlete(athlete_data))
    write_methodology(storage, season_plan, athlete_data)

    week = build_week(plan, season_plan)
    storage.put_week(week, expected_version=storage.version())

    sessions = build_sessions(load_json(STATE / "actual_load_cache.json"), start)
    for session in sessions:
        storage.upsert(session)

    print(f"корень данных:      {root}")
    print(f"сезон:              {season.id} {season.horizon_start} .. "
          f"{season.horizon_end}, {season.season_week_count} недель")
    print(f"неделя:             W{week.season_week} {week.start} .. {week.end}")
    print(f"тренировок в неделе: {len(week.workouts)}")
    print(f"факт:               {len(sessions)} сессий из Garmin")
    print(f"версия состояния:   {storage.version()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
