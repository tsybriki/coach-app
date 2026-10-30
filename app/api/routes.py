"""BFF: маршруты и форматы ответов.

Доменной логики нет. Маршруты переводят HTTP в вызовы портов и сервисов,
ответы — в общий формат `{version, data}` / `{version, error, data}`.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.adapters.fit import parse_fit
from app.api.dependencies import AppContainer, build_container
from app.domain.derivations import preserve_fact_links, week_progress
from app.domain.entities import (
    ActualSession,
    Command,
    Week,
    WeekSummary,
    WorkoutDetail,
)
from app.domain.enums import CommandType
from app.ports.storage import (
    DuplicateExternalIdError,
    ExternalSourceError,
    StorageBusyError,
    VersionConflictError,
)

router = APIRouter(prefix="/api/v1")


def get_container(request: Request) -> AppContainer:
    """Зависимость: собранное приложение.

    Контейнер один на процесс: он держит хранилище и сервисы, которые
    переиспользуются между запросами.
    """
    container = getattr(request.app.state, "container", None)
    if container is None:
        container = build_container()
        request.app.state.container = container
    return container


# ------------------------------------------------------------------ схемы


class CommandIn(BaseModel):
    """Конверт команды от клиента."""

    id: str = Field(min_length=1)
    type: str
    target: dict[str, Any] = Field(default_factory=dict)
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)
    issued_at: str | None = None
    issued_by: str = "user"
    expected_version: int = 0


class BatchIn(BaseModel):
    """Несколько команд подряд. Идемпотентность по id каждой."""

    commands: list[CommandIn]


class NarrateIn(BaseModel):
    """Запрос текстового объяснения."""

    about: str
    diff: list[dict[str, Any]] | None = None


# ------------------------------------------------------------------ ответы


def ok(container: AppContainer, data: Any, status: int = 200) -> JSONResponse:
    """Успех: версия + данные."""
    version = _version(container)
    return JSONResponse(
        status_code=status,
        content={"version": version, "data": data},
        headers={"ETag": f'"{version}"'},
    )


def fail(
    container: AppContainer,
    code: str,
    message: str,
    data: Any = None,
    status: int = 400,
) -> JSONResponse:
    """Ошибка: версия + код + сообщение. Данные — текущий снапшот."""
    version = _version(container)
    return JSONResponse(
        status_code=status,
        content={"version": version, "error": {"code": code, "message": message},
                 "data": data},
        headers={"ETag": f'"{version}"'},
    )


def _version(container: AppContainer) -> int:
    """Глобальная версия состояния — та, что в ответе и в ETag."""
    try:
        return container.storage.version()
    except (ValueError, OSError):
        return 0


# ------------------------------------------------------------------ чтение


@router.get("/snapshot")
def snapshot(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Весь сезон: план + состояние + версия."""
    season = container.season_repo.load()
    return ok(container, {
        "season": {
            "id": season.id,
            "horizon": {
                "start": season.horizon_start.isoformat(),
                "end": season.horizon_end.isoformat(),
                "season_week_count": season.season_week_count,
            },
            "slots": len(season.slots),
            "equipment": len(season.equipment),
            "plans": [
                {
                    "id": p.id,
                    "status": p.status.value,
                    "goal": p.goal.target_friendly,
                    "race_date": p.goal.race_date.isoformat(),
                }
                for p in season.plans
            ],
        },
        "athlete": _athlete_dict(container),
    })


