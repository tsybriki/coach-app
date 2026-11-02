"""Предложение недели: макро + правила методики → неделя для активации.

Команда `propose_week` собирает неделю заново по правилам. Планировщик
(`WeekPlanner`) умеет раскладывать рецепты по слотам, но не знает, что
взять из текущей недели: макро (объём по видам спорта) живёт в самой неделе.

Поэтому здесь — тонкий слой поверх планировщика: достать макро из текущей
недели, добавить к бегу качественную работу по правилам Дэниэлса, собрать
неделю заново.

**Длинный бег** — по правилу Дэниэлса: 25 % недельного километража или
1,5 часа, что меньше. Остальное время — лёгкий бег.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.domain.entities import (
    Assignment,
    MacroWeek,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import PlanStatus, Sport, TargetType, WeekStatus
from app.services.week_lifecycle import TransitionError
from app.services.week_planner import (
    WeeklyTarget,
    WeekPlanInput,
    WeekPlanner,
    shift_time,
)

# Длинный бег: 25 % недельного километража или 1,5 часа, что меньше.
LONG_FRACTION = 0.25
LONG_MAX_MIN = 90


@dataclass
class MacroVolume:
    """Объём недели по виду спорта — из текущей недели."""

    minutes: dict[Sport, int] = None  # type: ignore[assignment]
    run_km: float = 0.0
    long_min: int = 0
    # Разбивка тренировок по видам спорта: «2×25м» → [25, 25].
    sessions: dict[str, list[int]] = None  # type: ignore[assignment]
    # Число лёгких пробежек недели — из макро.
    easy_runs: int = 0

    def __post_init__(self) -> None:
        if self.minutes is None:
            self.minutes = {}
        if self.sessions is None:
            self.sessions = {}


def macro_from_week(week: Week) -> MacroVolume:
    """Макро текущей недели: минуты по видам спорта и километраж бега.

    Километраж бега берётся из `load_target.distance_m` — это цель недели,
    заданная макро, а не факт пробега.
    """
    minutes: dict[Sport, int] = {}
    long_min = 0
    for workout in week.workouts:
        minutes[workout.sport] = minutes.get(workout.sport, 0) + int(workout.duration_min)
        # Вид длинного бега в плане пайплайна — `long_Z2`: регистр и
        # подчёркивание не несут смысла, несёт смысл слово `long`.
        if workout.kind.lower().startswith("long"):
            long_min += int(workout.duration_min)
    run_km = float(week.load_target.get("distance_m", 0.0)) / 1000.0
    return MacroVolume(minutes=minutes, run_km=run_km, long_min=long_min)

def weeks_to_race(season: Season, week_start: date) -> int:
    """Горизонт сезона — от старта сезона до гонки, **в неделях до гонки**.

    Этот срок определяет, как программа Дэниэлса раскладывается по фазам.

    **Горизонт один на весь сезон.** Он считается от старта сезона, а не от
    начала текущей недели: если считать заново каждую неделю, к гонке
    горизонт сжимается, а номер недели сезона растёт — и неделя
    запрашивается за пределами расписания. Тогда неделя собирается без
    качественной работы программы молча, без ошибки, а макро-план и
    планировщик показывают разные недели.

    Расписание программы покрывает недели **до** гонки. Неделя гонки —
    событие, а не тренировка, и планировать её не нужно (Кирилл,
    01.11.2026): в макро-плана её нет, гонка живёт в календаре сезона.
    Лишняя неделя программы уходит по `EXTRA` в фазу по кругу — как у
    планировщика.
    """
    for plan in season.plans:
        days = (plan.goal.race_date - season.horizon_start).days
        if days >= 0:
            return days // 7
    return 0


def is_race_week(season: Season, week_start: date, week_end: date) -> bool:
    """Неделя гонки — та, в которую попадает дата гонки.

    Гонка — событие недели, а не тренировка: в неделю гонки нет качественной
    работы по программе, есть гонка и восстановление после неё.
    """
    return any(
        week_start <= plan.goal.race_date <= week_end for plan in season.plans
    )


def build_targets(macro: MacroVolume, week: Week) -> list[WeeklyTarget]:
    """Запросы недели: бег по правилам Дэниэлса.

    Не беговые виды спорта (велосипед, плавание, ОФП) сюда не входят: их
    структуру задаёт не Дэниэлс, а макро и среда, поэтому они переносятся
    из текущей недели как есть — иначе они попали бы в план дважды.
    """
    targets: list[WeeklyTarget] = []

    run_minutes = macro.minutes.get(Sport.RUN, 0)
    if run_minutes > 0:
        long_min = macro.long_min
        if not long_min and macro.run_km > 0:
            # Длинный бег по правилу: 25 % недельного километража или 1,5 ч.
            long_min = int(min(macro.run_km * LONG_FRACTION, LONG_MAX_MIN))
        # Потолок правила — всегда: 25 % недельного километража **или**
        # 1,5 часа, что меньше. Без него длинный пробежек растёт с
        # километражом недели и перестаёт быть длинным пробежком.
        long_min = min(long_min, LONG_MAX_MIN)
        targets.append(WeeklyTarget(
            sport=Sport.RUN,
            duration_min=run_minutes,
            focus=week.focus or "",
            kind="easy",
            long_min=long_min or None,
        ))
    return targets


def _macro_week_of(season: Season, season_week: int) -> MacroWeek:
    """Макро-неделя сезона — или отказ."""
    plan = next((p for p in season.plans if p.status is PlanStatus.ACTIVE), None)
    if plan is None:
        raise TransitionError("в сезоне нет активного плана")
    macro = plan.macro_week(season_week)
    if macro is None:
        raise TransitionError(f"в макро-плане нет недели W{season_week}")
    return macro


def macro_for_season_week(season: Season, season_week: int) -> MacroVolume:
    """Макро недели — из макро-плана сезона.

    Источник объёма — макро-план сезона, а не сохранённая неделя: неделя
    хранит то, что уже собрано, и повторный propose сжимал бы неделю.
    """
    return macro_from_macro_week(_macro_week_of(season, season_week))


def macro_from_macro_week(macro: MacroWeek) -> MacroVolume:
    """Макро недели — из макро-недели сезона.

    Для недели, которой ещё нет в хранилище: источник — макро-план
    сезона (`Plan.macro_weeks`), а не сохранённая неделя.

    Бег берётся **разбивкой пайплайна**: длинная + качественная + лёгкая.
    Качественная работа по правилам Дэниэлса идёт внутри недельного объёма
    бега, а не добавляется к нему — иначе неделя раздувается вдвое.
    """
    minutes: dict[Sport, int] = {}
    for sport, value in macro.minutes_by_sport.items():
        try:
            minutes[Sport(sport)] = int(round(value))
        except ValueError:
            continue

    run_minutes = minutes.get(Sport.RUN, 0)
    if run_minutes and macro.long_min + macro.quality_min + macro.easy_min:
        # Разбивка известна — бег собирается из неё.
        run_minutes = (macro.long_min + macro.quality_min + macro.easy_min)
        minutes[Sport.RUN] = run_minutes

    run_km = macro.run_km
    long_min = macro.long_min
    if not long_min and run_km > 0:
        # Длинный бег по правилу: 25 % недельного километража или 1,5 ч.
        long_min = int(min(run_km * LONG_FRACTION, LONG_MAX_MIN))
    elif long_min > LONG_MAX_MIN:
        # Правило Дэниэлса: 25 % недельного километража **или** 1,5 часа,
        # что меньше. Макро считает длинный бег по километражу без потолка —
        # потолок применяется здесь.
        long_min = LONG_MAX_MIN
    return MacroVolume(minutes=minutes, run_km=run_km, long_min=long_min,
                       sessions=dict(macro.sessions_by_sport),
                       easy_runs=macro.easy_runs)


def plan_from_macro(season: Season,
                     season_week: int,
                     planner: WeekPlanner,
                     templates: dict[str, Any] | None = None,
                     ) -> Week:
    """Собрать неделю сезона из макро-плана и правил Дэниэлса.

    Неделя, которой ещё нет в хранилище, собирается с нуля: объём по
    видам спорта — из макро-плана сезона, качественная работа бега — из
    правил Дэниэлса по неделе программы, раскладка по слотам — из среды.

    Это то, чем пользователь планирует следующую неделю с телефона:
    кнопка «Спланировать неделю» не требует, чтобы неделя уже была
    создана заранее.
    """
    plan = next((p for p in season.plans if p.status is PlanStatus.ACTIVE), None)
    if plan is None:
        raise TransitionError("в сезоне нет активного плана")
    templates = templates or {}
    macro_week = plan.macro_week(season_week)
    if macro_week is None:
        raise TransitionError(
            f"в макро-плане нет недели W{season_week}"
        )

    week_start = season.horizon_start + timedelta(days=7 * (season_week - 1))
    week_end = week_start + timedelta(days=6)

    volume = macro_from_macro_week(macro_week)
    targets = build_targets(volume, _stub_week(macro_week, season_week,
                                               week_start, week_end, plan.id))
    if not targets:
        raise TransitionError(
            f"в макро недели W{season_week} нет объёма — нечего планировать"
        )

    race_week = is_race_week(season, week_start, week_end)

    # Контрольная точка — первая: она задаёт качественную работу недели
    # и занимает лучшее окно.
    cp_workout, cp_slot = _plan_control_point(
        macro_week, templates, season)

    # Тестовая сессия — часть недельного объёма бега, а не добавка к нему:
    # иначе неделя раздувается на её длительность.
    cp_workout_km = 0.0
    if cp_workout is not None:
        run_minutes = volume.minutes.get(Sport.RUN, 0)
        cp_minutes = int(round(cp_workout.duration_min))
        volume.minutes[Sport.RUN] = max(run_minutes - cp_minutes, 0)
        targets = build_targets(volume, _stub_week(
            macro_week, season_week, week_start, week_end, plan.id))
        # Километраж теста — часть недельного километража, а не добавка.
        cp_workout_km = _workout_km(cp_workout)

    # Не беговые виды спорта занимают слоты **после** бега: правило
    # Дэниэлса требует пробежку в каждый день недели («7 дней в неделю
    # Л-темп»), и семь пробежек разбирают семь дней. Если вел и плавание
    # встанут первыми, на пробежки останется пять дней, а неделя
    # покажет четыре.
    planned = planner.build_from(WeekPlanInput(
        season_week=season_week,
        week_start=week_start,
        week_end=week_end,
        targets=targets,
        slots=season.slots,
        weeks_to_race=0 if race_week else weeks_to_race(season, week_start),
        run_km=volume.run_km,
        easy_runs=volume.easy_runs,
        plan_id=plan.id,
        # Контрольная точка — одна из пробежек недели и часть её
        # километража: форма фазы считает остаток.
        reserved_km=cp_workout_km,
        reserved_runs=1 if cp_workout is not None else 0,
        reserved_slots=(cp_slot.id,) if cp_slot is not None else (),
    ))

    # Вел, плавание и ОФП — в окна, оставшиеся от пробежек.
    others, _other_slots = _plan_other_sports(
        volume, season,
        reserved={cp_slot.id} if cp_slot is not None else set(),
        occupied=_occupied_minutes(planned.assignments),
        skip_ofp=_ofp_inside_runs(planner, season, season_week, race_week),
    )

    planned = _merge_others(planned, others, season)
    if cp_workout is not None:
        planned = _merge_control_point(planned, cp_workout)

    planned.load_target = planner.load_target_for_week(planned)
    planned.validate()
    return planned


def _stub_week(macro: MacroWeek, season_week: int, week_start: date,
               week_end: date, plan_id: str) -> Week:
    """Пустая неделя — только ради макро и фокуса.

    `build_targets` берёт из недели фокус и минуты по видам спорта, а
    сами минуты приходят из макро-недели.
    """
    return Week(
        id=f"W{season_week}",
        plan_id=plan_id,
        season_week=season_week,
        start=week_start,
        end=week_end,
        status=WeekStatus.PROPOSED,
        focus=macro.goal_text or macro.focus,
        load_target={
            "hours": macro.total_h,
            "sessions": float(macro.sessions_target),
            "distance_m": macro.run_km * 1000.0,
        },
    )


def _workout_km(workout: Workout) -> float:
    """Километраж тренировки — по шагам с дистанцией.

    Тестовая сессия — часть недельного километража: без этого форма
    фазы считает километраж недели, к которому тест добавился сверху.
    """
    meters = sum(
        float(step.target_value)
        for step in workout.steps
        if step.target_type == TargetType.DISTANCE
    )
    return meters / 1000.0


def _plain_step(sport: Sport, minutes: int) -> Step:
    """Шаг тренировки без структуры: один кусок на всю длительность.

    У велотренировки и бассейна нет зон и шагов Дэниэлса: инвариант
    «длительность тренировки = Σ шагов» всё равно должен держаться, поэтому
    шаг один и на всю тренировку.
    """
    from app.domain.entities import Step
    from app.domain.enums import FocusType, StepRole, TargetType

    return Step(
        id="s1",
        role=StepRole.WORK,
        sport=sport,
        target_type=TargetType.TIME,
        target_value=float(minutes),
        focus=FocusType.HR,
        focus_value={"zone": "Z2"},
        duration_min=float(minutes),
    )


def _plan_control_point(macro: MacroWeek,
                        templates: dict[str, Any],
                        season: Season,
                        ) -> tuple[Workout | None, Slot | None]:
    """Контрольная точка недели — качественная сессия.

    Тестовая сессия задаёт работу недели: её дистанция и темп — из цели
    CP, структура — из каталога шаблонов. В неделе программы, где по
    правилам Дэниэлса качественной работы нет, CP всё равно её создаёт:
    это проверка формы, а не тренировка по программе.
    """
    cp = macro.control_point
    if not cp:
        return None, None
    if cp.get("kind") != "quality":
        return None, None

    variant = _cp_variant(templates, cp.get("variant_id"))
    if variant is None:
        return None, None

    distance = float(cp.get("distance_m") or variant.get("work_m") or 0.0)
    pace = cp.get("pace_min_per_km")
    pace_sec = _pace_seconds(pace)
    if pace_sec is None:
        return None, None

    # Разминка и заминка — по правилу CP: 15 мин Z1 и 12 мин Z1.
    warmup = 15.0
    cooldown = 12.0
    # Темп — секунды на КИЛОМЕТР, дистанция — метры: переводим.
    work_min = (distance / 1000.0) * pace_sec / 60.0

    steps = [
        _cp_step("s1", Sport.RUN, warmup, zone="Z1"),
        _cp_step("s2", Sport.RUN, work_min, zone="Z4",
                 pace=pace, distance=distance),
        _cp_step("s3", Sport.RUN, cooldown, zone="Z1"),
    ]
    total = warmup + work_min + cooldown

    slot = _slot_for_sport(season, Sport.RUN, int(round(total)),
                            set())
    workout = Workout(
        id="w-control-point",
        request_id="r-control-point",
        sport=Sport.RUN,
        kind="quality",
        focus=cp.get("session_goal") or cp.get("title") or "Контрольная точка",
        objective={
            "name": cp.get("title") or "Контрольная точка",
            "session": cp,
            "slot_id": slot.id if slot else "",
        },
        time=slot.start if slot else None,
        steps=steps,
        duration_min=total,
    )
    return workout, slot


def _cp_variant(templates: dict[str, Any], variant_id: str | None) -> dict[str, Any] | None:
    """Вариант каталога для контрольной точки."""
    if not variant_id:
        return None
    for variant in (templates.get("time_trial") or {}).get("variants", []):
        if variant.get("id") == variant_id:
            found: dict[str, Any] = variant
            return found
    return None


def _cp_step(step_id: str, sport: Sport, minutes: float, *,
             zone: str = "Z2", pace: str | None = None,
             distance: float = 0.0) -> Step:
    """Шаг тестовой сессии."""
    from app.domain.enums import FocusType, StepRole, TargetType

    focus_value: dict[str, Any] = {"zone": zone}
    if pace:
        focus_value["pace_min_per_km"] = pace
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=sport,
        target_type=(TargetType.DISTANCE if distance
                     else TargetType.TIME),
        target_value=distance if distance else minutes,
        focus=FocusType.HR if zone != "Z4" else FocusType.PACE,
        focus_value=focus_value,
        duration_min=round(minutes, 2),
    )


def _pace_seconds(pace: str | None) -> float | None:
    """'4:40' → 280 секунд на километр."""
    if not pace or ":" not in pace:
        return None
    minutes, _, seconds = pace.partition(":")
    try:
        return float(minutes) * 60.0 + float(seconds)
    except ValueError:
        return None


def _ofp_inside_runs(planner: WeekPlanner, season: Season,
                     season_week: int, race_week: bool) -> bool:
    """ОФП этой недели — внутри пробежек, а не отдельными тренировками.

    Форма фазы добавляет ОФП в конец пробежки («к трём из семи
    тренировок — ОФП в конце»). Если поставить ещё и отдельные тренировки
    ОФП из макро, неделя покажет ОФП дважды.
    """
    if race_week:
        return False
    horizon = weeks_to_race(season, season.horizon_start)
    shape = planner.phase_shape_for(season_week, horizon)
    return bool(shape and shape.ofp_minutes > 0 and shape.ofp_runs > 0)


def _occupied_minutes(assignments: list[Assignment]) -> dict[str, int]:
    """Сколько минут занято в каждом окне.

    Вел, плавание и ОФП встают в окна, оставшиеся от пробежек: окно
    вмещает две тренировки (утром пробежка, вечером вел), и без учёта
    занятости вел занял бы то же окно, что и пробежка.
    """
    occupied: dict[str, int] = {}
    for assignment in assignments:
        occupied[assignment.slot_id] = (
            occupied.get(assignment.slot_id, 0) + int(assignment.duration_min)
        )
    return occupied


def _plan_other_sports(volume: MacroVolume, season: Season,
                       taken: set[str] | None = None,
                       reserved: set[str] | None = None,
                       occupied: dict[str, int] | None = None,
                       skip_ofp: bool = False,
                       ) -> tuple[list[Workout], set[str]]:
    """Вел, плавание и ОФП — по объёму макро, раскладка — по слотам среды.

    Правила Дэниэлса задают бег. Остальные виды спорта приходят из макро
    и среды: их объём известен, а куда поставить — решает слот.

    Возвращает тренировки и занятые слоты: бег встанет в оставшиеся.
    """
    workouts: list[Workout] = []
    used: set[str] = set(taken or set())
    occupied = occupied or {}

    for sport in (Sport.BIKE, Sport.SWIM, Sport.OFP):
        minutes = int(volume.minutes.get(sport, 0))
        if minutes <= 0:
            continue
        # ОФП внутри пробежек — отдельными тренировками не делаем: иначе
        # неделя покажет ОФП дважды.
        if sport is Sport.OFP and skip_ofp:
            continue
        # Разбивка из макро: «2×25м» — две тренировки по 25 минут, а не
        # одна на 50. Без разбивки число сессий не сходится с планом.
        parts = volume.sessions.get(sport.value) or [minutes]
        name = {
            Sport.BIKE: "Вел",
            Sport.SWIM: "Пул",
            Sport.OFP: "ОФП",
        }[sport]
        for index, part in enumerate(parts):
            part_minutes = int(part)
            if part_minutes <= 0:
                continue
            slot = _slot_for_sport(
                season, sport, part_minutes, used,
                reserved=reserved or set(),
                occupied=occupied,
            )
            if slot is None:
                continue
            used.add(slot.id)
            occupied[slot.id] = occupied.get(slot.id, 0) + part_minutes
            workouts.append(Workout(
                id=f"w-{sport.value}-{index + 1}",
                request_id=f"r-{sport.value}-{index + 1}",
                sport=sport,
                kind=sport.value,
                focus=sport.value,
                objective={"name": f"{name} {part_minutes}мин",
                           "day": slot.day,
                           "slot_id": slot.id},
                time=shift_time(slot.start, occupied[slot.id] - part_minutes),
                steps=[_plain_step(sport, part_minutes)],
                duration_min=float(part_minutes),
            ))
    return workouts, used


def _merge_control_point(week: Week, workout: Workout) -> Week:
    """Добавить тестовую сессию контрольной точки к собранной неделе."""
    from app.domain.entities import Assignment, Request

    request_id = f"r{week.season_week}-cp"
    requests = list(week.requests)
    requests.append(Request(
        id=request_id,
        sport=workout.sport,
        kind=workout.kind,
        focus=workout.focus,
        duration_min=int(workout.duration_min),
    ))
    assignments = list(week.assignments)
    slot_id = str((workout.objective or {}).get("slot_id") or "")
    if slot_id:
        assignments.append(Assignment(
            request_id=request_id,
            slot_id=slot_id,
            start=workout.time or "",
            duration_min=int(workout.duration_min),
        ))
    workouts = list(week.workouts)
    workouts.append(_rebind(workout, request_id))
    return week.copy_with(requests=requests, assignments=assignments,
                           workouts=workouts)


def _merge_others(week: Week, others: list[Workout],
                   season: Season) -> Week:
    """Добавить не беговые тренировки к собранной неделе.

    Запросы и размещения создаются под них, чтобы инвариант «каждый
    Workout вырос из Request» не нарушился.
    """
    from app.domain.entities import Assignment, Request

    if not others:
        return week

    requests = list(week.requests)
    assignments = list(week.assignments)
    workouts = list(week.workouts)

    for index, workout in enumerate(others):
        request_id = f"r{week.season_week}-other-{index + 1}"
        requests.append(Request(
            id=request_id,
            sport=workout.sport,
            kind=workout.kind,
            focus=workout.focus,
            duration_min=int(workout.duration_min),
        ))
        slot_id = str((workout.objective or {}).get("slot_id") or "")
        slot = _slot_by_id(season, slot_id)
        if slot is None:
            # Без окна тренировка — висяк: решение пользователя.
            unplaced = list(week.unplaced)
            unplaced.append(requests[-1])
            week = week.copy_with(unplaced=unplaced)
        else:
            assignments.append(Assignment(
                request_id=request_id,
                slot_id=slot.id,
                start=workout.time or slot.start,
                duration_min=int(workout.duration_min),
            ))
        workouts.append(_rebind(workout, request_id))

    return week.copy_with(requests=requests, assignments=assignments,
                           workouts=workouts)


def _slot_by_id(season: Season, slot_id: str) -> Slot | None:
    """Окно по id.

    Время начала тренировки может быть сдвинуто (окно вмещает две
    тренировки), поэтому искать окно по времени нельзя.
    """
    if not slot_id:
        return None
    for slot in season.slots:
        if slot.id == slot_id:
            return slot
    return None


def _rebind(workout: Workout, request_id: str) -> Workout:
    """Тренировка с другим id запроса."""
    return Workout(
        id=workout.id,
        request_id=request_id,
        sport=workout.sport,
        kind=workout.kind,
        focus=workout.focus,
        objective=workout.objective,
        equipment_ids=workout.equipment_ids,
        location=workout.location,
        time=workout.time,
        steps=workout.steps,
        duration_min=workout.duration_min,
        priority=workout.priority,
        rationale=workout.rationale,
    )


def _slot_by_start(season: Season, start: str | None) -> Slot | None:
    """Слот по времени начала — для уже размещённой тренировки."""
    if not start:
        return None
    for slot in season.slots:
        if slot.start == start:
            return slot
    return None


def _slot_for_sport(season: Season, sport: Sport, minutes: int,
                    taken: set[str],
                    reserved: set[str] | None = None,
                    occupied: dict[str, int] | None = None,
                    ) -> Slot | None:
    """Слот для вида спорта: по вместимости и запрету видов спорта.

    Окно может вместить две тренировки, поэтому считаем не занятые
    слоты, а занятые минуты: вел встаёт в окно после пробежки, если
    там ещё есть место.
    """
    occupied = occupied or {}
    for slot in season.slots:
        if slot.id in taken:
            continue
        if slot.id in (reserved or set()):
            continue
        free = slot.capacity_min - occupied.get(slot.id, 0)
        if free < minutes:
            continue
        if sport in slot.forbidden_sports:
            continue
        return slot
    return None


def propose_week(season: Season,
                 current: Week,
                 planner: WeekPlanner,
                 templates: dict[str, Any] | None = None,
                 ) -> Week:
    """Собрать неделю по правилам методики.

    `current` — текущая неделя: из неё берётся макро (объём по видам спорта).
    Качественная работа по бегу — из правил Дэниэлса, по номеру недели
    программы для этого срока до старта.

    I21/I40: повторный propose полностью заменяет содержимое proposed-недели.
    I23: закрытая неделя не меняется — предлагать её заново нельзя.
    """
    if current.status is not WeekStatus.PROPOSED:
        raise TransitionError(
            f"предложить заново можно только proposed-неделю, а не {current.status}"
        )

    # Объём — из макро-плана сезона, а не из самой недели: иначе повторный
    # propose сжимает неделю (объём берётся из того, что уже собрано) и
    # неделя с каждым нажатием становится всё короче.
    templates = templates or {}
    macro = macro_for_season_week(season, current.season_week)
    macro_week = _macro_week_of(season, current.season_week)
    targets = build_targets(macro, current)
    if not targets:
        raise ValueError("в неделе нет объёма — нечего предлагать")

    slots = list(season.slots)
    # Неделя гонки — событие, а не тренировка: в ней нет качественной
    # работы по программе. Гонка и восстановление после неё — из макро.
    race_week = is_race_week(season, current.start, current.end)

    # Не беговые виды спорта занимают слоты **после** бега: правило
    # Дэниэлса требует пробежку в каждый день недели («7 дней в неделю
    # Л-темп»), и семь пробежек разбирают семь дней.
    cp_workout, cp_slot = _plan_control_point(
        macro_week, templates, season)

    planned = planner.build_from(WeekPlanInput(
        season_week=current.season_week,
        week_start=current.start,
        week_end=current.end,
        targets=targets,
        slots=slots,
        weeks_to_race=0 if race_week else weeks_to_race(season, current.start),
        run_km=macro.run_km,
        easy_runs=macro.easy_runs,
        plan_id=current.plan_id,
        # Контрольная точка — одна из пробежек недели и часть её
        # километража: форма фазы считает остаток.
        reserved_km=_workout_km(cp_workout) if cp_workout else 0.0,
        reserved_runs=1 if cp_workout is not None else 0,
        reserved_slots=(cp_slot.id,) if cp_slot is not None else (),
    ))

    # Вел, плавание и ОФП — в окна, оставшиеся от пробежек.
    others, _other_slots = _plan_other_sports(
        macro, season,
        reserved={cp_slot.id} if cp_slot is not None else set(),
        occupied=_occupied_minutes(planned.assignments),
        skip_ofp=_ofp_inside_runs(
            planner, season, current.season_week, race_week),
    )

    planned = _merge_others(planned, others, season)
    if cp_workout is not None:
        planned = _merge_control_point(planned, cp_workout)

    # Недельная цель пересчитывается по итоговой неделе: перенесённые
    # тренировки тоже тренировки, а число сессий показывается клиенту.
    planned.load_target = planner.load_target_for_week(planned)

    planned.validate()
    return planned


def _slot_for(workout: Workout, by_time: dict[str, list[Slot]],
              taken: set[str]) -> Slot | None:
    """Слот для тренировки — по времени начала и виду спорта.

    None — подходящего слота нет: тренировка остаётся висяком.
    """
    if not workout.time:
        return None
    for slot in by_time.get(workout.time, []):
        if slot.id in taken:
            continue
        if slot.capacity_min < int(workout.duration_min):
            continue
        if workout.sport in slot.forbidden_sports:
            continue
        return slot
    return None


__all__ = [
    "MacroVolume",
    "build_targets",
    "is_race_week",
    "macro_from_macro_week",
    "macro_from_week",
    "plan_from_macro",
    "propose_week",
    "weeks_to_race",
]
