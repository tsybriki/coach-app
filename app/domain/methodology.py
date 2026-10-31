"""Правила методологии: рецепты тренировок, темпы, программа недель.

Правила — данные. Они приходят через порт `MethodologyRepo`; домен знает их
язык, но не знает, откуда они взялись и в каком файле лежат.

Язык правил:

- **Зона** — интенсивность методики: `E` (лёгкий), `M` (марафонский),
  `T` (пороговый), `I` (интервальный), `R` (повторный). Это интенсивность
  правила, а не зона пульса атлета: пульс — свойство спортсмена, зона
  правила — нет.
- **Рецепт** — одна тренировка: наборы с повторами либо плоский список кусков.
- **Ограничение недели** (`ZoneCap`) — сколько километров недели можно бежать
  в зоне: доля недельного километража и, у части зон, потолок в километрах
  («8 % недельного километража или 10 км — что меньше»).
- **Программа** (`MethodPlan`) — недели программы по фазам плюс правило
  «сколько недель в какой фазе, если до старта N недель» (`WeekSchedule`).

Производные (темпы, длительности шагов, объём недели) не хранятся — считаются.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.entities import Athlete, Step
from app.domain.enums import FocusType, Sport, StepRole, TargetType

ZONE_EASY = "E"
ZONE_MARATHON = "M"
ZONE_THRESHOLD = "T"
ZONE_INTERVAL = "I"
ZONE_REPETITION = "R"

ZONE_NAMES = {
    ZONE_EASY: "Л",
    ZONE_MARATHON: "М",
    ZONE_THRESHOLD: "П",
    ZONE_INTERVAL: "И",
    ZONE_REPETITION: "Пв",
}

ZONE_FULL = {
    ZONE_EASY: "лёгкий темп",
    ZONE_MARATHON: "марафонский темп",
    ZONE_THRESHOLD: "пороговый темп",
    ZONE_INTERVAL: "интервальный темпе",
    ZONE_REPETITION: "повторный темп",
}

# Диапазон пульса зоны правила, в % от HRmax атлета.
#
# Источник: Дэниэлс, главы 4-10: E 65-78 % HRmax, T 88-90 % HRmax,
# I 95-100 % HRmax. Марафонский темп — между E и T: по %VO2max 79-85 %,
# что по пульсу даёт 78-84 % HRmax. У повторного темпа пульсового
# соответствия нет: он быстрее максимума пульса, поэтому работа в нём
# задаётся темпом, а не пульсом.
ZONE_HR_PCT = {
    ZONE_EASY: (65.0, 78.0),
    ZONE_MARATHON: (78.0, 84.0),
    ZONE_THRESHOLD: (88.0, 90.0),
    ZONE_INTERVAL: (95.0, 100.0),
}

# Зона правила → зона пульса атлета. По мосту зон Дэниэлса: E → Z1-Z2,
# M → Z3-Z4, T → Z5, I → Z7. У повторного темпа зоны атлета нет.
ZONE_ATHLETE_ZONE = {
    ZONE_EASY: "Z2",
    ZONE_MARATHON: "Z3",
    ZONE_THRESHOLD: "Z5",
    ZONE_INTERVAL: "Z7",
}


# ------------------------------------------------------------------ типы правил


@dataclass(frozen=True)
class PaceRow:
    """Строка таблицы темпов: VDOT → темпы зон, сек/км."""

    vdot: int
    paces_sec_per_km: dict[str, float]


@dataclass(frozen=True)
class DanielsPaces:
    """Таблица темпов Дэниэлса: VDOT → темпы зон.

    Справочник, а не профиль: меняется только при смене издания.
    """

    rows: tuple[PaceRow, ...] = ()

    def pace_sec_per_km(self, zone: str, vdot: float) -> float | None:
        """Темп зоны для VDOT. Между строками — интерполяция, не округление вниз.

        Округление вниз делает атлета быстрее, чем он есть.

        Интерполяция идёт по непрерывным величинам, а печатные значения
        округлены: между VDOT 48 и 49 темп может совпасть. Поэтому при
        точном попадании в строку берётся её значение, а при дробном VDOT —
        линейная интерполяция между строками, и уже она округляется до
        целой секунды (темпы в книге — целые секунды на километр).
        """
        if not self.rows:
            return None
        exact = next((r for r in self.rows if r.vdot == int(vdot)), None)
        if exact is not None and float(vdot) == int(vdot):
            return exact.paces_sec_per_km.get(zone)
        lower = next((r for r in self.rows if r.vdot <= vdot), None)
        higher = next((r for r in self.rows if r.vdot > vdot), None)
        if lower is None:
            return self.rows[0].paces_sec_per_km.get(zone)
        if higher is None or higher.vdot == lower.vdot:
            return lower.paces_sec_per_km.get(zone)
        fraction = (vdot - lower.vdot) / (higher.vdot - lower.vdot)
        low_pace = lower.paces_sec_per_km.get(zone)
        high_pace = higher.paces_sec_per_km.get(zone)
        if low_pace is None or high_pace is None:
            return low_pace if low_pace is not None else high_pace
        return low_pace + (high_pace - low_pace) * fraction

    def pace_by_zone(self, vdot: float) -> dict[str, float]:
        """Все зоны для VDOT — то, что нужно планировщику."""
        paces: dict[str, float] = {}
        for zone in ZONE_NAMES:
            value = self.pace_sec_per_km(zone, vdot)
            if value is not None:
                paces[zone] = value
        return paces


@dataclass(frozen=True)
class RecipeSegment:
    """Кусок работы в одной зоне: объём или время.

    `alternatives` — равнозначные способы задать тот же кусок («3 мин в
    И-темпе или 800 м в И-темпе»). Берётся первый.

    `pace_offset_sec` — смещение темпа зоны в секундах на километр. Нужно для
    прогрессии: «бег с ускорением — темп растёт на 5 с на 400 м». Само
    смещение хранится в правилах, а не в домене: правило говорит «5 с на
    400 м», перевод в секунды на километр — дело движка.
    """

    zone: str
    distance_m: float | None = None
    minutes: float | None = None
    seconds: float | None = None
    alternatives: tuple[RecipeSegment, ...] = ()
    pace_offset_sec: float = 0.0

    def label(self) -> str:
        """«200м Пв» / «2мин И»."""
        if self.distance_m:
            amount = f"{int(self.distance_m)}м"
        elif self.minutes:
            amount = f"{int(self.minutes)}мин"
        elif self.seconds:
            amount = f"{int(self.seconds)}с"
        else:
            amount = "?"
        return f"{amount} {ZONE_NAMES.get(self.zone, self.zone)}"


@dataclass(frozen=True)
class RecipeSet:
    """Набор с повторами: сколько раз повторить последовательность сегментов."""

    reps_min: int
    reps_max: int
    segments: tuple[RecipeSegment, ...]
    label: str = ""


@dataclass(frozen=True)
class WorkoutRecipe:
    """Рецепт одной тренировки из правил методологии."""

    kind: str
    label: str
    sets: tuple[RecipeSet, ...] = ()
    flat: tuple[RecipeSegment, ...] = ()
    note: str = ""
    distance_m: float = 0.0
    pace_growth_sec_per_400m: float = 0.0
    final_zone: str = ""

    @property
    def is_quality(self) -> bool:
        """Качественная работа — всё, кроме лёгкого бега и гонки."""
        return self.kind not in ("FILL", "LONG", "RACE")


@dataclass(frozen=True)
class ZoneCap:
    """Ограничение недели: сколько километров в зоне можно.

    `fraction_of_week` — доля недельного километража. `ceiling_km` — потолок
    в километрах, если он есть («8 % недельного километража или 10 км — что
    меньше»). Потолок в 10 км — правило «I-темп: не больше 10 км», а не
    доля: без него атлет с большим объёмом набирал бы неограниченно много
    интервальной работы.
    """

    zone: str
    fraction_of_week: float
    ceiling_km: float | None = None

    def limit_km(self, week_km: float) -> float:
        """Предел километров в зоне для недели заданного объёма."""
        limit = week_km * self.fraction_of_week
        if self.ceiling_km is not None:
            limit = min(limit, self.ceiling_km)
        return limit


@dataclass(frozen=True)
class PhaseWeek:
    """Неделя программы: какие тренировки и какие ограничения."""

    phase: int
    week: int
    recipes: tuple[WorkoutRecipe, ...] = ()
    caps: tuple[ZoneCap, ...] = ()

    def cap_for(self, zone: str) -> ZoneCap | None:
        for cap in self.caps:
            if cap.zone == zone:
                return cap
        return None


@dataclass(frozen=True)
class WeekSchedule:
    """Распределение недель по фазам программы.

    `weeks` — сколько недель до старта. `phases` — какие недели
    **программы** попадают в каждую фазу при таком сроке.

    Недели перечислены явно, а не заданы количеством: при сжатии программы
    недели перетасовываются между фазами, и одна и та же неделя программы
    в разных сроках попадает в разные фазы. Считать «6 недель первой фазы»
    нельзя — это другая неделя программы.
    """

    weeks: int
    phases: dict[int, tuple[int, ...]] = field(default_factory=dict)

    def total(self) -> int:
        return sum(len(weeks) for weeks in self.phases.values())

    def weeks_for(self, phase: int) -> tuple[int, ...]:
        """Недели программы, попадающие в фазу."""
        return self.phases.get(phase, ())

    def phase_of(self, program_week: int) -> int | None:
        """Фаза, в которую попадает неделя программы."""
        for phase, weeks in self.phases.items():
            if program_week in weeks:
                return phase
        return None


@dataclass(frozen=True)
class MethodPlan:
    """Программа тренировок целиком: недели, распределение по срокам."""

    weeks: tuple[PhaseWeek, ...] = ()
    schedules: tuple[WeekSchedule, ...] = ()
    base_schedule: WeekSchedule | None = None

    def week(self, phase: int, week: int) -> PhaseWeek | None:
        for entry in self.weeks:
            if entry.phase == phase and entry.week == week:
                return entry
        return None

    def schedule_for(self, weeks_to_race: int) -> WeekSchedule | None:
        """Распределение недель по фазам для заданного срока до старта."""
        for schedule in self.schedules:
            if schedule.weeks == weeks_to_race:
                return schedule
        if self.base_schedule is not None:
            return self.base_schedule
        return None

    def program_week(self, weeks_to_race: int, offset: int) -> tuple[int, int] | None:
        """Неделя программы для недели сезона.

        `offset` — номер недели от начала плана с нуля. Фазы занимают
       timeline по порядку, и на каждую фазу отводится столько недель,
        сколько она содержит. Внутри фазы недели программы идут в том
        порядке, в каком перечислены в правиле.

        Возвращается (фаза, неделя программы). None — неделя за пределами
        программы (гонка, доведение).

        Важно: неделя программы определяется правилом распределения, а не
        порядковым номером недели сезона. При 24 неделях до старта первая
        неделя сезона — это неделя 1 программы, а седьмая — неделя 10
        программы (фаза II): недели программы перетасовываются между фазами.
        """
        schedule = self.schedule_for(weeks_to_race)
        if schedule is None:
            return None
        remaining = offset
        for phase in sorted(schedule.phases):
            weeks = schedule.weeks_for(phase)
            if remaining < len(weeks):
                return (phase, weeks[remaining])
            remaining -= len(weeks)
        return None


# ------------------------------------------------------------------ вычисления


def format_pace(sec_per_km: float) -> str:
    """Секунды на километр → «4:24»."""
    total = int(round(sec_per_km))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def zone_hr_target(zone: str, athlete: Athlete) -> int | None:
    """Целевой пульс зоны правила — по HRmax атлета.

    None, если у зоны нет пульсового соответствия (повторный темп: он
    быстрее максимума пульса).
    """
    percent_range = ZONE_HR_PCT.get(zone)
    if percent_range is None or athlete.hr_max <= 0:
        return None
    middle = (percent_range[0] + percent_range[1]) / 2.0
    return int(round(athlete.hr_max * middle / 100.0))


def athlete_zone_for(zone: str, athlete: Athlete) -> str | None:
    """Зона пульса атлета для зоны правила.

    По середине пульсового диапазона зоны правила ищется зона атлета, в
    которую он попадает. Нет — None: тогда шаг задаётся темпом.
    """
    known = ZONE_ATHLETE_ZONE.get(zone)
    if known and known in athlete.hr_zones:
        return known
    target = zone_hr_target(zone, athlete)
    if target is None:
        return None
    for name, (low, high) in athlete.hr_zones.items():
        if low <= target <= high:
            return name
    return None


def segment_duration_min(segment: RecipeSegment,
                         pace_by_zone: dict[str, float]) -> float:
    """Длительность куска работы в минутах.

    Объём → по темпу зоны. Время — как есть.
    """
    if segment.minutes:
        return float(segment.minutes)
    if segment.seconds:
        return float(segment.seconds) / 60.0
    distance_m = segment.distance_m
    if not distance_m:
        return 0.0
    pace = pace_by_zone.get(segment.zone)
    if not pace:
        return 0.0
    return (distance_m / 1000.0) * pace / 60.0


def recipe_zone_volume_m(recipe: WorkoutRecipe) -> dict[str, float]:
    """Сколько метров рецепт даёт в каждой зоне.

    Считается по минимальному числу повторов: объём недели планируется по
    нижней границе, а не по верхней.
    """
    volumes: dict[str, float] = {}

    def add(segment: RecipeSegment, reps: int) -> None:
        if segment.distance_m:
            volumes[segment.zone] = volumes.get(segment.zone, 0.0) + segment.distance_m * reps

    for recipe_set in recipe.sets:
        for segment in recipe_set.segments:
            add(segment, recipe_set.reps_min)
    for segment in recipe.flat:
        add(segment, 1)
    return volumes


def apply_week_caps(recipes: list[WorkoutRecipe],
                    caps: tuple[ZoneCap, ...],
                    week_km: float) -> list[WorkoutRecipe]:
    """Подчинить тренировки недели ограничениям по объёму.

    Предел задан на **неделю**, а не на тренировку: «R-темп — не более 5 %
    недельного километража» считает всё, что пробежано в этой зоне за
    неделю. Поэтому сначала считается сумма по зоне, и если она выше
    предела, лишнее снимается с самой объёмной работы.

    Если работу урезать нельзя (весь набор уходит), она уходит из недели
    совсем: пустая тренировка в плане хуже, чем её отсутствие.
    """
    if not caps or week_km <= 0:
        return recipes

    result = list(recipes)
    for cap in caps:
        limit_m = cap.limit_km(week_km) * 1000.0
        if limit_m <= 0:
            continue
        # Страховка от зацикливания: каждый проход обязан уменьшить объём.
        for _ in range(len(result) * 4 + 4):
            current = _zone_volume(result, cap.zone)
            if current <= limit_m:
                break
            excess = current - limit_m
            index = _largest_in_zone(result, cap.zone)
            if index is None:
                break
            reduced = _shrink_recipe(result[index], cap.zone, excess)
            if reduced is None:
                result.pop(index)
                continue
            if _zone_volume([reduced], cap.zone) >= \
                    _zone_volume([result[index]], cap.zone):
                # Урезание ничего не дало — дальше крутить бессмысленно.
                break
            result[index] = reduced
    return result


def _zone_volume(recipes: list[WorkoutRecipe], zone: str) -> float:
    """Суммарный объём в зоне по списку рецептов."""
    total = 0.0
    for recipe in recipes:
        total += recipe_zone_volume_m(recipe).get(zone, 0.0)
    return total


def _largest_in_zone(recipes: list[WorkoutRecipe], zone: str) -> int | None:
    """Индекс самого объёмного рецепта в зоне."""
    best: int | None = None
    best_volume = 0.0
    for index, recipe in enumerate(recipes):
        volume = recipe_zone_volume_m(recipe).get(zone, 0.0)
        if volume > best_volume:
            best = index
            best_volume = volume
    return best


def _shrink_recipe(recipe: WorkoutRecipe, zone: str,
                   excess_m: float) -> WorkoutRecipe | None:
    """Снять с рецепта до `excess_m` метров работы в зоне.

    None — из рецепта в этой зоне ничего не осталось.

    Важно: урезание обязано уменьшать объём. Если набор нельзя уменьшить
    (один повтор — это весь объём), он уходит целиком. Иначе цикл урезания
    не сходится: объём не меняется, а предел не достигается.
    """
    current = recipe_zone_volume_m(recipe).get(zone, 0.0)
    if current <= 0:
        return None
    excess = min(excess_m, current)

    new_sets = list(recipe.sets)
    for recipe_set in list(recipe.sets):
        set_volume = sum(
            (s.distance_m or 0.0) for s in recipe_set.segments if s.zone == zone
        ) * recipe_set.reps_min
        if set_volume <= 0:
            continue
        if excess >= set_volume:
            # Набор уходит целиком — объём в зоне уменьшается на set_volume.
            new_sets.remove(recipe_set)
            excess -= set_volume
            if excess <= 0:
                break
            continue
        per_rep = set_volume / recipe_set.reps_min
        keep = int((set_volume - excess) // per_rep)
        if keep < 1 or keep >= recipe_set.reps_min:
            # Частично урезать нельзя: набор уходит целиком.
            new_sets.remove(recipe_set)
            excess -= set_volume
            if excess <= 0:
                break
            continue
        index = new_sets.index(recipe_set)
        new_sets[index] = RecipeSet(
            reps_min=keep,
            reps_max=min(recipe_set.reps_max, keep),
            segments=recipe_set.segments,
            label=recipe_set.label,
        )
        excess -= set_volume - keep * per_rep
        if excess <= 0:
            break

    # Плоский список не урезается: если объём в зоне остался в нём —
    # рецепт целиком не годится.
    flat_volume = sum(
        (s.distance_m or 0.0) for s in recipe.flat if s.zone == zone
    )
    sets_volume = sum(
        sum((s.distance_m or 0.0) for s in recipe_set.segments if s.zone == zone)
        * recipe_set.reps_min
        for recipe_set in new_sets
    )
    if flat_volume > 0 and flat_volume + sets_volume > 0:
        return None

    if not new_sets and not recipe.flat:
        return None
    return WorkoutRecipe(
        kind=recipe.kind,
        label=recipe.label,
        sets=tuple(new_sets),
        flat=recipe.flat,
        note=recipe.note,
    )


def scale_recipe(recipe: WorkoutRecipe, zone: str,
                 max_volume_m: float) -> WorkoutRecipe:
    """Сократить повторы так, чтобы в зоне уложиться в предел.

    Сокращается набор с наибольшим объёмом в этой зоне: одна тренировка
    теряет часть повторов, остальные не трогаются. Если предел не
    достижим даже одним повтором — набор уходит целиком, и это видно по
    объёму: план покажет меньше, чем правило разрешает.
    """
    volumes = recipe_zone_volume_m(recipe)
    if volumes.get(zone, 0.0) <= max_volume_m:
        return recipe

    new_sets = list(recipe.sets)
    for index, recipe_set in enumerate(recipe.sets):
        set_volume = sum(
            (s.distance_m or 0.0) for s in recipe_set.segments if s.zone == zone
        ) * recipe_set.reps_min
        if set_volume <= 0:
            continue
        allowed_reps = int(max_volume_m // set_volume) if set_volume else 0
        if allowed_reps >= recipe_set.reps_min:
            continue
        if allowed_reps <= 0:
            new_sets.pop(index)
            break
        new_sets[index] = RecipeSet(
            reps_min=allowed_reps,
            reps_max=min(recipe_set.reps_max, allowed_reps),
            segments=recipe_set.segments,
            label=recipe_set.label,
        )
        break
    return WorkoutRecipe(
        kind=recipe.kind,
        label=recipe.label,
        sets=tuple(new_sets),
        flat=recipe.flat,
        note=recipe.note,
    )


def build_steps(recipe: WorkoutRecipe,
                pace_by_zone: dict[str, float],
                athlete: Athlete) -> list[Step]:
    """Шаги тренировки по рецепту.

    Плоский список: прогрессия и повторы — отдельные шаги. Набор помечен
    группой и номером повтора, чтобы клиент собрал сет обратно.
    """
    steps: list[Step] = []
    index = 0

    def add_segment(segment: RecipeSegment, group: str | None,
                    round_number: int | None, role: StepRole,
                    reps: int | None = None,
                    pace_offset_sec: float = 0.0) -> None:
        nonlocal index
        index += 1
        duration = segment_duration_min(segment, pace_by_zone)
        if segment.distance_m:
            target_type = TargetType.DISTANCE
            target_value = float(segment.distance_m)
        elif segment.minutes:
            target_type = TargetType.TIME
            target_value = float(segment.minutes)
        elif segment.seconds:
            target_type = TargetType.TIME
            target_value = float(segment.seconds) / 60.0
        else:
            target_type = TargetType.OPEN
            target_value = duration

        focus_value: dict[str, Any] = {}
        athlete_zone = athlete_zone_for(segment.zone, athlete)
        pace = pace_by_zone.get(segment.zone)
        if pace is not None:
            pace = pace + pace_offset_sec
        if athlete_zone:
            focus = FocusType.HR
            focus_value["zone"] = athlete_zone
            hr_target = zone_hr_target(segment.zone, athlete)
            if hr_target:
                focus_value["hr_target"] = hr_target
            if pace:
                focus_value["pace_min_per_km"] = format_pace(pace)
        else:
            focus = FocusType.PACE
            if pace:
                focus_value["pace_min_per_km"] = format_pace(pace)

        if reps:
            focus_value["set_reps"] = reps
        focus_value["daniels_zone"] = segment.zone

        steps.append(Step(
            id=f"s{index}",
            role=role,
            sport=Sport.RUN,
            target_type=target_type,
            target_value=target_value,
            focus=focus,
            focus_value=focus_value,
            group=group,
            round=round_number,
            duration_min=round(duration, 2),
        ))

    for recipe_set in recipe.sets:
        for position in range(1, recipe_set.reps_min + 1):
            for segment in recipe_set.segments:
                role = StepRole.REST if segment.zone == ZONE_EASY else StepRole.WORK
                add_segment(segment, recipe_set.label or recipe.label,
                            position, role, reps=recipe_set.reps_min)

    for segment in recipe.flat:
        role = StepRole.REST if segment.zone == ZONE_EASY else StepRole.WORK
        add_segment(segment, None, None, role)

    return steps


def build_progression_steps(recipe: WorkoutRecipe,
                            pace_by_zone: dict[str, float],
                            athlete: Athlete,
                            total_distance_m: float,
                            pace_growth_sec_per_400m: float,
                            final_zone: str = ZONE_INTERVAL,
                            ) -> list[Step]:
    """Шаги прогрессии: «бег с ускорением».

    Правило Дэниэлса: «бег с ускорением начинается очень медленно, постепенно
    темп увеличивается на 5 с на 400 м, последние 400 м — примерно в
    интервальном темпе».

    Разбивка — на отрезки по 400 м: каждый следующий быстрее предыдущего на
    заданное число секунд. Первый отрезок — легкий темп, последние 400 м —
    интервальный.
    """
    if total_distance_m <= 0 or not pace_by_zone:
        return []

    steps: list[Step] = []
    lap_m = 400.0
    laps = max(int(total_distance_m // lap_m), 1)

    easy_pace = pace_by_zone.get(ZONE_EASY)
    interval_pace = pace_by_zone.get(final_zone, easy_pace)
    if easy_pace is None or interval_pace is None:
        return []

    # Темп последнего отрезка — интервальный, предыдущие — плавно быстрее.
    for index in range(laps):
        fraction = (index + 1) / laps
        pace = easy_pace + (interval_pace - easy_pace) * fraction
        duration = (lap_m / 1000.0) * pace / 60.0
        zone = final_zone if index == laps - 1 else ZONE_EASY
        steps.append(Step(
            id=f"acc{index + 1}",
            role=StepRole.WORK,
            sport=Sport.RUN,
            target_type=TargetType.DISTANCE,
            target_value=lap_m,
            focus=FocusType.HR if athlete_zone_for(zone, athlete) else FocusType.PACE,
            focus_value={
                "zone": athlete_zone_for(zone, athlete) or "",
                "pace_min_per_km": format_pace(pace),
                "daniels_zone": zone,
                "pace_offset_sec": round(pace - easy_pace, 1),
                "progression_sec_per_400m": pace_growth_sec_per_400m,
            },
            group=recipe.label or "Бег с ускорением",
            round=index + 1,
            duration_min=round(duration, 2),
        ))
    return steps


__all__ = [
    "DanielsPaces",
    "MethodPlan",
    "PaceRow",
    "PhaseWeek",
    "RecipeSegment",
    "RecipeSet",
    "WeekSchedule",
    "WorkoutRecipe",
    "ZoneCap",
    "athlete_zone_for",
    "build_steps",
    "format_pace",
    "recipe_zone_volume_m",
    "scale_recipe",
    "segment_duration_min",
    "zone_hr_target",
]
