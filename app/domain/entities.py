"""Сущности домена.

Каждая сущность — данные и правила над ними. Инварианты проверяются при
создании или в методах, нарушающих правило.

Номера инвариантов (I1…I43) — из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.domain.enums import (
    CommandStatus,
    CommandType,
    FactSource,
    FocusType,
    IssuedBy,
    PlanStatus,
    Sport,
    StepRole,
    TargetType,
    Verdict,
    WeekStatus,
    WorkoutStatus,
)


class InvariantViolationError(Exception):
    """Нарушен доменный инвариант. Сообщение — что именно нарушено."""

    def __init__(self, invariant: str, message: str) -> None:
        super().__init__(f"{invariant}: {message}")
        self.invariant = invariant
        self.message = message


# ---------------------------------------------------------------- атлет


@dataclass(frozen=True)
class Athlete:
    """Нормативное состояние атлета. Форма — следствие прошлого, а не план."""

    vdot: float
    hr_zones: dict[str, tuple[int, int]]
    hr_max: int
    rhr: int
    lth: int
    weight_kg: float | None = None
    injuries: list[str] = field(default_factory=list)
    form: str | None = None


# ---------------------------------------------------------------- цель


@dataclass(frozen=True)
class Goal:
    """Цель плана: метрика и дата. Отдельной сущности Race нет."""

    id: str
    discipline: str
    race_date: date
    metric_type: str
    metric_target: float
    target_friendly: str
    venue: str | None = None
    start_time: str | None = None
    race_pace_min_per_km: float | None = None
    realistic_fork: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------- слоты


@dataclass(frozen=True)
class Slot:
    """Окно тренировки: время + доступное оборудование + запреты."""

    id: str
    day: int
    start: str
    end: str
    capacity_min: int
    equipment_ids: tuple[str, ...] = ()
    max_intensity: float | None = None
    forbidden_sports: frozenset[Sport] = frozenset()
    note: str | None = None
    priority_hint: int | None = None


@dataclass(frozen=True)
class SlotOverride:
    """Перекрытие слота. Patch хранит только отличие от уровня выше.

    `ops` — список операций, каждая со своим payload:
    `{"op": "set_time", "start": "18:00", "end": "20:00"}`.
    """

    slot_id: str
    ops: tuple[dict[str, Any], ...]
    reason: str
    scope: str  # season | phase | week
    scope_id: str | None = None


# ---------------------------------------------------------------- шаги и тренировки


@dataclass(frozen=True)
class Step:
    """Шаг тренировки. Плоский список: прогрессия — три отдельных шага."""

    id: str
    role: StepRole
    sport: Sport
    target_type: TargetType
    target_value: float
    focus: FocusType = FocusType.NONE
    focus_value: dict[str, Any] = field(default_factory=dict)
    group: str | None = None
    round: int | None = None
    label: str | None = None
    notes: str | None = None
    duration_min: float = 0.0


@dataclass
class Workout:
    """Тренировка: шаги + связь с фактом. Статус — состояние выполнения."""

    id: str
    request_id: str
    sport: Sport
    kind: str
    focus: str
    objective: dict[str, Any] = field(default_factory=dict)
    equipment_ids: tuple[str, ...] = ()
    location: str | None = None
    time: str | None = None
    steps: list[Step] = field(default_factory=list)
    duration_min: float = 0.0
    priority: int = 0
    status: WorkoutStatus = WorkoutStatus.PLANNED
    rationale: str | None = None
    actual_id: str | None = None

    def validate(self) -> None:
        """Проверить инварианты тренировки.

        Вызывается перед сохранением, а не в конструкторе: тренировка мутируема
        (шаги добавляются по мере сборки), и в конструкторе она ещё неполна.
        """
        self._check_single_sport()
        self._check_duration_sum()
        self.check_steps_do_not_overlap()

    def _check_single_sport(self) -> None:
        """I4: в тренировке один sport; все шаги этого спорта."""
        for step in self.steps:
            if step.sport != self.sport:
                raise InvariantViolationError(
                    "I4",
                    f"тренировка {self.id}: шаг {step.id} sport={step.sport} "
                    f"≠ sport тренировки {self.sport}",
                )

    def _check_duration_sum(self) -> None:
        """I5: Σ длительностей шагов = длительность тренировки."""
        total = self.steps_duration_min
        if abs(total - self.duration_min) > 0.01:
            raise InvariantViolationError(
                "I5",
                f"тренировка {self.id}: Σ шагов {total:.1f} ≠ длительность {self.duration_min:.1f}",
            )

    @property
    def steps_duration_min(self) -> float:
        """Сумма длительностей шагов — производное."""
        return sum(s.duration_min for s in self.steps)

    def check_steps_do_not_overlap(self) -> None:
        """I6: шаги не пересекаются по времени; rest идёт после work."""
        previous_end = 0.0
        seen_work = False
        for step in self.steps:
            if step.role is StepRole.WORK:
                seen_work = True
            elif step.role is StepRole.REST and not seen_work:
                raise InvariantViolationError("I6", f"тренировка {self.id}: rest до work")
            if step.duration_min < 0:
                raise InvariantViolationError(
                    "I6", f"тренировка {self.id}: отрицательная длительность"
                )
            previous_end += step.duration_min


# ---------------------------------------------------------------- запросы и размещения


@dataclass
class Request:
    """Намерение из макро. Статуса нет — состояние выводится из наличия Assignment."""

    id: str
    sport: Sport
    kind: str
    focus: str
    duration_min: int
    equipment_required: tuple[str, ...] = ()
    priority: int = 0
    min_slot_quality: int | None = None


@dataclass
class Assignment:
    """Размещение запроса по слоту. Статуса нет — факт выполнения в Workout.status."""

    request_id: str
    slot_id: str
    start: str
    duration_min: int
    equipment_ids: tuple[str, ...] = ()
    fit_score: float | None = None


# ---------------------------------------------------------------- неделя


@dataclass
class Week:
    """Неделя: три состояния, мягкое расписание, висяки."""

    id: str
    plan_id: str
    season_week: int
    start: date
    end: date
    status: WeekStatus = WeekStatus.PROPOSED
    focus: str | None = None
    load_target: dict[str, Any] = field(default_factory=dict)
    requests: list[Request] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    unplaced: list[Request] = field(default_factory=list)
    slot_overrides: list[SlotOverride] = field(default_factory=list)
    workouts: list[Workout] = field(default_factory=list)
    summary: WeekSummary | None = None
    version: int = 0

    def copy_with(
        self,
        *,
        status: WeekStatus | None = None,
        focus: str | None = None,
        load_target: dict[str, Any] | None = None,
        requests: list[Request] | None = None,
        assignments: list[Assignment] | None = None,
        unplaced: list[Request] | None = None,
        slot_overrides: list[SlotOverride] | None = None,
        workouts: list[Workout] | None = None,
        summary: WeekSummary | None = None,
    ) -> Week:
        """Копия недели с заменой указанных полей.

        Неизменённые поля переносятся как есть. Списки копируются — иначе
        мутация результата изменила бы исходную неделю.
        """
        return Week(
            id=self.id,
            plan_id=self.plan_id,
            season_week=self.season_week,
            start=self.start,
            end=self.end,
            status=status if status is not None else self.status,
            focus=focus if focus is not None else self.focus,
            load_target=dict(load_target) if load_target is not None else dict(self.load_target),
            requests=list(requests) if requests is not None else list(self.requests),
            assignments=list(assignments) if assignments is not None else list(self.assignments),
            unplaced=list(unplaced) if unplaced is not None else list(self.unplaced),
            slot_overrides=(
                list(slot_overrides) if slot_overrides is not None else list(self.slot_overrides)
            ),
            workouts=list(workouts) if workouts is not None else list(self.workouts),
            summary=summary if summary is not None else self.summary,
            version=self.version,
        )

    def validate(self) -> None:
        """Проверить инварианты недели.

        Вызывается перед сохранением: неделя мутируема, в конструкторе она
        ещё неполна (запросы размещаются постепенно).
        """
        self.check_unplaced_has_reason()
        self.check_closed_has_summary()
        self.check_workouts_have_requests()
        self.check_unplaced_not_bound_to_day()

    def check_unplaced_has_reason(self) -> None:
        """I7: запрос без размещения попадает в unplaced с причиной."""
        placed = {a.request_id for a in self.assignments}
        unplaced_ids = {r.id for r in self.unplaced}
        for req in self.requests:
            if req.id not in placed and req.id not in unplaced_ids:
                raise InvariantViolationError(
                    "I7", f"неделя {self.id}: запрос {req.id} без размещения не в unplaced"
                )

    def check_closed_has_summary(self) -> None:
        """I8: у недели со статусом closed есть WeekSummary."""
        if self.status is WeekStatus.CLOSED and self.summary is None:
            raise InvariantViolationError("I8", f"неделя {self.id}: closed без summary")

    def check_workouts_have_requests(self) -> None:
        """I20: каждый Workout вырос из Request (request_id задан)."""
        request_ids = {r.id for r in self.requests}
        for w in self.workouts:
            if w.request_id not in request_ids:
                raise InvariantViolationError(
                    "I20", f"неделя {self.id}: тренировка {w.id} без request_id"
                )

    def check_unplaced_not_bound_to_day(self) -> None:
        """I31: висяк не привязан к дню."""
        for req in self.unplaced:
            if hasattr(req, "slot_id") or hasattr(req, "day"):
                raise InvariantViolationError("I31", f"висяк {req.id} привязан к дню")


# ---------------------------------------------------------------- детали тренировки


@dataclass
class Split:
    """Отрезок тренировки — круг или автосплит."""
    index: int
    duration_s: float
    distance_m: float
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_cadence: int | None = None
    avg_speed_mps: float | None = None
    ascent_m: float | None = None


@dataclass
class WorkoutDetail:
    """Подробный разбор выполненной тренировки.

    Производное от FIT-файла Garmin: агрегаты, отрезки и ряды для графика.
    Хранится рядом с фактом, чтобы смотреть разбор без повторного разбора FIT.
    """
    actual_id: str
    source: FactSource = FactSource.GARMIN
    # агрегаты
    duration_s: float = 0.0
    elapsed_s: float = 0.0
    distance_m: float = 0.0
    ascent_m: float = 0.0
    descent_m: float = 0.0
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_cadence: int | None = None
    max_cadence: int | None = None
    avg_power_w: int | None = None
    max_power_w: int | None = None
    normalized_power_w: int | None = None
    calories: int | None = None
    # зоны пульса атлета, минуты
    hr_zone_minutes: dict[str, float] = field(default_factory=dict)
    # отрезки
    splits: list[Split] = field(default_factory=list)
    # ряды для графика: [секунда, пульс, каденция, мощность]
    series_hr: list[tuple[int, int]] = field(default_factory=list)
    series_cadence: list[tuple[int, int]] = field(default_factory=list)
    series_power: list[tuple[int, int]] = field(default_factory=list)
    series_distance: list[tuple[int, float]] = field(default_factory=list)
    # откуда данные
    cadence_source: str | None = None
    power_source: str | None = None


# ---------------------------------------------------------------- факт


@dataclass
class ActualSession:
    """Выполненная тренировка. Живёт вне плана, связывается вручную."""

    id: str
    date: date
    sport: Sport
    duration_min: int
    distance_m: float = 0.0
    hr_avg: int | None = None
    hr_max: int | None = None
    hr_zones_min: dict[str, int] = field(default_factory=dict)
    aerobic_te: float | None = None
    anaerobic_te: float | None = None
    vo2max: float | None = None
    moderate_min: int = 0
    vigorous_min: int = 0
    source: FactSource = FactSource.GARMIN
    external_id: str | None = None
    fetched_at: str | None = None
    linked_workout_id: str | None = None


@dataclass
class WeekSummary:
    """Итог недели: что планировали против того, что сделали."""

    week_id: str
    closed_at: str | None = None
    updated_at: str | None = None
    totals: dict[str, Any] = field(default_factory=dict)
    per_session: list[dict[str, Any]] = field(default_factory=list)
    verdict: dict[str, int] = field(default_factory=dict)
    missed: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    deviations: list[dict[str, Any]] = field(default_factory=list)
    intensity: dict[str, Any] = field(default_factory=dict)

    def actual_moderate(self) -> int:
        """I16: actual_moderate = Σ contributions[].moderate_min."""
        return sum(c.get("moderate_min", 0) for c in self.intensity.get("contributions", []))

    def actual_vigorous(self) -> int:
        """Аналогично для vigorous."""
        return sum(c.get("vigorous_min", 0) for c in self.intensity.get("contributions", []))

    def check_contributions_sum(self) -> None:
        """I16: вклад в неделю — сумма contributions."""
        intensity = self.intensity
        if intensity.get("actual_moderate") is None:
            return
        if intensity["actual_moderate"] != self.actual_moderate():
            raise InvariantViolationError(
                "I16",
                f"неделя {self.week_id}: actual_moderate {intensity['actual_moderate']} "
                f"≠ Σ contributions {self.actual_moderate()}",
            )


# ---------------------------------------------------------------- команда


@dataclass
class Command:
    """Любое изменение состояния. Ничего не меняется само."""

    id: str
    type: CommandType
    target: dict[str, Any] = field(default_factory=dict)
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    issued_at: str | None = None
    issued_by: IssuedBy = IssuedBy.USER
    expected_version: int = 0
    status: CommandStatus = CommandStatus.PROPOSED
    diff: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise InvariantViolationError("command", "reason обязателен")


# ---------------------------------------------------------------- план и сезон


@dataclass
class Phase:
    """Фаза плана: цель текстом. Не путать с Plan.goal — это цель плана."""

    id: str
    objective: str
    focus: str | None = None
    load_range: tuple[float, float] | None = None
    volume_range: tuple[float, float] | None = None
    intensity_pct_mean: float | None = None
    deload_weeks: tuple[int, ...] = ()
    sport_weights: dict[str, float] = field(default_factory=dict)
    slot_overrides: list[SlotOverride] = field(default_factory=list)


@dataclass
class Plan:
    """План: одна цель, последовательные фазы, один активный план на сезон."""

    id: str
    status: PlanStatus
    goal: Goal
    period_start: date
    period_end: date
    sport_lines: dict[str, dict[str, Any]] = field(default_factory=dict)
    load_budget: dict[str, Any] = field(default_factory=dict)
    phase_ids: list[str] = field(default_factory=list)
    transition: dict[str, Any] = field(default_factory=dict)


@dataclass
class Equipment:
    """Реестр оборудования. Доступность — во времени, а не «навсегда»."""

    id: str
    name: str
    kind: str
    sports: tuple[Sport, ...] = ()
    availability: dict[str, Any] = field(default_factory=dict)
    limitations: dict[str, Any] = field(default_factory=dict)


@dataclass
class Season:
    """Корень: календарь, справочники, факт. Цели приходят через планы."""

    id: str
    horizon_start: date
    horizon_end: date
    season_week_count: int
    slots: list[Slot] = field(default_factory=list)
    equipment: list[Equipment] = field(default_factory=list)
    plan_models: list[str] = field(default_factory=list)
    load_model_id: str | None = None
    plans: list[Plan] = field(default_factory=list)
    version: int = 0

    def validate(self) -> None:
        """Проверить инварианты сезона."""
        self.check_single_active_plan()
        self.check_slot_equipment_exists()

    def check_single_active_plan(self) -> None:
        """I1: в сезоне ровно один Plan со статусом active."""
        active = [p for p in self.plans if p.status is PlanStatus.ACTIVE]
        if len(active) != 1:
            raise InvariantViolationError(
                "I1", f"в сезоне {self.id}: активных планов {len(active)}, ожидался 1"
            )

    def check_slot_equipment_exists(self) -> None:
        """I3: ссылка слота — на существующее оборудование из реестра."""
        known = {e.id for e in self.equipment}
        for slot in self.slots:
            for eq in slot.equipment_ids:
                if eq not in known:
                    raise InvariantViolationError(
                        "I3", f"слот {slot.id}: оборудование {eq} не в реестре"
                    )


@dataclass
class PlanModel:
    """Стратегия: правила методики. Данные, а не код."""

    id: str
    name: str
    version: str
    sports: tuple[Sport, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)
    intensity_map: dict[str, Any] = field(default_factory=dict)
    intensity_units: tuple[str, ...] = ()
    block_rules: dict[str, Any] = field(default_factory=dict)
    progression_rules: dict[str, Any] = field(default_factory=dict)
    guard: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class LoadModel:
    """Правило нагрузки. Единственный владелец adaptation_rate (I43)."""

    intensity_factor: dict[str, float] = field(default_factory=dict)
    adaptation_rate: dict[str, float] = field(default_factory=dict)
    formula: str = ""
    budget: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ActualSession",
    "Assignment",
    "Athlete",
    "Command",
    "Equipment",
    "Goal",
    "InvariantViolationError",
    "LoadModel",
    "Phase",
    "Plan",
    "PlanModel",
    "Request",
    "Season",
    "Slot",
    "SlotOverride",
    "Step",
    "Verdict",
    "Week",
    "WeekSummary",
    "Workout",
]
