"""Планировщик недели: макро + правила → неделя.

Шаг 3 планировщика (см. `specs/logical/LOGICAL.md`). Логика построения
тренировочного процесса — здесь, в сервисе.

Порядок:
1. цель и объём недели из макро;
2. неделя программы по фазе и номеру — из правил методологии;
3. структура качественной сессии — по рецепту правила;
4. раскладка по слотам среды;
5. что не разложилось — висяк, решение пользователя;
6. сборка шагов; длительность тренировки = Σ шагов;
7. неделя готова к активации — активация по команде пользователя.

Правила методики — данные (`MethodologyRepo`). Движок применяет их, но не
решает, что считать.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.domain.derivations import merged_slots
from app.domain.entities import (
    Assignment,
    Athlete,
    LoadModel,
    Phase,
    Request,
    Slot,
    SlotOverride,
    Step,
    Week,
    Workout,
)
from app.domain.enums import FocusType, Sport, StepRole, TargetType, WeekStatus
from app.domain.methodology import (
    ZONE_EASY,
    ZONE_INTERVAL,
    DanielsPaces,
    MethodPlan,
    WorkoutRecipe,
    apply_week_caps,
    build_progression_steps,
    build_steps,
    format_pace,
)


@dataclass
class WeeklyTarget:
    """Недельная цель из макро: что и сколько."""

    sport: Sport
    duration_min: int
    focus: str = ""
    kind: str = "easy"
    long_min: int | None = None
    quality: dict[str, str] | None = None
    equipment_required: tuple[str, ...] = ()


@dataclass
class WorkoutTemplate:
    """Шаблон тренировки из методологии: рецепт занятия."""

    id: str
    label: str
    goal: str
    scale: str
    develops: str
    method: str
    blocks: list[dict[str, object]]


@dataclass
class WeekPlanInput:
    """Вход планировщика: всё, что нужно для сборки недели.

    `phase` и `week` — неделя программы Дэниэлса. `weeks_to_race` — сколько
    недель до старта: по этому сроку программа раскладывается по фазам.
    `run_km` — недельный километраж бега из макро: ограничения Дэниэлса
    заданы в его долях, без него предел не вычислить.
    """

    season_week: int
    week_start: date
    week_end: date
    targets: list[WeeklyTarget]
    slots: list[Slot]
    phase: int = 0
    week: int = 0
    weeks_to_race: int = 0
    run_km: float = 0.0
    # Число лёгких пробежек недели — из макро. Задаёт разбивку лёгкого
    # остатка, чтобы макро и собранная неделя называли одно число
    # тренировок.
    easy_runs: int = 0
    plan_id: str = ""
    phase_overrides: list[SlotOverride] | None = None
    week_overrides: list[SlotOverride] | None = None


@dataclass
class _PlannedSession:
    """Тренировка, готовая к сборке: запрос + рецепт (если есть)."""

    target: WeeklyTarget
    recipe: WorkoutRecipe | None = None


def _split_easy(minutes: float, runs: int) -> list[int]:
    """Лёгкий остаток недели — на `runs` пробежек, поровну.

    Правило Дэниэлса: «7 дней в неделю Л-темп». Остаток бега — это не одна
    тренировка длиной в полнедели, а несколько лёгких пробежек.

    Число пробежек задаёт **макро**: без него макро и собранная неделя
    называют разное число тренировок. Без макро — одна пробежка.
    """
    if minutes <= 0:
        return []
    if runs <= 0:
        runs = 1
    if runs == 1:
        return [int(round(minutes))]
    each = int(minutes // runs)
    parts = [each] * (runs - 1)
    parts.append(int(minutes - each * (runs - 1)))
    return [p for p in parts if p > 0]


def _easy_runs_by_slots(minutes: float, slots: list[Slot],
                        taken: set[str]) -> int:
    """Число лёгких пробежек — по свободным окнам.

    Запасной путь для плана без макро: макро задаёт число пробежек само.
    """
    count = 0
    left = minutes
    for slot in slots:
        if left <= 0:
            break
        if slot.id in taken or Sport.RUN in slot.forbidden_sports:
            continue
        take = min(slot.capacity_min, left)
        if take <= 0:
            continue
        left -= take
        count += 1
    return max(count, 1)


class WeekPlanner:
    """Собирает неделю из макро, профиля, среды и правил методики.

    Движок методики: применяет правила, не решает, что считать. Правила
    приходят из `MethodologyRepo`.
    """

    def __init__(
        self,
        templates: dict[str, WorkoutTemplate],
        load_model: LoadModel,
        athlete: Athlete,
        paces: DanielsPaces | None = None,
        plan: MethodPlan | None = None,
    ) -> None:
        self._templates = templates
        self._load_model = load_model
        self._athlete = athlete
        self._paces = paces or DanielsPaces()
        self._plan = plan or MethodPlan()

    # ---------------------------------------------------------- сборка недели

    def build(self, season_week: int, week_start: date, week_end: date,
              targets: list[WeeklyTarget], slots: list[Slot],
              phase_overrides: list[SlotOverride] | None = None,
              week_overrides: list[SlotOverride] | None = None) -> Week:
        """Собрать неделю: цель → запросы → размещения → тренировки → шаги."""
        return self.build_from(WeekPlanInput(
            season_week=season_week,
            week_start=week_start,
            week_end=week_end,
            targets=targets,
            slots=slots,
            phase_overrides=phase_overrides,
            week_overrides=week_overrides,
        ))

    def build_from(self, data: WeekPlanInput) -> Week:
        """Собрать неделю по полному входу.

        Разница с `build`: известны неделя программы и срок до старта, значит
        правила методики применяются, а не только макро.
        """
        merged = merged_slots(
            data.slots,
            data.phase_overrides or [],
            data.week_overrides or [],
        )

        sessions = self._plan_sessions(data, merged)

        requests: list[Request] = []
        assignments: list[Assignment] = []
        unplaced: list[Request] = []
        workouts: list[Workout] = []

        for index, session in enumerate(sessions):
            target = session.target
            request = Request(
                id=f"r{data.season_week}-{index + 1}",
                sport=target.sport,
                kind=target.kind,
                focus=target.focus,
                duration_min=target.duration_min,
                equipment_required=target.equipment_required,
            )
            requests.append(request)

            slot = self._pick_slot(merged, request, assignments)
            if slot is None:
                # не разложилось — висяк, решение пользователя
                unplaced.append(request)
                workouts.append(self._build_workout(request, session, None))
                continue

            assignments.append(
                Assignment(
                    request_id=request.id,
                    slot_id=slot.id,
                    start=slot.start,
                    duration_min=request.duration_min,
                    equipment_ids=slot.equipment_ids,
                )
            )
            workouts.append(self._build_workout(request, session, slot))

        week = Week(
            id=f"W{data.season_week}",
            plan_id=data.plan_id,
            season_week=data.season_week,
            start=data.week_start,
            end=data.week_end,
            status=WeekStatus.PROPOSED,
            focus=data.targets[0].focus if data.targets else None,
            load_target=self._load_target(data.targets, data.run_km),
            requests=requests,
            assignments=assignments,
            unplaced=unplaced,
            workouts=workouts,
        )
        # Сессии пересчитываем по собранным тренировкам: одна цель может
        # дать несколько тренировок, а висяк — ни одной.
        week.load_target = self.load_target_for_week(week)
        week.validate()
        return week

    # ---------------------------------------------------------- правила

    def _recipes_for(self, data: WeekPlanInput) -> list[WorkoutRecipe]:
        """Рецепты недели программы.

        Номер недели программы берётся из срока до старта: программа
        раскладывается под срок по фазам. Если недель программы не хватает —
        рецептов нет, и неделя собирается только из макро.

        Для лишней недели (срок больше базы) план берётся из хвоста своей
        фазы: неделя 25 в фазе II использует план недели 11.
        """
        if not self._plan.weeks:
            return []
        phase = data.phase
        week = data.week
        plan_week = week
        if data.weeks_to_race:
            mapped = self._plan.plan_week(data.weeks_to_race, data.season_week - 1)
            if mapped is not None:
                phase, week, plan_week = mapped
        entry = self._plan.week(phase, plan_week)
        if entry is None:
            return []
        return list(entry.recipes)

    def _scaled_recipes(self, data: WeekPlanInput) -> list[WorkoutRecipe]:
        """Рецепты недели, подчинённые ограничениям по объёму.

        «R-темп — не более 5 % недельного километража», «I-темп — 8 % или
        10 км, что меньше». Предел задан на неделю целиком, поэтому считается
        сумма по зоне за неделю: если она выше предела, работа урезается.

        Ограничения берутся из недели **плана**: у лишней недели план из
        хвоста фазы, значит и пределы её.
        """
        recipes = self._recipes_for(data)
        if not recipes or data.run_km <= 0:
            return recipes

        entry = self._plan.week(*self._plan_position(data))
        if entry is None or not entry.caps:
            return recipes
        return apply_week_caps(recipes, entry.caps, data.run_km)

    def _program_position(self, data: WeekPlanInput) -> tuple[int, int]:
        """Неделя программы для недели сезона."""
        if data.weeks_to_race:
            mapped = self._plan.program_week(data.weeks_to_race, data.season_week - 1)
            if mapped is not None:
                return mapped
        return (data.phase, data.week)

    def _plan_position(self, data: WeekPlanInput) -> tuple[int, int]:
        """Неделя **плана** для недели сезона: фаза и неделя, чей план берётся.

        Для лишней недели это неделя из хвоста фазы.
        """
        if data.weeks_to_race:
            mapped = self._plan.plan_week(data.weeks_to_race, data.season_week - 1)
            if mapped is not None:
                phase, _program_week, plan_week = mapped
                return (phase, plan_week)
        return (data.phase, data.week)

    def _plan_sessions(self, data: WeekPlanInput,
                       slots: list[Slot] | None = None) -> list[_PlannedSession]:
        """Тренировки недели: качество из правил, остальное — из макро.

        Порядок: сначала качественная работа (её кладут в лучшие слоты),
        потом длинный бег, потом лёгкий остаток.
        """
        recipes = self._scaled_recipes(data)
        pace_by_zone = self._paces.pace_by_zone(self._athlete.vdot)
        available = slots if slots is not None else list(data.slots)

        run_targets = [t for t in data.targets if t.sport is Sport.RUN]
        other_targets = [t for t in data.targets if t.sport is not Sport.RUN]
        run_minutes = sum(t.duration_min for t in run_targets)

        sessions: list[_PlannedSession] = []

        used_minutes = 0.0
        for recipe in recipes:
            if recipe.kind == "RACE":
                # Гонка — событие недели, а не тренировка: её дистанция и
                # время зависят от конкретной гонки, а правила их не задают.
                # В план недели она не входит: план — это тренировки, а гонка
                # живёт в сезоне (календарь гонок).
                continue
            if not recipe.is_quality:
                continue
            # Длительность — по фактическим шагам, а не по рецепту: шаги
            # округлены, и разница иначе уходит в лёгкую часть недели.
            steps = self._recipe_steps(recipe, pace_by_zone)
            duration = sum(step.duration_min for step in steps)
            if duration <= 0:
                continue
            # Запрос — в целых минутах (длительность запроса — целое число).
            # Округляем здесь, чтобы остаток недели считался от того же
            # числа: иначе сумма целей разойдётся с объёмом недели.
            request_minutes = int(round(duration))
            used_minutes += request_minutes
            sessions.append(_PlannedSession(
                target=WeeklyTarget(
                    sport=Sport.RUN,
                    duration_min=request_minutes,
                    focus=recipe.label,
                    kind=recipe.kind.lower(),
                    quality={"recipe": recipe.label},
                ),
                recipe=recipe,
            ))

        for target in run_targets:
            if not target.long_min:
                continue
            used_minutes += target.long_min
            sessions.append(_PlannedSession(
                target=WeeklyTarget(
                    sport=target.sport,
                    duration_min=target.long_min,
                    focus=target.focus,
                    kind="long",
                ),
            ))

        for target in other_targets:
            sessions.append(_PlannedSession(target=target))

        # Лёгкий остаток — на столько пробежек, сколько задаёт макро.
        #
        # Пробежки раскладываются **последними**: окно занимает одна
        # тренировка, и качественная работа с длинным бегом и прочие виды
        # спорта берут свои окна первыми. Число пробежек — из макро
        # (`easy_runs`): иначе макро и собранная неделя называют разное
        # число тренировок.
        remaining = max(run_minutes - used_minutes, 0)
        if remaining > 0:
            runs = data.easy_runs
            if runs <= 0:
                runs = _easy_runs_by_slots(remaining, available, set())
            focus = data.targets[0].focus if data.targets else ""
            for minutes in _split_easy(remaining, runs):
                sessions.append(_PlannedSession(
                    target=WeeklyTarget(
                        sport=Sport.RUN,
                        duration_min=int(minutes),
                        focus=focus,
                        kind="easy",
                    ),
                ))

        return sessions

    def _recipe_steps(self, recipe: WorkoutRecipe,
                     pace_by_zone: dict[str, float]) -> list[Step]:
        """Шаги тренировки по рецепту.

        Бег с ускорением — по прогрессии темпа, остальное — по рецепту.

        Сумма длительностей шагов выравнивается до целого числа минут:
        инвариант I5 требует, чтобы длительность тренировки равнялась сумме
        шагов, а недельный объём — целые минуты. Без выравнивания
        накопленная погрешность съедает часть недели.
        """
        if recipe.kind == "ACC" and recipe.distance_m > 0:
            return build_progression_steps(
                recipe, pace_by_zone, self._athlete,
                recipe.distance_m,
                recipe.pace_growth_sec_per_400m,
                recipe.final_zone or ZONE_INTERVAL,
            )
        steps = build_steps(recipe, pace_by_zone, self._athlete)
        return _align_to_whole_minutes(steps)

    def _recipe_duration_min(self, recipe: WorkoutRecipe,
                             pace_by_zone: dict[str, float]) -> float:
        """Длительность тренировки по рецепту — по темпам зон."""
        steps = self._recipe_steps(recipe, pace_by_zone)
        return sum(step.duration_min for step in steps)

    # ---------------------------------------------------------- внутреннее

    def _pick_slot(
        self,
        slots: list[Slot],
        request: Request,
        taken: list[Assignment],
    ) -> Slot | None:
        """Подобрать слот: помещается по времени, нет конфликта, доступно оборудование.

        Из подходящих берётся **самый тесный** — тот, в котором тренировка
        оставляет меньше всего запаса. Первое попавшееся окно отдавало
        широкое окно короткой тренировке, и длинный бег уходил в висяк,
        хотя для него было другое окно: тренировка в 30 минут занимает
        окно в 30 минут, а не в 90.
        """
        used = {a.slot_id for a in taken}
        best: Slot | None = None
        for slot in slots:
            if slot.id in used:
                continue
            if slot.capacity_min < request.duration_min:
                continue
            if request.sport in slot.forbidden_sports:
                continue
            needed = set(request.equipment_required)
            if needed and not needed.issubset(set(slot.equipment_ids)):
                continue
            if best is None or slot.capacity_min < best.capacity_min:
                best = slot
        return best

    def _build_workout(self, request: Request, session: _PlannedSession,
                       slot: Slot | None) -> Workout:
        """Тренировка из запроса: шаги по рецепту методики.

        Время — из слота: клиент показывает время тренировки, а без
        размещения его взять неоткуда.
        """
        steps = self._build_steps(request, session)
        target = session.target
        return Workout(
            id=f"w-{request.id}",
            request_id=request.id,
            sport=request.sport,
            kind=request.kind,
            focus=request.focus,
            time=slot.start if slot else None,
            steps=steps,
            duration_min=sum(s.duration_min for s in steps),
            rationale=f"{target.kind} · {target.focus}" if target.focus else target.kind,
        )

    def _build_steps(self, request: Request, session: _PlannedSession) -> list[Step]:
        """Шаги тренировки.

        Качественная работа — по рецепту правила. Бег с ускорением — по
        прогрессии темпа. Остальное — лёгкий бег: один шаг в лёгкой зоне.
        """
        pace_by_zone = self._paces.pace_by_zone(self._athlete.vdot)

        if session.recipe is not None:
            return self._recipe_steps(session.recipe, pace_by_zone)

        pace = pace_by_zone.get(ZONE_EASY)
        focus_value: dict[str, object] = {"zone": "Z2"}
        if pace:
            focus_value["pace_min_per_km"] = format_pace(pace)
        return [
            Step(
                id=f"{request.id}-work",
                role=StepRole.WORK,
                sport=request.sport,
                target_type=TargetType.TIME,
                target_value=float(request.duration_min),
                focus=FocusType.HR,
                focus_value=focus_value,
                duration_min=float(request.duration_min),
            )
        ]

    def _load_target(self, targets: list[WeeklyTarget], run_km: float) -> dict[str, float]:
        """Недельная цель: часы, число сессий, километраж бега.

        Ключи те же, что у импорта из пайплайна (`hours`, `sessions`,
        `distance_m`): от них зависят и прогресс недели «N из M», и клиент.
        """
        minutes = float(sum(t.duration_min for t in targets))
        return {
            "hours": minutes / 60.0,
            "minutes": minutes,
            "sessions": float(len(targets)),
            "distance_m": float(run_km) * 1000.0,
        }

    def load_target_for_week(self, week: Week) -> dict[str, float]:
        """Недельная цель по собранной неделе.

        Число сессий — по фактическим тренировкам, а не по числу целей:
        одна цель может дать несколько тренировок (качество, длинный,
        лёгкий остаток), а висяки — ноль.
        """
        minutes = float(sum(w.duration_min for w in week.workouts))
        sessions = float(len(week.workouts))
        distance_m = float(week.load_target.get("distance_m", 0.0))
        return {
            "hours": minutes / 60.0,
            "minutes": minutes,
            "sessions": sessions,
            "distance_m": distance_m,
        }


def _align_to_whole_minutes(steps: list[Step]) -> list[Step]:
    """Выровнять сумму длительностей шагов до целого числа минут.

    Погрешность округления шагов (десятые доли минуты) уходит в последний
    шаг: сумма становится целым числом минут, а инвариант «длительность
    тренировки = Σ шагов» сохраняется.
    """
    if not steps:
        return steps
    total = sum(step.duration_min for step in steps)
    target = round(total)
    if abs(total - target) < 0.001:
        return steps
    last = steps[-1]
    # Step — неизменяемый dataclass: последний шаг заменяется новым.
    aligned = replace(
        last,
        duration_min=round(last.duration_min + (target - total), 2),
    )
    return [*steps[:-1], aligned]


def phase_targets(phase: Phase, macro: dict[str, float]) -> list[WeeklyTarget]:
    """Недельные цели из макро фазы.

    `macro` — недельные цели из макро-плана: ключ — вид спорта, значение —
    минуты.
    """
    targets: list[WeeklyTarget] = []
    for sport_name, minutes in macro.items():
        try:
            sport = Sport(sport_name)
        except ValueError:
            continue
        targets.append(
            WeeklyTarget(
                sport=sport,
                duration_min=int(minutes),
                focus=phase.focus or "",
            )
        )
    return targets
