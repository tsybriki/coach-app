"""Производные значения домена.

Не хранятся — считаются. Каждое значение здесь выводится из состояния, поэтому
не может разойтись с ним.

Номера инвариантов — из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.entities import (
    ActualSession,
    Assignment,
    LoadModel,
    Slot,
    SlotOverride,
    Step,
    Week,
    Workout,
)
from app.domain.enums import FactSource, Sport


def merged_slots(
    season_slots: list[Slot],
    phase_overrides: list[SlotOverride],
    week_overrides: list[SlotOverride],
) -> list[Slot]:
    """I2: слот = Season ← Phase ← Week. Каждый уровень перекрывает предыдущий.

    Patch хранит только отличие от уровня выше: `remove` убирает слот,
    `set_time`/`set_capacity` меняют его, `add` добавляет новый.
    """
    slots: dict[str, Slot] = {s.id: s for s in season_slots}

    for overrides in (phase_overrides, week_overrides):
        for patch in overrides:
            for operation in patch.ops:
                op = operation.get("op", "")
                if op == "remove":
                    slots.pop(patch.slot_id, None)
                elif op == "set_time":
                    current = slots.get(patch.slot_id)
                    if current is not None:
                        slots[patch.slot_id] = _with_time(current, operation)
                elif op == "set_capacity":
                    current = slots.get(patch.slot_id)
                    if current is not None:
                        slots[patch.slot_id] = _with_capacity(current, operation)
                elif op == "add":
                    slots[patch.slot_id] = _added_slot(patch.slot_id, operation)

    return list(slots.values())


def _with_time(slot: Slot, operation: dict[str, Any]) -> Slot:
    return Slot(
        id=slot.id,
        day=slot.day,
        start=str(operation.get("start", slot.start)),
        end=str(operation.get("end", slot.end)),
        capacity_min=slot.capacity_min,
        equipment_ids=slot.equipment_ids,
        max_intensity=slot.max_intensity,
        forbidden_sports=slot.forbidden_sports,
        note=slot.note,
        priority_hint=slot.priority_hint,
    )


def _with_capacity(slot: Slot, operation: dict[str, Any]) -> Slot:
    return Slot(
        id=slot.id,
        day=slot.day,
        start=slot.start,
        end=slot.end,
        capacity_min=int(operation.get("capacity_min", slot.capacity_min)),
        equipment_ids=slot.equipment_ids,
        max_intensity=slot.max_intensity,
        forbidden_sports=slot.forbidden_sports,
        note=slot.note,
        priority_hint=slot.priority_hint,
    )


def _added_slot(slot_id: str, operation: dict[str, Any]) -> Slot:
    return Slot(
        id=slot_id,
        day=int(operation.get("day", 0)),
        start=str(operation.get("start", "00:00")),
        end=str(operation.get("end", "23:59")),
        capacity_min=int(operation.get("capacity_min", 60)),
    )


def workout_load_min(workout: Workout, load_model: LoadModel) -> float:
    """Нагрузка тренировки = Σ (минуты шага × intensity_factor × adaptation_rate).

    Минуты — из шагов, фактор зоны — из LoadModel, коэффициент вида спорта — тоже.
    """
    factor_by_zone = load_model.intensity_factor
    rate = load_model.adaptation_rate.get(workout.sport.value, 1.0)
    total = 0.0
    for step in workout.steps:
        factor = factor_by_zone.get(step_zone(step), 1.0)
        total += step.duration_min * factor * rate
    return total


def step_zone(step: Step) -> str:
    """Зона шага.

    Фокус — это вид интенсивности (`hr`, `pace`, …), а зона — конкретный
    диапазон (`Z2`, `Z5`). Фактор нагрузки берётся по зоне; если зоны нет —
    нейтральный фактор 1.0.
    """
    zone = step.focus_value.get("zone")
    if zone:
        return str(zone)
    return step.focus.value


def week_load_min(week: Week, load_model: LoadModel) -> float:
    """Нагрузка недели = Σ по тренировкам."""
    return sum(workout_load_min(w, load_model) for w in week.workouts)


def planned_intensity_min(week: Week, load_model: LoadModel) -> dict[str, int]:
    """Плановые intensity minutes: расчёт по шагам через зоны атлета.

    Возвращает moderate/vigorous по зонам: Z1–Z3 — moderate, Z4+ — vigorous.
    """
    moderate = 0.0
    vigorous = 0.0
    for workout in week.workouts:
        rate = load_model.adaptation_rate.get(workout.sport.value, 1.0)
        for step in workout.steps:
            minutes = step.duration_min * rate
            if step.focus.value in ("hr", "pace", "power"):
                zone = str(step.focus_value.get("zone", "Z2"))
                if zone in ("Z4", "Z5", "Z6", "Z7"):
                    vigorous += minutes
                else:
                    moderate += minutes
            else:
                moderate += minutes
    return {"moderate": int(moderate), "vigorous": int(vigorous)}


def actual_intensity_min(sessions: list[ActualSession]) -> dict[str, int]:
    """I27/I28/I29: интенсивность — только из тренировок, по тренировкам.

    Недельные агрегаты Garmin (пн→вс) не используются — считаем сами по
    тренировкам. Если источник не делит интенсивность — всё идёт в moderate.
    """
    moderate = 0
    vigorous = 0
    for session in sessions:
        if session.source is FactSource.GARMIN and session.moderate_min == 0 \
                and session.vigorous_min == 0:
            # источник не разделил — всё в moderate
            moderate += session.duration_min
            continue
        moderate += session.moderate_min
        vigorous += session.vigorous_min
    return {"moderate": moderate, "vigorous": vigorous}


def facts_in_week_range(week: Week, sessions: list[ActualSession]) -> list[ActualSession]:
    """I17: вклад в неделю принимается только из факта с датой в её диапазоне."""
    return [s for s in sessions if week.start <= s.date <= week.end]


def week_contributions(
    week: Week, sessions: list[ActualSession]
) -> list[dict[str, int | str]]:
    """I18: один факт — один вклад в неделю."""
    contributions: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for session in facts_in_week_range(week, sessions):
        if session.id in seen:
            continue
        seen.add(session.id)
        contributions.append(
            {
                "actual_id": session.id,
                "moderate_min": session.moderate_min,
                "vigorous_min": session.vigorous_min,
            }
        )
    return contributions


def plan_week_totals(week: Week) -> dict[str, float]:
    """I26: висяки учитываются в плане недели.

    План недели = размещённые тренировки + висяки. Висяк без дня, но он часть
    плана: иначе план занижен.
    """
    placed_min = sum(a.duration_min for a in week.assignments)
    unplaced_min = sum(r.duration_min for r in week.unplaced)
    sessions = len(week.assignments) + len(week.unplaced)
    return {
        "minutes": float(placed_min + unplaced_min),
        "placed_min": float(placed_min),
        "unplaced_min": float(unplaced_min),
        "sessions": float(sessions),
    }


def empty_week_totals() -> dict[str, float]:
    """I30: неделя без факта показывается с нулями."""
    return {"minutes": 0.0, "distance_m": 0.0, "load_min": 0.0, "sessions": 0.0}


def actual_week_totals(sessions: list[ActualSession]) -> dict[str, float]:
    """Фактические цифры недели по факту."""
    return {
        "minutes": float(sum(s.duration_min for s in sessions)),
        "distance_m": float(sum(s.distance_m for s in sessions)),
        "sessions": float(len(sessions)),
    }




def preserve_fact_links(
    existing: list[ActualSession],
    incoming: list[ActualSession],
) -> list[ActualSession]:
    """Факт из внешнего источника не теряет связь, поставленную пользователем.

    Выкачка Garmin приходит без `linked_workout_id`: связь ставит человек,
    а не источник. Если при перезаписи факта её терять, то после любой
    выкачки все привязки исчезают, а факты снова предлагаются к связыванию.

    Разрыв связи — осознанное действие пользователя, поэтому он делается
    только через `link(actual_id, None)`.
    """
    linked = {
        session.id: session.linked_workout_id
        for session in existing
        if session.linked_workout_id
    }
    for session in incoming:
        if session.id in linked:
            session.linked_workout_id = linked[session.id]
    return incoming

def week_progress(week: Week, sessions: list[ActualSession]) -> dict[str, Any]:
    """Факт недели против плана: «N из M».

    План — из `load_target` макро-недели (часы, сессии, километраж бега).
    Факт — из сессий недели. Считается по всем активностям недели, а не по
    связанным: выполненная тренировка вкладывается в объём независимо от
    того, связал её пользователь или нет.

    `distance_m` плана — это бег (макро считает `run_km`). Факт бега —
    сумма сессий со спортом `run`. Километраж велосипеда и плавания в беговый
    объём не идёт.
    """
    target = week.load_target or {}
    planned_hours = float(target.get("hours") or 0.0)
    planned_sessions = int(target.get("sessions") or 0)
    planned_distance_m = float(target.get("distance_m") or 0.0)

    in_week = facts_in_week_range(week, sessions)
    actual_minutes = sum(s.duration_min for s in in_week)
    actual_distance_m = sum(s.distance_m for s in in_week if s.sport is Sport.RUN)

    return {
        "hours": {
            "planned": planned_hours,
            "actual": actual_minutes / 60.0,
        },
        "sessions": {
            "planned": planned_sessions,
            "actual": len(in_week),
        },
        "distance_m": {
            "planned": planned_distance_m,
            "actual": actual_distance_m,
        },
    }

def race_week_of(plan_id: str, goal_race_date: date, plan_period: tuple[date, date]) -> int | None:
    """I33: неделя гонки принадлежит плану.

    Возвращает номер недели гонки внутри плана, если дата попадает в период.
    """
    start, end = plan_period
    if not (start <= goal_race_date <= end):
        return None
    return ((goal_race_date - start).days // 7) + 1


def plans_overlap(a: tuple[date, date], b: tuple[date, date]) -> bool:
    """I34: планы не перекрываются."""
    return a[0] <= b[1] and b[0] <= a[1]


def round_duration_to_minutes(minutes: float) -> int:
    """I35: для силовой и ОФП — общая длительность тренировки, округлённая до минут."""
    return round(minutes)


def step_is_strength_or_ofp(step: Step) -> bool:
    """Силовая и ОФП: длительность — общая, не по шагам."""
    return step.sport in (Sport.STRENGTH, Sport.OFP)


def unplaced_without_fact_is_missed(week: Week, sessions: list[ActualSession]) -> list[str]:
    """I38: висящая тренировка без факта ⇒ пропущена."""
    linked = {s.linked_workout_id for s in sessions if s.linked_workout_id}
    missed: list[str] = []
    for request in week.unplaced:
        workouts = [w for w in week.workouts if w.request_id == request.id]
        if workouts and not any(w.id in linked for w in workouts):
            missed.append(request.id)
    return missed


def is_today(target: date, today: date) -> bool:
    """I39: «сегодня» определяется по календарной дате."""
    return target == today


def phase_goal_is_distinct(plan_goal_id: str, phase_objective: str) -> bool:
    """I36: Plan.goal и Phase.objective — разные вещи."""
    return bool(phase_objective) and phase_objective != plan_goal_id


def has_status_field(obj: object) -> bool:
    """I37: у Request и Assignment нет статуса — состояние выводится.

    Функция-проверка для теста: у этих сущностей не должно быть поля статуса.
    """
    return "status" in getattr(obj, "__dataclass_fields__", {})


def assignments_by_request(week: Week) -> dict[str, Assignment]:
    """Размещения по запросу — состояние выводится из наличия Assignment."""
    return {a.request_id: a for a in week.assignments}


def request_is_placed(week: Week, request_id: str) -> bool:
    """I37: размещён (есть Assignment) или висит (в unplaced[])."""
    return request_id in assignments_by_request(week)


def unique_external_ids(sessions: list[ActualSession]) -> bool:
    """I42: external_id уникален."""
    ids = [s.external_id for s in sessions if s.external_id]
    return len(ids) == len(set(ids))


def only_garmin_sources(sessions: list[ActualSession]) -> bool:
    """I14: активности берутся только из Garmin.

    Ручной факт (`source: manual`) допустим — он создан человеком, а не получен
    из внешнего источника активностей. Garmin-сессии — всегда Garmin.
    """
    return all(s.source is not FactSource.GARMIN or s.external_id for s in sessions)


__all__ = [
    "actual_intensity_min",
    "actual_week_totals",
    "assignments_by_request",
    "empty_week_totals",
    "facts_in_week_range",
    "has_status_field",
    "is_today",
    "merged_slots",
    "only_garmin_sources",
    "phase_goal_is_distinct",
    "plan_week_totals",
    "planned_intensity_min",
    "plans_overlap",
    "race_week_of",
    "request_is_placed",
    "round_duration_to_minutes",
    "unplaced_without_fact_is_missed",
    "unique_external_ids",
    "week_contributions",
    "week_load_min",
    "workout_load_min",
]
