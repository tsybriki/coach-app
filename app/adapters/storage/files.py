"""Файловый адаптер хранилища.

Первая реализация портов хранения. Формат знает только этот модуль: домен,
сервисы и API работают через порты и не знают, что данные лежат в файлах.

Раскладка:
    <root>/season.json         Season
    <root>/athlete.json        Athlete
    <root>/weeks/W<n>.json     Week
    <root>/actual/W<n>.json    ActualSession[]
    <root>/methodology/*.json  правила
    <root>/versions.json       версия схемы

Запись атомарна: временный файл → fsync → os.replace → fsync каталога.
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import IO, Any

from app.domain.entities import (
    ActualSession,
    Assignment,
    Athlete,
    Command,
    Equipment,
    Goal,
    LoadModel,
    Plan,
    Request,
    Season,
    Slot,
    Step,
    Week,
    WeekSummary,
    Workout,
)
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
from app.ports.storage import (
    DuplicateExternalIdError,
    StorageBusyError,
    VersionConflictError,
)


class FileStorage:
    """Хранилище сезона на файлах.

    Один писатель — процесс BFF. `flock` на время записи: если лок занят,
    команда отклоняется, а не ждёт.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "weeks").mkdir(exist_ok=True)
        (self.root / "actual").mkdir(exist_ok=True)

    # ---------------------------------------------------------- служебное

    def _version(self) -> int:
        """Глобальная версия состояния.

        Один счётчик на всё состояние: изменение недели тоже двигает его.
        Раньше версия недели и версия сезона были разными числами, и команда
        сравнивала одно с другим — получался ложный конфликт.
        """
        data = self._read_json(self.root / "state.json")
        return int(data.get("version", 0))

    def _bump_version(self) -> int:
        """Увеличить глобальную версию на 1. Вернуть новую."""
        new_version = self._version() + 1
        self._write_json(self.root / "state.json", {"version": new_version})
        return new_version

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """Прочитать JSON. Битый файл → понятная ошибка, не исключение наугад."""
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"битый JSON в {path}: {error}") from error
        if not isinstance(data, dict):
            raise ValueError(f"ожидался объект в {path}")
        return data

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        """Атомарная запись: временный файл → fsync → replace → fsync каталога."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _lock(self) -> IO[str]:
        """Блокировка на запись. Лок занят → StorageBusyError."""
        lock_path = self.root / ".lock"
        lock_path.touch(exist_ok=True)
        # Хендл живёт дольше вызова: лок держится до конца записи.
        # Закрывает вызывающий — в finally.
        handle = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise StorageBusyError("хранилище занято другой записью") from error
        return handle

    def version(self) -> int:
        """Глобальная версия состояния."""
        return self._version()

    # ---------------------------------------------------------- низкий уровень

    def load(self) -> Season:
        data = self._read_json(self.root / "season.json")
        if not data:
            return Season(
                id="S1",
                horizon_start=date.today(),
                horizon_end=date.today(),
                season_week_count=0,
            )
        return _season_from_dict(data)

    def save(self, season: Season, expected_version: int) -> int:
        actual = self._version()
        if actual != expected_version:
            raise VersionConflictError(expected_version, actual)

        handle = self._lock()
        try:
            actual = self._version()
            if actual != expected_version:
                raise VersionConflictError(expected_version, actual)
            season.version = actual + 1
            self._write_json(self.root / "season.json", _season_to_dict(season))
            return self._bump_version()
        finally:
            handle.close()

    def week(self, season_week: int) -> Week | None:
        path = self.root / "weeks" / f"W{season_week}.json"
        if not path.exists():
            return None
        return _week_from_dict(self._read_json(path))

    def put_week(self, week: Week, expected_version: int) -> int:
        actual = self._version()
        if actual != expected_version:
            raise VersionConflictError(expected_version, actual)

        handle = self._lock()
        try:
            actual = self._version()
            if actual != expected_version:
                raise VersionConflictError(expected_version, actual)
            week.version = actual + 1
            self._write_json(self.root / "weeks" / f"W{week.season_week}.json",
                             _week_to_dict(week))
            return self._bump_version()
        finally:
            handle.close()

    # ---------------------------------------------------------- низкий уровень: факт

    def list_for_week(self, season_week: int) -> list[ActualSession]:
        path = self.root / "actual" / f"W{season_week}.json"
        data = self._read_json(path)
        return [_session_from_dict(item) for item in data.get("sessions", [])]

    def list_in_range(self, start: date, end: date) -> list[ActualSession]:
        sessions: list[ActualSession] = []
        for path in sorted((self.root / "actual").glob("W*.json")):
            data = self._read_json(path)
            for item in data.get("sessions", []):
                session = _session_from_dict(item)
                if start <= session.date <= end:
                    sessions.append(session)
        return sessions

    def get(self, actual_id: str) -> ActualSession | None:
        for path in sorted((self.root / "actual").glob("W*.json")):
            data = self._read_json(path)
            for item in data.get("sessions", []):
                session = _session_from_dict(item)
                if session.id == actual_id:
                    return session
        return None

    def upsert(self, session: ActualSession) -> ActualSession:
        if session.external_id:
            for existing in self.list_in_range(date.min, date.max):
                if existing.external_id == session.external_id and existing.id != session.id:
                    raise DuplicateExternalIdError(
                        f"факт с external_id {session.external_id} уже есть: {existing.id}"
                    )

        path = self.root / "actual" / f"W{_season_week_of(session.date)}.json"
        data = self._read_json(path)
        items = data.get("sessions", [])
        items = [item for item in items if item.get("id") != session.id]
        items.append(_session_to_dict(session))
        self._write_json(path, {"sessions": items})
        return session

    def link(self, actual_id: str, workout_id: str | None) -> None:
        session = self.get(actual_id)
        if session is None:
            raise KeyError(f"факт {actual_id} не найден")
        session.linked_workout_id = workout_id
        path = self.root / "actual" / f"W{_season_week_of(session.date)}.json"
        data = self._read_json(path)
        items = [
            _session_to_dict(session) if item.get("id") == actual_id else item
            for item in data.get("sessions", [])
        ]
        self._write_json(path, {"sessions": items})

    # ---------------------------------------------------------- низкий уровень: профиль

    def get_athlete(self) -> Athlete:
        data = self._read_json(self.root / "athlete.json")
        if not data:
            return Athlete(vdot=0.0, hr_zones={}, hr_max=0, rhr=0, lth=0)
        return Athlete(
            vdot=float(data.get("vdot", 0.0)),
            hr_zones=data.get("hr_zones", {}),
            hr_max=int(data.get("hr_max", 0)),
            rhr=int(data.get("rhr", 0)),
            lth=int(data.get("lth", 0)),
            weight_kg=data.get("weight_kg"),
            injuries=data.get("injuries", []),
            form=data.get("form"),
        )

    def update_athlete(self, athlete: Athlete) -> None:
        self._write_json(self.root / "athlete.json", {
            "vdot": athlete.vdot,
            "hr_zones": athlete.hr_zones,
            "hr_max": athlete.hr_max,
            "rhr": athlete.rhr,
            "lth": athlete.lth,
            "weight_kg": athlete.weight_kg,
            "injuries": athlete.injuries,
            "form": athlete.form,
        })

    # ---------------------------------------------------------- низкий уровень: правила

    def load_methodology_model(self) -> LoadModel:
        """Правило нагрузки из хранилища. Нет — пустое правило."""
        data = self._read_json(self.root / "methodology" / "load_model.json")
        if not data:
            return LoadModel()
        return LoadModel(
            intensity_factor=data.get("intensity_factor", {}),
            adaptation_rate=data.get("adaptation_rate", {}),
            formula=data.get("formula", ""),
            budget=data.get("budget", {}),
        )

    def load_workout_templates(self) -> dict[str, Any]:
        """Шаблоны тренировок из хранилища. Нет — пусто."""
        data = self._read_json(self.root / "methodology" / "workout_templates.json")
        templates: dict[str, Any] = data.get("templates", {})
        return templates

    # ---------------------------------------------------------- низкий уровень: журнал

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        data = self._read_json(self.root / "commands.json")
        commands: list[dict[str, Any]] = data.get("commands", [])
        for item in commands:
            if item.get("id") == command_id:
                return item
        return None

    def append_command(self, command: Command, result: dict[str, Any]) -> None:
        path = self.root / "commands.json"
        data = self._read_json(path)
        commands = [c for c in data.get("commands", []) if c.get("id") != command.id]
        commands.append({
            "id": command.id,
            "type": command.type.value,
            "reason": command.reason,
            "issued_at": command.issued_at,
            "issued_by": command.issued_by.value,
            "status": result.get("status"),
            "new_version": result.get("new_version"),
        })
        self._write_json(path, {"commands": commands})


# ------------------------------------------------------------------ сериализация


def _json_default(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, Sport | StepRole | TargetType | FocusType | WeekStatus
                  | WorkoutStatus | PlanStatus | FactSource | CommandType
                  | CommandStatus | IssuedBy | Verdict):
        return value.value
    raise TypeError(f"не умею сериализовать {type(value).__name__}")


def _session_to_dict(session: ActualSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "sport": session.sport.value,
        "duration_min": session.duration_min,
        "distance_m": session.distance_m,
        "hr_avg": session.hr_avg,
        "hr_max": session.hr_max,
        "hr_zones_min": session.hr_zones_min,
        "aerobic_te": session.aerobic_te,
        "anaerobic_te": session.anaerobic_te,
        "vo2max": session.vo2max,
        "moderate_min": session.moderate_min,
        "vigorous_min": session.vigorous_min,
        "source": session.source.value,
        "external_id": session.external_id,
        "fetched_at": session.fetched_at,
        "linked_workout_id": session.linked_workout_id,
    }


def _session_from_dict(data: dict[str, Any]) -> ActualSession:
    return ActualSession(
        id=data["id"],
        date=date.fromisoformat(data["date"]),
        sport=Sport(data["sport"]),
        duration_min=int(data.get("duration_min", 0)),
        distance_m=float(data.get("distance_m", 0.0)),
        hr_avg=data.get("hr_avg"),
        hr_max=data.get("hr_max"),
        hr_zones_min=data.get("hr_zones_min", {}),
        aerobic_te=data.get("aerobic_te"),
        anaerobic_te=data.get("anaerobic_te"),
        vo2max=data.get("vo2max"),
        moderate_min=int(data.get("moderate_min", 0)),
        vigorous_min=int(data.get("vigorous_min", 0)),
        source=FactSource(data.get("source", "garmin")),
        external_id=data.get("external_id"),
        fetched_at=data.get("fetched_at"),
        linked_workout_id=data.get("linked_workout_id"),
    )


def _week_to_dict(week: Week) -> dict[str, Any]:
    return {
        "id": week.id,
        "plan_id": week.plan_id,
        "season_week": week.season_week,
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "status": week.status.value,
        "focus": week.focus,
        "load_target": week.load_target,
        "requests": [
            {
                "id": r.id, "sport": r.sport.value, "kind": r.kind, "focus": r.focus,
                "duration_min": r.duration_min,
                "equipment_required": list(r.equipment_required),
                "priority": r.priority, "min_slot_quality": r.min_slot_quality,
            }
            for r in week.requests
        ],
        "assignments": [
            {
                "request_id": a.request_id, "slot_id": a.slot_id, "start": a.start,
                "duration_min": a.duration_min,
                "equipment": list(a.equipment_ids), "fit_score": a.fit_score,
            }
            for a in week.assignments
        ],
        "unplaced": [
            {
                "id": r.id, "sport": r.sport.value, "kind": r.kind, "focus": r.focus,
                "duration_min": r.duration_min,
                "equipment_required": list(r.equipment_required),
                "priority": r.priority, "min_slot_quality": r.min_slot_quality,
            }
            for r in week.unplaced
        ],
        "workouts": [_workout_to_dict(w) for w in week.workouts],
        "summary": asdict(week.summary) if week.summary else None,
        "version": week.version,
    }


def _week_from_dict(data: dict[str, Any]) -> Week:
    return Week(
        id=data["id"],
        plan_id=data["plan_id"],
        season_week=int(data["season_week"]),
        start=date.fromisoformat(data["start"]),
        end=date.fromisoformat(data["end"]),
        status=WeekStatus(data.get("status", "proposed")),
        focus=data.get("focus"),
        load_target=data.get("load_target", {}),
        requests=[_request_from_dict(r) for r in data.get("requests", [])],
        assignments=[
            Assignment(
                request_id=a["request_id"], slot_id=a["slot_id"], start=a["start"],
                duration_min=int(a["duration_min"]),
                equipment_ids=tuple(a.get("equipment", [])),
                fit_score=a.get("fit_score"),
            )
            for a in data.get("assignments", [])
        ],
        unplaced=[_request_from_dict(r) for r in data.get("unplaced", [])],
        workouts=[_workout_from_dict(w) for w in data.get("workouts", [])],
        summary=WeekSummary(**data["summary"]) if data.get("summary") else None,
        version=int(data.get("version", 0)),
    )


def _request_from_dict(data: dict[str, Any]) -> Request:
    return Request(
        id=data["id"],
        sport=Sport(data["sport"]),
        kind=data["kind"],
        focus=data["focus"],
        duration_min=int(data["duration_min"]),
        equipment_required=tuple(data.get("equipment_required", [])),
        priority=int(data.get("priority", 0)),
        min_slot_quality=data.get("min_slot_quality"),
    )


def _workout_to_dict(workout: Workout) -> dict[str, Any]:
    return {
        "id": workout.id,
        "request_id": workout.request_id,
        "sport": workout.sport.value,
        "kind": workout.kind,
        "focus": workout.focus,
        "objective": workout.objective,
        "equipment": list(workout.equipment_ids),
        "location": workout.location,
        "time": workout.time,
        "steps": [asdict(step) for step in workout.steps],
        "duration_min": workout.duration_min,
        "priority": workout.priority,
        "status": workout.status.value,
        "rationale": workout.rationale,
        "actual_id": workout.actual_id,
    }


def _workout_from_dict(data: dict[str, Any]) -> Workout:
    steps = []
    for item in data.get("steps", []):
        steps.append(Step(
            id=item["id"], role=StepRole(item["role"]), sport=Sport(item["sport"]),
            target_type=TargetType(item["target_type"]),
            target_value=float(item["target_value"]),
            focus=FocusType(item.get("focus", "none")),
            focus_value=item.get("focus_value", {}),
            group=item.get("group"), round=item.get("round"),
            label=item.get("label"), notes=item.get("notes"),
            duration_min=float(item.get("duration_min", 0.0)),
        ))
    return Workout(
        id=data["id"], request_id=data["request_id"], sport=Sport(data["sport"]),
        kind=data["kind"], focus=data["focus"], objective=data.get("objective", {}),
        equipment_ids=tuple(data.get("equipment", [])),
        location=data.get("location"), time=data.get("time"), steps=steps,
        duration_min=float(data.get("duration_min", 0.0)),
        priority=int(data.get("priority", 0)),
        status=WorkoutStatus(data.get("status", "planned")),
        rationale=data.get("rationale"), actual_id=data.get("actual_id"),
    )


def _season_to_dict(season: Season) -> dict[str, Any]:
    return {
        "id": season.id,
        "horizon_start": season.horizon_start.isoformat(),
        "horizon_end": season.horizon_end.isoformat(),
        "season_week_count": season.season_week_count,
        "version": season.version,
        "slots": [asdict(s) for s in season.slots],
        "equipment": [asdict(e) for e in season.equipment],
        "plan_models": season.plan_models,
        "load_model_id": season.load_model_id,
        "plans": [asdict(p) for p in season.plans],
    }


def _season_from_dict(data: dict[str, Any]) -> Season:
    return Season(
        id=data["id"],
        horizon_start=date.fromisoformat(data["horizon_start"]),
        horizon_end=date.fromisoformat(data["horizon_end"]),
        season_week_count=int(data.get("season_week_count", 0)),
        version=int(data.get("version", 0)),
        slots=[Slot(**s) for s in data.get("slots", [])],
        equipment=[Equipment(**e) for e in data.get("equipment", [])],
        plan_models=data.get("plan_models", []),
        load_model_id=data.get("load_model_id"),
        plans=[_plan_from_dict(p) for p in data.get("plans", [])],
    )


def _plan_from_dict(data: dict[str, Any]) -> Plan:
    return Plan(
        id=data["id"],
        status=PlanStatus(data.get("status", "draft")),
        goal=Goal(**data["goal"]),
        period_start=date.fromisoformat(data["period_start"]),
        period_end=date.fromisoformat(data["period_end"]),
        sport_lines=data.get("sport_lines", {}),
        load_budget=data.get("load_budget", {}),
        phase_ids=data.get("phase_ids", []),
        transition=data.get("transition", {}),
    )


def _season_week_of(day: date) -> int:
    """Номер недели сезона от даты. В сезоне неделя начинается 11.10.2026."""
    season_start = date(2026, 10, 11)
    return ((day - season_start).days // 7) + 1


__all__ = ["FileStorage"]
