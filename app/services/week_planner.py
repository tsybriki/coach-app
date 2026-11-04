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
from typing import Any

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
    PhaseShape,
    WorkoutRecipe,
    apply_week_caps,
    athlete_zone_for,
    build_ofp_steps,
    build_progression_steps,
    build_steps,
    build_stride_steps,
    format_pace,
)
from app.domain.session_name import easy_pace_sec_per_km, session_name

# Потолок длинного бега: «25 % недельного километража или 1,5 ч — что
# меньше» (правило Дэниэлса). Без потолка длинный пробежек растёт с
# километражом недели и перестаёт быть длинным пробежком.
LONG_MAX_MIN = 90


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

    `reserved_km` и `reserved_runs` — сколько километражей и пробежек
    недели уже занято (контрольная точка занимает и километраж, и слот
    пробежки). Форма фазы считает остаток.
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
    # остатка, чтобы макро и собранная неделя называют одно число
    # тренировок.
    easy_runs: int = 0
    plan_id: str = ""
    phase_overrides: list[SlotOverride] | None = None
    week_overrides: list[SlotOverride] | None = None
    # Километраж и число пробежек, занятые контрольной точкой.
    reserved_km: float = 0.0
    reserved_runs: int = 0
    # Окна, занятые контрольной точкой: их нельзя отдавать под бег.
    reserved_slots: tuple[str, ...] = ()


@dataclass
class _PlannedSession:
    """Тренировка, готовая к сборке: запрос + рецепт (если есть)."""

    target: WeeklyTarget
    recipe: WorkoutRecipe | None = None
    # Готовые шаги тренировки. Заданы, когда структура пришла из формы
    # фазы (отрезки и ОФП внутри пробежки), а не из рецепта.
    steps: list[Step] | None = None
    # Основа названия тренировки. Если не задана — название собирается
    # из вида работы и состава шагов (см. `app/domain/session_name.py`).
    base_name: str | None = None


def shift_time(start: str, offset_minutes: int) -> str:
    """Сдвинуть время начала окна на занятые минуты.

    Вторую тренировку окна ставим сразу после первой: «18:45 + 60 мин»
    — это «19:45», а не снова «18:45».
    """
    if offset_minutes <= 0:
        return start
    try:
        hours, _, minutes = start.partition(":")
        total = int(hours) * 60 + int(minutes) + offset_minutes
        total %= 24 * 60
        return f"{total // 60:02d}:{total % 60:02d}"
    except ValueError:
        return start


def _split_easy_km(kilometers: float, runs: int) -> list[float]:
    """Лёгкий километраж недели — на `runs` пробежек, поровну.

    Километраж, а не минуты: длина пробежки задаёт объём, а время
    считается по темпу зоны.
    """
    if kilometers <= 0:
        return []
    if runs <= 0:
        runs = 1
    if runs == 1:
        return [kilometers]
    each = kilometers / runs
    return [each] * runs


