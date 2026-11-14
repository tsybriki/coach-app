"""Намерения тренировки и сборка из них шагов.

**Зачем это разделено.** Пользователь пишет тренировку обычным языком:
«12 км, 3 км разминка, дальше фартлек». Разбирает это модель — но не
числа. Модель говорит «разминка → работа → заминка», «фартлек»,
«8 км». Числа — зоны, темпы, длительности — считает домен, по профилю
атлета и таблице Дэниэлса.

Почему так: если модель придумывает пульс и темп, ошибки полезут оттуда,
где их быть не должно, и их нельзя будет отличить от ошибок домена.
Намерение («порог») — это про структуру, и модель в нём разбирается лучше
всего. Зона атлета и темп по форме — это про данные, и их знает домен.

**Два слоя.**

`WorkoutIntent` — то, что возвращает модель: роль шага, вид спорта,
объём (метры или минуты), намерение по интенсивности, название.

`Composition` — готовая структура: шаги домена плюс то, что модель
додумала (`assumptions`) плюс примечания к шагам (`notes`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.entities import Athlete, Step, Workout
from app.domain.enums import (
    FocusType,
    Sport,
    StepRole,
    TargetType,
    WorkoutStatus,
)
from app.domain.methodology import (
    EASY_PACE_SEC_PER_KM,
    ZONE_EASY,
    ZONE_INTERVAL,
    ZONE_MARATHON,
    ZONE_REPETITION,
    ZONE_THRESHOLD,
    athlete_zone_for,
    format_pace,
)

# Намерение по интенсивности → зона правила Дэниэлса.
#
# Ключи — слова, которые может использовать человек и которые модель
# переводит в намерение. Значение — зона правила: по ней домен знает и
# зону пульса атлета, и темп.
INTENT_ZONES: dict[str, str] = {
    "easy": ZONE_EASY,
    "recovery": ZONE_EASY,
    "long": ZONE_EASY,
    "marathon": ZONE_MARATHON,
    "steady": ZONE_MARATHON,
    "threshold": ZONE_THRESHOLD,
    "tempo": ZONE_THRESHOLD,
    "fartlek": ZONE_THRESHOLD,
    "interval": ZONE_INTERVAL,
    "vo2max": ZONE_INTERVAL,
    "repetition": ZONE_REPETITION,
    "stride": ZONE_REPETITION,
}

# Человеческие названия намерений — для интерфейса.
INTENT_LABELS: dict[str, str] = {
    ZONE_EASY: "лёгкий",
    ZONE_MARATHON: "марафонский",
    ZONE_THRESHOLD: "пороговый",
    ZONE_INTERVAL: "интервальный",
    ZONE_REPETITION: "повторный",
}

# Роль шага → зона по умолчанию, если намерение не названо.
#
# Разминка и заминка всегда лёгкие: это не работа. Если модель назвала
# другое намерение — оно важнее: человек мог попросить «разминка с
# ускорением».
ROLE_DEFAULT_INTENT: dict[StepRole, str] = {
    StepRole.WARMUP: ZONE_EASY,
    StepRole.COOLDOWN: ZONE_EASY,
    StepRole.REST: ZONE_EASY,
    StepRole.WORK: ZONE_EASY,
    StepRole.TRANSITION: ZONE_EASY,
}

# Короткий отрезок с отдыхом трусцой — это повторный темп (R), а не
# интервальный (I).
#
# Граница 600 м: до неё отрезок настолько короткий, что держится в темпе
# «на старт», а не в интервальном, — и в методике Дэниэлса это R.
# «6 по 200 через 200» — именно R. «6 по 800» — уже I.
#
# Почему нельзя оставлять intent модели: модель читает «интервалы» из
# любого повторного отрезка и темп I медленнее R — работа получается
# медленнее названного.
SHORT_REPEAT_MAX_M = 600.0


def _zone_for_intent(intent: WorkoutIntent) -> str:
    """Зона правила для намерения.

    Намерение модели важнее, но короткие повторы домен уточняет сам:
    «6 по 200 через 200» — повторный темп, даже если модель назвала
    «интервал».
    """
    zone = INTENT_ZONES.get(intent.intent)
    if zone is None:
        zone = ROLE_DEFAULT_INTENT.get(intent.role, ZONE_EASY)
    if (
        zone == ZONE_INTERVAL
        and intent.reps > 1
        and intent.target_type is TargetType.DISTANCE
        and 0 < intent.target_value <= SHORT_REPEAT_MAX_M
    ):
        return ZONE_REPETITION
    return zone


@dataclass(frozen=True)
class WorkoutIntent:
    """Намерение одного шага — то, что возвращает модель.

    Числа здесь — только объём, который человек назвал сам: «8 км»,
    «30 минут». Зон, темпов и пульсов нет: их считает домен.
    """

    role: StepRole
    sport: Sport
    # Объём шага: метры (DISTANCE) или минуты (TIME).
    target_type: TargetType
    target_value: float
    # Намерение по интенсивности: ключ INTENT_ZONES.
    intent: str = ZONE_EASY
    label: str = ""
    # Сколько повторов: 8×400 — это восемь шагов по 400 метров.
    reps: int = 1
    notes: str = ""
    # Отдых между повторами — метры или минуты (0 = без отдыха).
    rest_type: TargetType = TargetType.DISTANCE
    rest_value: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "sport": self.sport.value,
            "target_type": self.target_type.value,
            "target_value": self.target_value,
            "intent": self.intent,
            "label": self.label,
            "reps": self.reps,
            "notes": self.notes,
            "rest_type": self.rest_type.value,
            "rest_value": self.rest_value,
        }


@dataclass(frozen=True)
class ComposedStep:
    """Шаг тренировки с пометкой, откуда он взялся."""

    step: Step
    # Что модель предположила про этот шаг. Пусто — шаг взят из текста.
    assumption: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": {
                "id": self.step.id,
                "role": self.step.role.value,
                "sport": self.step.sport.value,
                "target_type": self.step.target_type.value,
                "target_value": self.step.target_value,
                "focus": self.step.focus.value,
                "focus_value": self.step.focus_value,
                "duration_min": self.step.duration_min,
                "label": self.step.label,
                "notes": self.step.notes,
                "group": self.step.group,
                "round": self.step.round,
            },
            "assumption": self.assumption,
        }


@dataclass(frozen=True)
class Composition:
    """Разобранная тренировка: шаги, название, что модель додумала."""

    name: str
    sport: Sport
    steps: list[ComposedStep]
    assumptions: list[str] = field(default_factory=list)
    # Текст пожеланий — чтобы показать, из чего разобрали.
    source_text: str = ""
    # Намерения, из которых собраны шаги. Едут вместе с разбором: без них
    # повторы («6 по 200 через 200») пришлось бы угадывать по шагам, и они
    # терялись бы при добавлении тренировки в неделю.
    intents: list[WorkoutIntent] = field(default_factory=list)

    @property
    def duration_min(self) -> float:
        return round(sum(s.step.duration_min for s in self.steps), 2)

    @property
    def distance_m(self) -> float:
        return round(sum(
            s.step.target_value
            for s in self.steps
            if s.step.target_type is TargetType.DISTANCE
        ), 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sport": self.sport.value,
            "duration_min": self.duration_min,
            "distance_m": self.distance_m,
            "assumptions": list(self.assumptions),
            "source_text": self.source_text,
            "intents": [i.as_dict() for i in self.intents],
            "steps": [s.as_dict() for s in self.steps],
        }


class CompositionError(Exception):
    """Текст не удалось разобрать в тренировку."""


def build_steps(
    intents: list[WorkoutIntent],
    athlete: Athlete,
    pace_by_zone: dict[str, float],
    *,
    assumptions: list[str] | None = None,
) -> Composition:
    """Собрать шаги из намерений.

    Зоны и темпы — по профилю атлета и таблице Дэниэлса. Модель в этом
    не участвует: она сказала «порог», домен знает, что это 164 уд/мин
    и 4:05/км.

    Повторы разворачиваются в чередующуюся последовательность:
    работа — отдых — работа. Раньше все работы шли подряд и отдых
    добавлялся после них, хотя на часах это разные круги.
    """
    steps: list[ComposedStep] = []
    notes: list[str] = list(assumptions or [])

    for index, intent in enumerate(intents):
        zone = _zone_for_intent(intent)

        step_assumption = ""
        focus, focus_value = _focus_for(zone, athlete, pace_by_zone)

        # Объём в шаге — то, что назвал человек.
        if intent.target_type is TargetType.DISTANCE:
            target_value = float(intent.target_value)
            pace = _pace_for(zone, pace_by_zone)
            duration = (target_value / 1000.0) * pace / 60.0 if pace else 0.0
            if not pace:
                step_assumption = "темп для этого объёма не найден — время шага неизвестно"
                notes.append(step_assumption)
        else:
            target_value = float(intent.target_value)
            duration = target_value

        label = intent.label or INTENT_LABELS.get(zone, "")

        # Намерение сохраняется в шаге: по нему видно, что за работа
        # (и по нему же тренировку можно пересобрать). Плюс — то, что
        # модель назвала, видно пользователю.
        focus_value = dict(focus_value)
        focus_value["intent"] = intent.intent

        # Повторы: «8×400» — это восемь кругов, у каждого — свои блоки:
        # работа и (если задан) отдых.
        reps = max(1, intent.reps)
        group = _group_name(intent) if reps > 1 else (label or None)
        rest_min = _rest_minutes(intent, pace_by_zone)
        has_rest = reps > 1 and intent.rest_value > 0
        blocks_per_round = 2 if has_rest else 1
        for rep in range(reps):
            step_id = f"s{index + 1}" if reps == 1 else f"s{index + 1}-{rep + 1}"
            step_focus_value = dict(focus_value)
            if reps > 1:
                step_focus_value["set_reps"] = reps
                step_focus_value["set_blocks"] = blocks_per_round
                step_focus_value["set_block"] = 1
            steps.append(ComposedStep(
                step=Step(
                    id=step_id,
                    role=intent.role,
                    sport=intent.sport,
                    target_type=intent.target_type,
                    target_value=target_value,
                    focus=focus,
                    focus_value=step_focus_value,
                    group=group,
                    round=rep + 1 if reps > 1 else None,
                    label=label or None,
                    notes=intent.notes or None,
                    duration_min=round(duration, 2),
                ),
                assumption=step_assumption,
            ))

            # Отдых — часть своего круга. Последний круг тоже: без него
            # объём набора не сходится с тем, что человек пробежал
            # (6 по 200 через 200 = 2400 м, а не 1200).
            if has_rest:
                rest_focus_value: dict[str, Any] = {"zone": "Z2"}
                # Темп отдыха виден в блоке круга: отдых 200 м — это
                # «200 м по 5:30», а не просто «отдых».
                rest_pace = _pace_for(ZONE_EASY, pace_by_zone)
                if rest_pace:
                    rest_focus_value["pace_min_per_km"] = format_pace(rest_pace)
                if reps > 1:
                    rest_focus_value["set_reps"] = reps
                    rest_focus_value["set_blocks"] = blocks_per_round
                    rest_focus_value["set_block"] = 2
                steps.append(ComposedStep(
                    step=Step(
                        id=f"s{index + 1}-r{rep + 1}",
                        role=StepRole.REST,
                        sport=intent.sport,
                        target_type=intent.rest_type,
                        target_value=float(intent.rest_value),
                        focus=FocusType.HR,
                        focus_value=rest_focus_value,
                        group=group,
                        round=rep + 1,
                        label="отдых",
                        duration_min=round(rest_min, 2),
                    ),
                ))

    if not steps:
        raise CompositionError("из текста не получилось сделать ни одного шага")

    sport = intents[0].sport
    name = _workout_name(intents, sport)
    return Composition(
        name=name,
        sport=sport,
        steps=steps,
        assumptions=notes,
        intents=list(intents),
    )


def _pace_for(zone: str, pace_by_zone: dict[str, float]) -> float | None:
    """Темп зоны. Лёгкий бег — всегда 5:30.

    «E» из таблицы Дэниэлса для этого спортсмена — 5:13, верх лёгкой
    зоны: в нём HR упирается в верх Z2, и лёгкий бег перестаёт быть
    лёгким. Правило одно на все места, где встречается лёгкий бег.
    """
    if zone == ZONE_EASY:
        return EASY_PACE_SEC_PER_KM
    return pace_by_zone.get(zone)


def _rest_minutes(intent: WorkoutIntent, pace_by_zone: dict[str, float]) -> float:
    """Длительность отдыха между повторами — в минутах."""
    if intent.rest_type is TargetType.DISTANCE:
        pace = _pace_for(ZONE_EASY, pace_by_zone)
        return (intent.rest_value / 1000.0) * pace / 60.0 if pace else 0.0
    return intent.rest_value


def _group_name(intent: WorkoutIntent) -> str:
    """Название набора — сам набор: «6×200м через 200м».

    Название должно различать наборы: два набора с одинаковой подписью
    клиент склеил бы в один блок, и тогда «6 по 200» и «5 по 400»
    показались бы одним сетом. Поэтому подпись собирается из самого
    набора, а не берётся из названия тренировки.
    """
    amount = _amount_label(intent)
    rest = ""
    if intent.rest_value > 0:
        rest = f" через {_rest_label(intent)}"
    return f"{max(1, intent.reps)}×{amount}{rest}"


def _amount_label(intent: WorkoutIntent) -> str:
    """Объём шага словами: «200м» или «90с»."""
    if intent.target_type is TargetType.DISTANCE:
        return f"{int(intent.target_value)}м"
    if intent.target_type is TargetType.TIME:
        seconds = int(round(intent.target_value * 60))
        return f"{seconds}с"
    return str(int(intent.target_value))


def _rest_label(intent: WorkoutIntent) -> str:
    """Отдых словами: «200м» или «90с»."""
    if intent.rest_type is TargetType.DISTANCE:
        return f"{int(intent.rest_value)}м"
    return f"{int(round(intent.rest_value * 60))}с"


def _focus_for(
    zone: str,
    athlete: Athlete,
    pace_by_zone: dict[str, float],
) -> tuple[FocusType, dict[str, Any]]:
    """Фокус шага: пульс или темп, и что именно указывать.

    У повторного темпа пульсового соответствия нет (он быстрее
    максимума пульса) — такой шаг задаётся темпом.
    """
    athlete_zone = athlete_zone_for(zone, athlete)
    pace = _pace_for(zone, pace_by_zone)
    if athlete_zone:
        value: dict[str, Any] = {"zone": athlete_zone}
        if pace:
            value["pace_min_per_km"] = format_pace(pace)
        return FocusType.HR, value
    if pace:
        return FocusType.PACE, {"pace_min_per_km": format_pace(pace)}
    return FocusType.NONE, {}


def _workout_name(intents: list[WorkoutIntent], sport: Sport) -> str:
    """Название тренировки — из её состава.

    Как и у тренировок планировщика: основа плюс то, что внутри
    («Лёгкий бег + отрезки»). Модель может предложить своё название —
    тогда оно и берётся, но только если модель его явно дала.
    """
    named = next((i.label for i in intents if i.label and i.role is StepRole.WORK), "")
    if named:
        return named

    parts: list[str] = []
    work_zones = {
        i.intent for i in intents if i.role is StepRole.WORK
    }
    base = "Лёгкий бег" if sport is Sport.RUN else "Тренировка"
    if work_zones and work_zones != {ZONE_EASY}:
        base = "Тренировка"
    parts.append(base)
    if any(i.reps > 1 for i in intents):
        parts.append("интервалы")
    return " + ".join(parts)


def workout_from_composition(
    composition: Composition,
    *,
    workout_id: str,
    request_id: str,
) -> Workout:
    """Готовая тренировка из разбора.

    Обычная тренировка: те же `Step`, те же инварианты. Разница только в
    пути создания — из текста, а не из макро-плана.
    """
    steps = [s.step for s in composition.steps]
    duration = round(sum(s.duration_min for s in steps), 2)
    objective: dict[str, Any] = {"name": composition.name}
    if composition.assumptions:
        objective["assumptions"] = list(composition.assumptions)
    if composition.source_text:
        objective["source_text"] = composition.source_text
    return Workout(
        id=workout_id,
        request_id=request_id,
        sport=composition.sport,
        kind="composed",
        focus=composition.name,
        objective=objective,
        steps=steps,
        duration_min=duration,
        status=WorkoutStatus.PLANNED,
        rationale="Тренировка из твоего описания.",
    )


__all__ = [
    "ComposedStep",
    "Composition",
    "CompositionError",
    "INTENT_LABELS",
    "INTENT_ZONES",
    "WorkoutIntent",
    "build_steps",
    "workout_from_composition",
]
