"""Перечисления домена — закрытые множества значений.

Каждое независимое измерение — отдельный тип. Смешивать разные измерения
в одном поле нельзя: в enum варианты становятся неразличимы.
"""
from __future__ import annotations

from enum import StrEnum


class WeekStatus(StrEnum):
    """Три состояния недели. Переходы — только по команде пользователя."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    CLOSED = "closed"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    DRAFT = "draft"


class Sport(StrEnum):
    RUN = "run"
    BIKE = "bike"
    SWIM = "swim"
    STRENGTH = "strength"
    OFP = "ofp"
    MOBILITY = "mobility"


class WorkoutStatus(StrEnum):
    PLANNED = "planned"
    DONE = "done"
    SKIPPED = "skipped"
    MOVED = "moved"


class StepRole(StrEnum):
    """Роль шага в тренировке."""

    WARMUP = "warmup"
    WORK = "work"
    REST = "rest"
    COOLDOWN = "cooldown"
    TRANSITION = "transition"


class TargetType(StrEnum):
    """Тип объёма шага — объём, не интенсивность."""

    TIME = "time"
    DISTANCE = "distance"
    LAPS = "laps"
    REPS = "reps"
    OPEN = "open"


class FocusType(StrEnum):
    """Интенсивность шага — отдельное измерение от объёма."""

    PACE = "pace"
    HR = "hr"
    POWER = "power"
    RPE = "rpe"
    NONE = "none"
    STRENGTH_PATTERN = "strength_pattern"


class FactSource(StrEnum):
    """Источник факта. По I14 активности берутся только из Garmin."""

    GARMIN = "garmin"
    MANUAL = "manual"


class Verdict(StrEnum):
    """Вердикт по сессии: план против факта."""

    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"
    EXTRA = "extra"
    SUBSTITUTED = "substituted"


class CommandType(StrEnum):
    """Типы команд. Любое изменение состояния — команда."""

    PROPOSE_WEEK = "propose_week"
    ACTIVATE_WEEK = "activate_week"
    CLOSE_WEEK = "close_week"
    REPLAN_REMAINDER = "replan_remainder"
    PLACE_UNPLACED = "place_unplaced"
    UNPLACE_REQUEST = "unplace_request"
    LINK_ACTUAL = "link_actual"
    UNLINK_ACTUAL = "unlink_actual"
    EDIT_ACTUAL = "edit_actual"
    UPDATE_ATHLETE = "update_athlete"
    SET_GOAL = "set_goal"
    SET_PLAN = "set_plan"
    SET_SLOTS = "set_slots"
    OVERRIDE_SLOTS = "override_slots"
    SET_EQUIPMENT = "set_equipment"
    SET_GATE_RESULT = "set_gate_result"
    DECIDE_GATE = "decide_gate"
    PULL_FACT = "pull_fact"
    IMPORT_FIT = "import_fit"
    NARRATE = "narrate"
    IMPORT_STATE = "import_state"


class CommandStatus(StrEnum):
    PROPOSED = "proposed"
    APPLIED = "applied"
    REJECTED = "rejected"
    NEEDS_CONFIRMATION = "needs_confirmation"


class IssuedBy(StrEnum):
    USER = "user"
    BRAIN = "brain"


class ErrorCode(StrEnum):
    """Коды ошибок в ответах API."""

    VERSION_CONFLICT = "version_conflict"
    BUSY = "busy"
    NOT_FOUND = "not_found"
    INVALID_COMMAND = "invalid_command"
    INVARIANT_VIOLATED = "invariant_violated"
    DEGRADED = "degraded"
    UNAUTHORIZED = "unauthorized"