def _spread(count: int, total: int) -> set[int]:
    """Индексы `count` пробежек из `total` — равномерно по неделе.

    Добавки (отрезки, ОФП) не должны слипаться в начале: иначе половина
    недели тяжелее, а вторая — нет. Раскладываем через равные интервалы.
    """
    if count <= 0 or total <= 0:
        return set()
    count = min(count, total)
    if count == total:
        return set(range(total))
    step = total / count
    return {min(total - 1, int(index * step)) for index in range(count)}


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
        """
        Собрать неделю по полному входу.

        Разница с `build`: известны неделя программы и срок до старта, значит
        правила методики применяются, а не только макро.

        **Размещения нет.** Все тренировки недели становятся висяками, и
        пользователь раскладывает их по дням руками.

        Почему так: автоматическая привязка работает плохо — она
        раскладывает тренировки по кругу дней, не глядя на то, что в
        этом окне вообще можно делать. Вел вставал во вторник, где
        велосипеда нет, а длинный бег — в среду, где по семейному
        тайму интенсивное запрещено. Планировщик не знает о расписании
        семьи, а пользователь знает.

        Что остаётся от планировщика: **какие** тренировки нужны
        (объём, качественная работа, длинный бег, вел, плавание) и
        сколько они длятся. Куда они встанут — решение пользователя.
        """
        merged = merged_slots(
            data.slots,
            data.phase_overrides or [],
            data.week_overrides or [],
        )

        sessions = self._plan_sessions(data, merged)

        requests: list[Request] = []
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
            # Висяк: время выбирает пользователь.
            unplaced.append(request)
            workout = self._build_workout(request, session, None)
            # Фокус запроса — из названия тренировки, а не из фокуса цели.
            #
            # Фокус цели («Лёгкий бег + отрезки») не знает, есть ли в
            # тренировке ОФП: он задаётся формой фазы, а не целью. Имя
            # тренировки собирается из состава шагов, и висяк должен
            # называться так же, как тренировка, — иначе в списке
            # непривязанных одно название, а в самой тренировке другое.
            request.focus = workout.focus
            workouts.append(workout)

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
            assignments=[],
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
            # При форме фазы длинный бег собирает сама форма: иначе в
            # неделе окажется две длинные пробежки — длинная из макро и
            # длинная из правила Дэниэлса.
            if self._phase_shape(data)[0] is not None:
                continue
            used_minutes += target.long_min
            sessions.append(_PlannedSession(
                target=WeeklyTarget(
                    sport=target.sport,
                    duration_min=target.long_min,
                    focus=target.focus or "Длинный бег",
                    kind="long",
                ),
            ))

        for target in other_targets:
            sessions.append(_PlannedSession(target=target))

        # Форма фазы — правило Дэниэлса о числе пробежек и их структуре.
        # Если форма есть, она главнее: «7 дней в неделю Л-темп» — это
        # семь пробежек, а не «сколько останется после деления».
        #
        # Форма задаёт и длинный бег: отдельный «длинный» из макро при
        # форме был бы второй длинной пробежкой в неделе.
        shape, _program_week = self._phase_shape(data)
        shape_sessions = self._shape_runs(data)
        if shape_sessions:
            sessions.extend(shape_sessions)
            used_minutes += sum(
                s.target.duration_min for s in shape_sessions)

        # Лёгкий остаток — на столько пробежек, сколько задаёт макро.
        #
        # Пробежки раскладываются **последними**: окно занимает одна
        # тренировка, и качественная работа с длинным бегом и прочие виды
        # спорта берут свои окна первыми. Число пробежек — из макро
        # (`easy_runs`): иначе макро и собранная неделя называют разное
        # число тренировок.
        #
        # Если форма фазы собрала пробежки сама — остаток не делится
        # ещё раз: иначе неделя получает восьмую, девятую пробежку.
        remaining = max(run_minutes - used_minutes, 0)
        if remaining > 0 and not shape_sessions:
            runs = data.easy_runs
            if runs <= 0:
                runs = _easy_runs_by_slots(remaining, available, set())
            # Описание лёгкой пробежки — её собственное («Лёгкий бег»),
            # а не цель недели: карточка пробежки не должна говорить,
            # что она проверяет форму на контрольной точке.
            focus = data.targets[0].focus if data.targets else ""
            focus = focus or "Лёгкий бег"
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

    # ---------------------------------------------------------- форма фазы

    def phase_shape_for(self, season_week: int,
                        weeks_to_race: int) -> PhaseShape | None:
        """Форма фазы для недели сезона — по горизонту до старта.

        Фаза программы определяется тем же расписанием, что и неделя
        программы: макро и планировщик обязаны считать одно.
        """
        if not weeks_to_race:
            return None
        located = self._plan.program_week(weeks_to_race, season_week - 1)
        if located is None:
            return None
        phase, _program_week = located
        return self._plan.shape_for(phase)


    def _phase_shape(self, data: WeekPlanInput) -> tuple[PhaseShape | None, int]:
        """Форма фазы и номер недели программы.

        Форма — из правил Дэниэлса: сколько пробежек в неделе, с какими
        отрезками и сколько ОФП. Недельный километраж — из макро-плана
        сезона, форма его только ограничивает.
        """
        phase, program_week = self._program_position(data)
        shape = self._plan.shape_for(phase)
        if shape is None:
            return None, program_week
        return shape, program_week

    def _shape_runs(self, data: WeekPlanInput) -> list[_PlannedSession]:
        """Пробежки недели по форме фазы.

        Правило Дэниэлса для фазы I: 7 тренировок в неделю в лёгкой
        зоне; к четырём из них (не к длинной) — короткие быстрые
        отрезки; к трём — ОФП в конце.

        Каждая пробежка — отдельная тренировка со своей структурой:
        отрезки и ОФП идут **внутри** пробежки, а не отдельными
        тренировками. Иначе неделя показывает 20 тренировок вместо семи.
        """
        shape, program_week = self._phase_shape(data)
        if shape is None or shape.runs_per_week <= 0:
            return []

        pace_by_zone = self._paces.pace_by_zone(self._athlete.vdot)
        total_runs = shape.runs_per_week
        # Контрольная точка занимает одну пробежку недели.
        total_runs = max(total_runs - data.reserved_runs, 1)

        has_long = shape.has_long(program_week)
        long_min = self._shape_long_min(data, shape)
        # Длинная пробежка — одна из семи, и **без отрезков**.
        long_is_run = has_long and long_min > 0

        # Отрезки — **в каждой** из четырёх пробежек, по 6-8 штук.
        # «6-8 коротких быстрых отрезков в неделю по меньшей мере к
        # четырём Л-забегам» читается так: к четырём пробежкам добавить
        # по 6-8 отрезков, а не раздать 6-8 отрезков на всю неделю.
        stride_runs = shape.stride_runs
        if long_is_run:
            stride_runs = min(stride_runs, max(total_runs - 1, 0))
        stride_runs = min(stride_runs, total_runs)
        # ОФП — к трём из семи.
        ofp_runs = min(shape.ofp_runs, total_runs)
        # Длинная не получает ОФП: «в конце пробежки» — к лёгким.
        if long_is_run and ofp_runs > 0:
            ofp_runs = min(ofp_runs, max(total_runs - 1, 0))

        # Километраж недели — из макро, ограниченный формой фазы.
        run_km = shape.clamp_km(data.run_km)
        easy_runs = max(total_runs - (1 if long_is_run else 0), 1)
        # Длинная пробежка — 25 % недельного километража или 1,5 ч, что
        # меньше.
        long_km = 0.0
        if long_is_run:
            long_km = min(run_km * 0.25, run_km)
        # Лёгкий километраж — без длинной и без контрольной точки.
        easy_km = max(run_km - long_km - data.reserved_km, 0.0)

        # Пробежки с отрезками делятся на две группы: более короткие и
        # более длинные. В более коротких — 8 отрезков, в более длинных —
        # 6 («в более длинной тренировке 6, в более короткие 8»).
        # Порядок по неделе: первая половина несущих отрезки пробежек —
        # короткие, вторая — длинные.
        stride_slots = _spread(stride_runs, easy_runs)
        ofp_slots = _spread(ofp_runs, easy_runs)
        ordered_stride = sorted(stride_slots)
        half = len(ordered_stride) // 2
        short_strides = set(ordered_stride[:half])

        # Объём отрезков — часть недельного километража: каждый отрезок
        # это 100 м работы плюс 100 м отдыха бегом.
        stride_km = 0.0
        reps_by_index: dict[int, int] = {}
        if shape.has_strides(program_week) and stride_runs > 0:
            for index in ordered_stride:
                reps = (shape.stride_reps_max if index in short_strides
                        else shape.stride_reps_min)
                reps_by_index[index] = reps
                stride_km += reps * (shape.stride_distance_m
                                     + shape.stride_recovery_m) / 1000.0

        # База для лёгких пробежек — без отрезков: иначе недельный
        # объём выходит за потолок формы («55-57, но не больше»).
        base_easy_km = max(easy_km - stride_km, 0.0)
        # Две длины: короткие пробежки короче, длинные — длиннее.
        weights = [1.0] * easy_runs
        for index in ordered_stride:
            weights[index] = 0.9 if index in short_strides else 1.1
        total_weight = sum(weights) or 1.0
        parts = [base_easy_km * weight / total_weight for weight in weights]

        sessions: list[_PlannedSession] = []

        for index, km in enumerate(parts):
            with_strides = index in stride_slots
            with_ofp = index in ofp_slots
            steps = self._easy_run_steps(
                km, pace_by_zone, shape,
                with_strides=with_strides,
                with_ofp=with_ofp,
                program_week=program_week,
                stride_reps=reps_by_index.get(index, 0),
            )
            if not steps:
                continue
            minutes = int(round(sum(step.duration_min for step in steps)))
            sessions.append(_PlannedSession(
                target=WeeklyTarget(
                    sport=Sport.RUN,
                    duration_min=minutes,
                    focus="Лёгкий бег" + (" + отрезки" if with_strides else ""),
                    kind="easy",
                ),
                steps=steps,
            ))

        if long_is_run:
            long_steps = self._easy_run_steps(
                long_km, pace_by_zone, shape,
                with_strides=False, with_ofp=False,
                program_week=program_week,
            )
            long_minutes = int(round(sum(step.duration_min for step in long_steps)))
            sessions.append(_PlannedSession(
                target=WeeklyTarget(
                    sport=Sport.RUN,
                    duration_min=long_minutes,
                    focus="Длинный бег",
                    kind="long",
                ),
                steps=long_steps,
            ))
        return sessions

    def _shape_long_min(self, data: WeekPlanInput,
                        shape: PhaseShape) -> int:
        """Длинный бег — 25 % недельного километража или 1,5 ч, что меньше."""
        run_km = shape.clamp_km(data.run_km)
        return int(min(run_km * 0.25, LONG_MAX_MIN))

    def _easy_run_steps(
        self,
        km: float,
        pace_by_zone: dict[str, float],
        shape: PhaseShape,
        with_strides: bool,
        with_ofp: bool,
        program_week: int,
        stride_reps: int = 0,
    ) -> list[Step]:
        """Шаги пробежки: лёгкий бег + отрезки + ОФП в конце."""
        steps: list[Step] = []
        if km > 0:
            easy_pace = easy_pace_sec_per_km(pace_by_zone)
            if easy_pace:
                # Километраж — в километрах, темп — в секундах на км.
                minutes = km * easy_pace / 60.0
                steps.append(Step(
                    id="run-easy",
                    role=StepRole.WORK,
                    sport=Sport.RUN,
                    target_type=TargetType.DISTANCE,
                    target_value=round(km * 1000.0, 1),
                    focus=FocusType.HR,
                    focus_value={
                        "zone": athlete_zone_for(ZONE_EASY, self._athlete) or "Z2",
                        "pace_min_per_km": format_pace(easy_pace),
                    },
                    duration_min=round(minutes, 2),
                ))
        if with_strides and shape.has_strides(program_week) and stride_reps > 0:
            stride_steps = build_stride_steps(
                shape, pace_by_zone, self._athlete, stride_reps)
            for step in stride_steps:
                steps.append(step)
        if with_ofp and shape.ofp_minutes > 0:
            for step in build_ofp_steps(shape.ofp_minutes, self._athlete):
                steps.append(step)
        return steps

    # ---------------------------------------------------------- внутреннее

    def _pick_slot(
        self,
        slots: list[Slot],
        request: Request,
        taken: list[Assignment],
    ) -> tuple[Slot | None, str | None]:
        """Подобрать слот и время начала.

        Помещается по времени, нет конфликта, доступно оборудование.

        Из подходящих берётся **самый тесный** — тот, в котором тренировка
        оставляет меньше всего запаса. Первое попавшееся окно отдавало
        широкое окно короткой тренировке, и длинный бег уходил в висяк,
        хотя для него было другое окно: тренировка в 30 минут занимает
        окно в 30 минут, а не в 90.

        Окно может вместить **две тренировки**: «7 дней в неделю
        Л-темп» плюс вел и плавание — это девять тренировок на семь дней
        и восемь окон. Вторую тренировку окна ставим сразу после первой:
        время начала считается от занятого, а не от начала окна.
        """
        used_by_slot: dict[str, int] = {}
        for assignment in taken:
            used_by_slot[assignment.slot_id] = (
                used_by_slot.get(assignment.slot_id, 0)
                + int(assignment.duration_min)
            )

        best: Slot | None = None
        best_free = 0
        for slot in slots:
            free = slot.capacity_min - used_by_slot.get(slot.id, 0)
            if free < request.duration_min:
                continue
            if request.sport in slot.forbidden_sports:
                continue
            needed = set(request.equipment_required)
            if needed and not needed.issubset(set(slot.equipment_ids)):
                continue
            if best is None or free < best_free:
                best = slot
                best_free = free
        if best is None:
            return None, None
        start = shift_time(best.start, used_by_slot.get(best.id, 0))
        return best, start

    def _place_tight(
        self,
        sessions: list[_PlannedSession],
        slots: list[Slot],
    ) -> dict[int, tuple[Slot, str]]:
        """Разместить тренировки в самое тесное подходящее окно.

        Тренировка в 30 минут занимает окно в 30 минут, а не в 90: иначе
        длинная тренировка уходит в висяк, хотя для неё есть другое
        окно. Каждое окно занимает одна тренировка.
        """
        used: set[str] = set()
        placed: dict[int, tuple[Slot, str]] = {}

        for index, session in enumerate(sessions):
            target = session.target
            best: Slot | None = None
            for slot in slots:
                if slot.id in used:
                    continue
                if slot.capacity_min < target.duration_min:
                    continue
                if target.sport in slot.forbidden_sports:
                    continue
                needed = set(target.equipment_required)
                if needed and not needed.issubset(set(slot.equipment_ids)):
                    continue
                if best is None or slot.capacity_min < best.capacity_min:
                    best = slot
            if best is None:
                continue
            used.add(best.id)
            placed[index] = (best, best.start)
        return placed

    def _place_sessions(
        self,
        sessions: list[_PlannedSession],
        slots: list[Slot],
        start_day: int = 0,
        reserved_slots: tuple[str, ...] = (),
    ) -> dict[int, tuple[Slot, str]]:
        """Разместить тренировки по окнам.

        Пробежки — **по кругу дней недели**, начиная с первого дня
        недели: правило Дэниэлса требует «7 дней в неделю Л-темп», то
        есть пробежка в каждый день. Из семи дней недели в среде есть
        восемь окон плюс вел и плавание, поэтому одно окно вмещает две
        тренировки (утром пробежка, вечером вел), а вторую ставим сразу
        после первой.

        Остальные виды спорта — после пробежек, в самое вместительное
        из оставшихся окон: их объём известен точно, а бег забирает
        остаток.
        """
        used_by_slot: dict[str, int] = {}
        placed: dict[int, tuple[Slot, str]] = {}

        def occupy(slot: Slot, minutes: int) -> None:
            used_by_slot[slot.id] = used_by_slot.get(slot.id, 0) + minutes

        def fits(slot: Slot, sport: Sport, minutes: int,
                 equipment: tuple[str, ...]) -> bool:
            free = slot.capacity_min - used_by_slot.get(slot.id, 0)
            if free < minutes:
                return False
            if sport in slot.forbidden_sports:
                return False
            needed = set(equipment)
            return not needed or needed.issubset(set(slot.equipment_ids))

        runs = [index for index, session in enumerate(sessions)
                if session.target.sport is Sport.RUN]
        others = [index for index, session in enumerate(sessions)
                  if session.target.sport is not Sport.RUN]

        # Пробежки: от длинной к короткой, по кругу дней.
        # Слоты нумеруют дни как 0 — воскресенье, а `date.weekday()`
        # считает 0 — понедельник. Переводим в нумерацию слотов.
        start_slot_day = (start_day + 1) % 7
        day_order = [(start_slot_day + offset) % 7 for offset in range(7)]
        cursor = 0
        for index in sorted(
            runs,
            key=lambda i: (-sessions[i].target.duration_min, i),
        ):
            target = sessions[index].target
            chosen: Slot | None = None
            chosen_day = -1
            for offset in range(len(day_order)):
                position = (cursor + offset) % len(day_order)
                day = day_order[position]
                candidates = [
                    slot for slot in slots
                    if slot.day == day
                    and slot.id not in reserved_slots
                    and fits(slot, target.sport, target.duration_min,
                             target.equipment_required)
                ]
                if not candidates:
                    continue
                chosen = max(candidates, key=lambda s: s.capacity_min)
                chosen_day = position
                break
            if chosen is None or chosen_day < 0:
                continue
            occupy(chosen, target.duration_min)
            placed[index] = (
                chosen,
                shift_time(chosen.start,
                            used_by_slot[chosen.id] - target.duration_min),
            )
            cursor = (chosen_day + 1) % len(day_order)

        # Остальные виды спорта — в самое вместительное из оставшихся.
        for index in sorted(
            others,
            key=lambda i: (-sessions[i].target.duration_min, i),
        ):
            target = sessions[index].target
            candidates = [
                slot for slot in slots
                if slot.id not in reserved_slots
                and fits(slot, target.sport, target.duration_min,
                         target.equipment_required)
            ]
            if not candidates:
                continue
            chosen = max(candidates, key=lambda s: s.capacity_min)
            occupy(chosen, target.duration_min)
            placed[index] = (
                chosen,
                shift_time(chosen.start,
                            used_by_slot[chosen.id] - target.duration_min),
            )
        return placed

    def _build_workout(self, request: Request, session: _PlannedSession,
                       slot: Slot | None,
                       start: str | None = None) -> Workout:
        """
        Тренировка из запроса: шаги по рецепту методики.

        Время — из слота: клиент показывает время тренировки, а без
        размещения его взять неоткуда.

        День недели — тоже из слота. Без него карточка не знает, какой
        это день: тренировка без дня уезжает в конец списка, и неделя
        читается как «понедельник без названия, а потом длинный бег».
        """
        steps = self._build_steps(request, session)
        target = session.target
        objective: dict[str, Any] = {}
        if slot is not None:
            objective["day"] = slot.day
            objective["slot_id"] = slot.id
        # Название тренировки — из её состава, а не из фокуса запроса.
        # Фокус недели копировался в каждую тренировку, и все пробежки
        # недели назывались одинаково: отличить лёгкую от длинной было
        # нельзя, а «Длинный бег + отрезки» от «Лёгкого бега» — тем
        # более.
        name = session_name(request.kind, request.sport, steps,
                            base=session.base_name)
        objective["name"] = name
        # Длительность карточки — та же, что и внутри тренировки.
        # Карточка показывает сумму шагов, и шаги — источник истины:
        # расхождение между «43 мин» на карточке и «1 ч 21 мин» внутри
        # означало, что внутри считают не то же, что показывают.
        duration = sum(s.duration_min for s in steps)
        # «Зачем» — тоже из названия. Фокус цели («Лёгкий бег + отрезки»)
        # не знает, что в тренировке есть ОФП, и в «зачем» расходился с
        # названием: «Лёгкий бег + отрезки + ОФП» сверху и «easy · Лёгкий
        # бег + отрезки» внизу.
        rationale = name if name else (target.focus or target.kind)
        return Workout(
            id=f"w-{request.id}",
            request_id=request.id,
            sport=request.sport,
            kind=request.kind,
            focus=name,
            objective=objective,
            time=start or (slot.start if slot else None),
            steps=steps,
            duration_min=duration,
            rationale=rationale,
        )

    def _build_steps(self, request: Request, session: _PlannedSession) -> list[Step]:
        """Шаги тренировки.

        Качественная работа — по рецепту правила. Бег с ускорением — по
        прогрессии темпа. Остальное — лёгкий бег: один шаг в лёгкой зоне.
        """
        pace_by_zone = self._paces.pace_by_zone(self._athlete.vdot)

        # Готовые шаги — из формы фазы: пробежка с отрезками и ОФП.
        if session.steps:
            return session.steps

        if session.recipe is not None:
            return self._recipe_steps(session.recipe, pace_by_zone)

        pace = easy_pace_sec_per_km(pace_by_zone)
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

        Километраж — **по собранным шагам**, а не из макро: форма фазы
        задаёт свой недельный объём («55-57 км»), и макро-план с ним
        разойдётся. Клиент показывает то, что в неделе.
        """
        minutes = float(sum(w.duration_min for w in week.workouts))
        sessions = float(len(week.workouts))
        distance_m = sum(
            float(step.target_value)
            for workout in week.workouts
            for step in workout.steps
            if step.target_type == TargetType.DISTANCE
        )
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
