"""Планировщик недели: макро + атлет + среда → неделя.

Шаг 3 планировщика (см. `specs/logical/LOGICAL.md`). Логика построения
тренировочного процесса — здесь, в сервисе.

Порядок:
1. цель и объём недели из макро;
2. структура качественной сессии — по (goal, scale) из шаблонов методологии;
3. раскладка по слотам среды;
4. что не разложилось — висяк, решение пользователя;
5. сборка шагов; длительность тренировки = Σ шагов;
6. неделя готова к активации — активация по команде пользователя.

Правила методики — данные (`MethodologyRepo`). Движок применяет их, но не
решает, что считать.
"""
from __future__ import annotations

from dataclasses import dataclass
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


class WeekPlanner:
    """Собирает неделю из макро, профиля и среды.

    Движок методики: применяет правила, не решает, что считать. Правила приходят
    из `MethodologyRepo`.
    """

    def __init__(
        self,
        templates: dict[str, WorkoutTemplate],
        load_model: LoadModel,
        athlete: Athlete,
    ) -> None:
        self._templates = templates
        self._load_model = load_model
        self._athlete = athlete

    def build(
        self,
        season_week: int,
        week_start: date,
        week_end: date,
        targets: list[WeeklyTarget],
        slots: list[Slot],
        phase_overrides: list[SlotOverride] | None = None,
        week_overrides: list[SlotOverride] | None = None,
    ) -> Week:
        """Собрать неделю: цель → запросы → размещения → тренировки → шаги."""
        merged = merged_slots(slots, phase_overrides or [], week_overrides or [])

        requests: list[Request] = []
        assignments: list[Assignment] = []
        unplaced: list[Request] = []
        workouts: list[Workout] = []

        for index, target in enumerate(targets):
            request = Request(
                id=f"r{season_week}-{index + 1}",
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
                workouts.append(self._build_workout(request, target))
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
            workouts.append(self._build_workout(request, target))

        week = Week(
            id=f"W{season_week}",
            plan_id="",
            season_week=season_week,
            start=week_start,
            end=week_end,
            status=WeekStatus.PROPOSED,
            load_target=self._load_target(targets),
            requests=requests,
            assignments=assignments,
            unplaced=unplaced,
            workouts=workouts,
        )
        week.validate()
        return week

    # ---------------------------------------------------------- внутреннее

    def _pick_slot(
        self,
        slots: list[Slot],
        request: Request,
        taken: list[Assignment],
    ) -> Slot | None:
        """Подобрать слот: помещается по времени, нет конфликта, доступно оборудование."""
        used = {a.slot_id for a in taken}
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
            return slot
        return None

    def _build_workout(self, request: Request, target: WeeklyTarget) -> Workout:
        """Тренировка из запроса: шаги по шаблону методики."""
        steps = self._build_steps(request, target)
        return Workout(
            id=f"w-{request.id}",
            request_id=request.id,
            sport=request.sport,
            kind=request.kind,
            focus=request.focus,
            steps=steps,
            duration_min=sum(s.duration_min for s in steps),
            rationale=f"{target.kind} · {target.focus}" if target.focus else target.kind,
        )

    def _build_steps(self, request: Request, target: WeeklyTarget) -> list[Step]:
        """Шаги тренировки.

        Пока используется простой рецепт: разминка → работа → заминка. Более
        сложные структуры приходят из шаблонов методологии (этап 3б).
        """
        work_min = max(request.duration_min - 10.0, 1.0)
        return [
            Step(
                id=f"{request.id}-warmup",
                role=StepRole.WARMUP,
                sport=request.sport,
                target_type=TargetType.TIME,
                target_value=5.0,
                focus=FocusType.NONE,
                duration_min=5.0,
            ),
            Step(
                id=f"{request.id}-work",
                role=StepRole.WORK,
                sport=request.sport,
                target_type=TargetType.TIME,
                target_value=work_min,
                focus=self._focus_for(target),
                focus_value={"zone": self._zone_for(target)},
                duration_min=work_min,
            ),
            Step(
                id=f"{request.id}-cooldown",
                role=StepRole.COOLDOWN,
                sport=request.sport,
                target_type=TargetType.TIME,
                target_value=5.0,
                focus=FocusType.NONE,
                duration_min=5.0,
            ),
        ]

    def _focus_for(self, target: WeeklyTarget) -> FocusType:
        if target.kind in ("quality", "tempo", "threshold", "vo2max"):
            return FocusType.HR
        return FocusType.NONE

    def _zone_for(self, target: WeeklyTarget) -> str:
        """Зона по виду работы: интенсивная — Z4, иначе Z2."""
        if target.kind in ("quality", "tempo", "threshold", "vo2max"):
            return "Z4"
        return "Z2"

    def _load_target(self, targets: list[WeeklyTarget]) -> dict[str, float]:
        """Недельная цель: сумма минут и число сессий."""
        return {
            "minutes": float(sum(t.duration_min for t in targets)),
            "sessions": float(len(targets)),
        }


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