@router.get("/week/{season_week}")
def week(season_week: int, container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Одна неделя."""
    found = container.season_repo.week(season_week)
    if found is None:
        return fail(container, "not_found", f"неделя W{season_week} не найдена",
                    status=404)
    sessions = container.fact_repo.list_for_week(season_week)
    return ok(container, _week_dict(found, sessions))


@router.get("/actual/{season_week}")
def actual(season_week: int, container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Факт недели."""
    sessions = container.fact_repo.list_for_week(season_week)
    return ok(container, {"sessions": [_session_dict(s) for s in sessions]})


@router.get("/weeks")
def weeks(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Список сохранённых недель — скелет без шагов."""
    return ok(container, {
        "weeks": [
            {
                "id": w.id,
                "season_week": w.season_week,
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "status": w.status.value,
            }
            for w in container.season_repo.weeks()
        ]
    })


@router.get("/current-week")
def current_week(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Текущая неделя сезона.

    Считает сервер: клиенту не знать про дату старта сезона. Неделя
    определяется по календарной дате — неделя начинается в воскресенье.
    """
    season = container.season_repo.load()
    today = container.clock.now()
    start = season.horizon_start
    if today < start:
        week = 1
    else:
        week = ((today - start).days // 7) + 1
        week = min(week, season.season_week_count)
    week_start = start + timedelta(days=7 * (week - 1))
    return ok(container, {
        "season_week": week,
        "today": today.isoformat(),
        "start": week_start.isoformat(),
        "end": (week_start + timedelta(days=6)).isoformat(),
    })


@router.get("/detail/{actual_id}")
def detail(actual_id: str,
           container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Подробный разбор выполненной тренировки: агрегаты, отрезки, ряды."""
    found = container.detail_repo.detail(actual_id)
    if found is None:
        return fail(container, "not_found",
                    f"разбор тренировки {actual_id} не загружен", status=404)
    return ok(container, _detail_dict(found))


@router.get("/athlete")
def athlete(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Профиль атлета."""
    return ok(container, _athlete_dict(container))


@router.get("/season")
def season(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Скелет сезона: фазы и недели без деталей."""
    loaded = container.season_repo.load()
    return ok(container, {
        "id": loaded.id,
        "horizon": {
            "start": loaded.horizon_start.isoformat(),
            "end": loaded.horizon_end.isoformat(),
            "season_week_count": loaded.season_week_count,
        },
        "plans": [
            {"id": p.id, "status": p.status.value,
             "goal": p.goal.target_friendly}
            for p in loaded.plans
        ],
    })


# ------------------------------------------------------------------ команды


@router.post("/commands")
def run_command(payload: CommandIn,
                container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Одна команда. Ничего не инициируется само — только по команде."""
    return _execute(payload, container)


@router.post("/commands/batch")
def run_batch(payload: BatchIn,
               container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Несколько команд подряд. Каждая — со своим id, идемпотентность по id."""
    results = [_execute(command, container) for command in payload.commands]
    return ok(container, {"results": [json.loads(bytes(r.body)) for r in results]})


def _execute(payload: CommandIn, container: AppContainer) -> JSONResponse:
    """Выполнить команду: идемпотентность → применение → запись в журнал."""
    existing = container.command_log.get(payload.id)
    if existing is not None:
        # повтор с тем же id — тот же результат, команда не применяется второй раз
        return JSONResponse(
            status_code=200,
            content={"version": existing.get("new_version", 0),
                     "data": {"status": existing.get("status"), "replayed": True}},
        )

    try:
        command_type = CommandType(payload.type)
    except ValueError:
        return fail(container, "invalid_command", f"неизвестный тип команды: {payload.type}")

    command = Command(
        id=payload.id,
        type=command_type,
        target=payload.target,
        args=payload.args,
        reason=payload.reason,
        issued_at=payload.issued_at,
        expected_version=payload.expected_version,
    )

    try:
        result = _apply(command, container)
    except VersionConflictError as error:
        current = container.season_repo.load()
        return fail(container, "version_conflict",
                    f"состояние изменилось: ожидалась версия {error.expected}, "
                    f"сейчас {error.actual}",
                    data={"version": current.version}, status=409)
    except StorageBusyError:
        return fail(container, "busy", "хранилище занято другой записью", status=409)
    except ExternalSourceError as error:
        return fail(container, "degraded",
                    f"внешний источник недоступен: {error.source}", status=503)
    except DuplicateExternalIdError as error:
        return fail(container, "invalid_command", str(error))
    except Exception as error:  # noqa: BLE001 — доменная ошибка → понятный ответ
        return fail(container, "invalid_command", str(error))

    container.command_log.append(command, result)
    return ok(container, result)


def _apply(command: Command, container: AppContainer) -> dict[str, Any]:
    """Применить команду к состоянию. Здесь — только переходы, без файлов."""
    from app.services.week_lifecycle import (
        activate_week,
        close_week,
        link_actual,
        link_actual_session,
        propose_week,
        replan_remainder,
        unlink_actual,
    )

    # Команды, не требующие недели: загрузка факта, разбор FIT и текст
    if command.type is CommandType.IMPORT_FIT:
        # Разбор FIT-файла активности: агрегаты, отрезки, ряды для графика.
        actual_id = str(command.args.get("actual_id", ""))
        fact = container.fact_repo.get(actual_id)
        if fact is None:
            raise ValueError(f"факт {actual_id} не найден")
        if not fact.external_id:
            raise ValueError(f"у факта {actual_id} нет id активности Garmin")
        fit_path = container.fit_port.fit_path_for(fact.external_id)
        if fit_path is None:
            raise ExternalSourceError(
                "garmin", f"нет FIT-файла для активности {fact.external_id}")
        athlete = container.athlete_repo.get()
        detail = parse_fit(
            fit_path,
            hr_max=athlete.hr_max or 182,
            zones=athlete.hr_zones or None,
        )
        detail.actual_id = actual_id
        container.detail_repo.save_detail(detail)
        return {
            "status": "applied",
            "actual_id": actual_id,
            "splits": len(detail.splits),
            "new_version": container.season_repo.load().version,
        }

    if command.type is CommandType.PULL_FACT:
        # Факт тянем за неделю, а не за сегодня: неделя — вс→сб, и
        # тренировка в понедельник ещё не «сегодняшняя».
        season = container.season_repo.load()
        start = season.horizon_start
        today = container.clock.now()
        week_start = start + timedelta(days=7 * (int(command.args.get("season_week", 0)) - 1))
        week_end = week_start + timedelta(days=6)
        if week_start > today:
            week_start = today - timedelta(days=6)
        sessions = container.activity_port.pull(
            week_start, week_end, command.args.get("sport"))
        # Выкачка не должна стирать связи, поставленные пользователем:
        # факт из Garmin приходит без `linked_workout_id`.
        sessions = preserve_fact_links(
            container.fact_repo.list_for_week(
                int(command.args.get("season_week", 0))), sessions)
        for session in sessions:
            container.fact_repo.upsert(session)
        return {
            "status": "applied",
            "pulled": [s.id for s in sessions],
            "skipped": [],
            "new_version": container.season_repo.load().version,
        }

    if command.type is CommandType.NARRATE:
        text = container.narrator_port.explain(str(command.args.get("about", "")))
        return {"status": "applied", "text": text,
                "new_version": container.season_repo.load().version}

    season_week = int(command.args.get("season_week", 0))
    week = container.season_repo.week(season_week)
    if week is None:
        raise ValueError(f"неделя W{season_week} не найдена")

    diff: list[dict[str, Any]] = []

    if command.type is CommandType.PROPOSE_WEEK:
        updated = propose_week(week, week)
    elif command.type is CommandType.ACTIVATE_WEEK:
        updated = activate_week(week)
    elif command.type is CommandType.CLOSE_WEEK:
        sessions = container.fact_repo.list_for_week(season_week)
        assessment = container.assessor.assess(week, sessions)
        updated = close_week(week, assessment.summary)
    elif command.type is CommandType.REPLAN_REMAINDER:
        updated = replan_remainder(week, date.today(), [])
    elif command.type is CommandType.LINK_ACTUAL:
        actual_id = str(command.args.get("actual_id", ""))
        workout_id = str(command.args.get("workout_id", ""))
        actual_session = container.fact_repo.get(actual_id)
        if actual_session is None:
            raise ValueError(f"факт {actual_id} не найден")
        updated = link_actual(week, workout_id, actual_session)
        # Обратная ссылка на факте: без неё факт снова предлагается к связыванию.
        container.fact_repo.upsert(
            link_actual_session(actual_session, workout_id))
    elif command.type is CommandType.UNLINK_ACTUAL:
        workout_id = str(command.args.get("workout_id", ""))
        updated = unlink_actual(week, workout_id)
        # Ссылка снимается с факта, иначе он навсегда остаётся занятым.
        for session in container.fact_repo.list_for_week(season_week):
            if session.linked_workout_id == workout_id:
                session.linked_workout_id = None
                container.fact_repo.upsert(session)
    else:
        raise ValueError(f"команда {command.type} пока не реализована")

    version = container.season_repo.put_week(updated, command.expected_version)
    diff.append({"path": f"week.W{season_week}", "before": week.status.value,
                 "after": updated.status.value})
    return {"status": "applied", "new_version": version, "diff": diff,
            "consequences": {"scope": "local", "affected": [f"W{season_week}"]},
            "warnings": []}


@router.post("/narrate")
def narrate(payload: NarrateIn,
            container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Текстовое объяснение. Нарратор не считает и не применяет."""
    text = container.narrator_port.explain(payload.about, payload.diff)
    return ok(container, {"text": text})


# ------------------------------------------------------------------ события


@router.get("/events")
def events(container: AppContainer = Depends(get_container)) -> StreamingResponse:
    """SSE: изменения версии.

    Односторонний поток «сервер → клиент». Heartbeat каждые 25 секунд —
    чтобы прокси не рвал соединение.
    """
    async def stream() -> AsyncIterator[str]:
        last = container.season_repo.load().version
        yield f"data: {json.dumps({'version': last, 'changed': []})}\n\n"
        while True:
            import asyncio

            await asyncio.sleep(25)
            current = container.season_repo.load().version
            if current != last:
                last = current
                yield f"data: {json.dumps({'version': current, 'changed': []})}\n\n"
            else:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------------------ сериализация


def _week_dict(
    week: Week,
    sessions: list[ActualSession] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": week.id,
        "season_week": week.season_week,
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "status": week.status.value,
        "focus": week.focus,
        "load_target": week.load_target,
        "requests": [
            {"id": r.id, "sport": r.sport.value, "kind": r.kind, "focus": r.focus,
             "duration_min": r.duration_min}
            for r in week.requests
        ],
        "assignments": [
            {"request_id": a.request_id, "slot_id": a.slot_id, "start": a.start,
             "duration_min": a.duration_min}
            for a in week.assignments
        ],
        "unplaced": [
            {"id": r.id, "sport": r.sport.value, "kind": r.kind,
             "duration_min": r.duration_min}
            for r in week.unplaced
        ],
        "workouts": [
            {
                "id": w.id,
                "request_id": w.request_id,
                "sport": w.sport.value,
                "kind": w.kind,
                "focus": w.focus,
                "objective": w.objective,
                "location": w.location,
                "time": w.time,
                "rationale": w.rationale,
                "duration_min": w.duration_min,
                "status": w.status.value,
                "actual_id": w.actual_id,
                "steps": [
                    {
                        "id": s.id,
                        "role": s.role.value,
                        "sport": s.sport.value,
                        "target_type": s.target_type.value,
                        "target_value": s.target_value,
                        "focus": s.focus.value,
                        "focus_value": s.focus_value,
                        "duration_min": s.duration_min,
                        "label": s.label,
                        "notes": s.notes,
                        "group": s.group,
                        "round": s.round,
                    }
                    for s in w.steps
                ],
            }
            for w in week.workouts
        ],
        "summary": _summary_dict(week.summary) if week.summary else None,
    }
    # Факт недели против плана: «N из M». Считается по всем активностям
    # недели — связанным и нет.
    data["progress"] = week_progress(week, sessions or [])
    return data


def _summary_dict(summary: WeekSummary) -> dict[str, Any]:
    return {
        "week_id": summary.week_id,
        "closed_at": summary.closed_at,
        "totals": summary.totals,
        "verdict": summary.verdict,
        "missed": summary.missed,
        "extra": summary.extra,
        "deviations": summary.deviations,
        "intensity": summary.intensity,
        "per_session": summary.per_session,
    }


def _session_dict(session: ActualSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "date": session.date.isoformat(),
        "sport": session.sport.value,
        "duration_min": session.duration_min,
        "distance_m": session.distance_m,
        "hr_avg": session.hr_avg,
        "hr_max": session.hr_max,
        "moderate_min": session.moderate_min,
        "vigorous_min": session.vigorous_min,
        "source": session.source.value,
        "external_id": session.external_id,
        "linked_workout_id": session.linked_workout_id,
    }


def _detail_dict(detail: WorkoutDetail) -> dict[str, Any]:
    """Разбор тренировки в ответе API."""
    return {
        "actual_id": detail.actual_id,
        "duration_s": detail.duration_s,
        "elapsed_s": detail.elapsed_s,
        "distance_m": detail.distance_m,
        "ascent_m": detail.ascent_m,
        "descent_m": detail.descent_m,
        "avg_hr": detail.avg_hr,
        "max_hr": detail.max_hr,
        "avg_cadence": detail.avg_cadence,
        "max_cadence": detail.max_cadence,
        "avg_power_w": detail.avg_power_w,
        "max_power_w": detail.max_power_w,
        "normalized_power_w": detail.normalized_power_w,
        "calories": detail.calories,
        "hr_zone_minutes": {
            zone: round(value, 1)
            for zone, value in detail.hr_zone_minutes.items()
        },
        "cadence_source": detail.cadence_source,
        "power_source": detail.power_source,
        "splits": [
            {
                "index": s.index,
                "duration_s": s.duration_s,
                "distance_m": s.distance_m,
                "avg_hr": s.avg_hr,
                "max_hr": s.max_hr,
                "avg_cadence": s.avg_cadence,
                "avg_speed_mps": s.avg_speed_mps,
                "ascent_m": s.ascent_m,
            }
            for s in detail.splits
        ],
        "series": {
            "hr": [list(point) for point in detail.series_hr],
            "cadence": [list(point) for point in detail.series_cadence],
            "power": [list(point) for point in detail.series_power],
            "distance": [list(point) for point in detail.series_distance],
        },
    }


def _athlete_dict(container: AppContainer) -> dict[str, Any]:
    profile = container.athlete_repo.get()
    return {
        "vdot": profile.vdot,
        "hr_zones": {
            name: {"low": low, "high": high}
            for name, (low, high) in profile.hr_zones.items()
        },
        "hr_max": profile.hr_max,
        "rhr": profile.rhr,
        "lth": profile.lth,
        "weight_kg": profile.weight_kg,
        "injuries": profile.injuries,
        "form": profile.form,
    }
