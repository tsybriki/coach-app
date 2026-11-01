"""BFF: маршруты и форматы ответов.

Доменной логики нет. Маршруты переводят HTTP в вызовы портов и сервисов,
ответы — в общий формат `{version, data}` / `{version, error, data}`.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.adapters.fit import parse_fit
from app.api.dependencies import AppContainer, get_container
from app.domain.derivations import preserve_fact_links, week_progress
from app.domain.entities import (
    ActualSession,
    Command,
    Week,
    WeekSummary,
    WorkoutDetail,
)
from app.domain.enums import CommandType, PlanStatus
from app.ports.storage import (
    DuplicateExternalIdError,
    ExternalSourceError,
    StorageBusyError,
    VersionConflictError,
)

router = APIRouter(prefix="/api/v1")


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
    loaded = container.season_repo.load()
    return ok(container, _week_dict(found, sessions, loaded.slots))


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


@router.get("/slots")
def slots(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Окна тренировок — расписание, в которое раскладывается неделя.

    Окна принадлежат среде, а не конкретной неделе: одно и то же окно
    повторяется каждую неделю. Карточка атлета показывает их, чтобы было
    видно, куда вообще можно попасть.
    """
    loaded = container.season_repo.load()
    return ok(container, {"slots": [_slot_dict(s) for s in loaded.slots]})


@router.get("/season")
def season(container: AppContainer = Depends(get_container)) -> JSONResponse:
    """Скелет сезона: фазы, недели макро-плана и загруженные недели.

    Макро-план — весь сезон целиком: что в каждой неделе задумано, до
    всякой раскладки по слотам. Загруженные недели — те, что уже есть в
    хранилище: по ним видно, что закрыто, а что ещё впереди.
    """
    loaded = container.season_repo.load()
    plan = next((p for p in loaded.plans if p.status is PlanStatus.ACTIVE), None)
    stored = {w.season_week: w for w in container.season_repo.weeks()}

    macro_weeks: list[dict[str, Any]] = []
    if plan is not None:
        for entry in plan.macro_weeks:
            week = stored.get(entry.season_week)
            macro_weeks.append({
                "season_week": entry.season_week,
                "phase_id": entry.phase_id,
                "focus": entry.focus,
                "goal_text": entry.goal_text,
                "run_km": entry.run_km,
                "total_h": entry.total_h,
                "sessions_target": entry.sessions_target,
                "deload": entry.deload,
                "status": week.status.value if week else None,
                "has_fact": bool(week and week.summary),
            })

    phases = []
    if plan is not None:
        for phase in plan.phases:
            weeks = [w.season_week for w in plan.macro_weeks
                     if w.phase_id == phase.id]
            phases.append({
                "id": phase.id,
                "objective": phase.objective,
                "focus": phase.focus,
                "week_from": min(weeks) if weeks else None,
                "week_to": max(weeks) if weeks else None,
                "load_range": list(phase.load_range) if phase.load_range else None,
                "volume_range": (list(phase.volume_range)
                                 if phase.volume_range else None),
            })

    return ok(container, {
        "id": loaded.id,
        "horizon": {
            "start": loaded.horizon_start.isoformat(),
            "end": loaded.horizon_end.isoformat(),
            "season_week_count": loaded.season_week_count,
        },
        "plans": [
            {"id": p.id, "status": p.status.value,
             "goal": p.goal.target_friendly,
             "race_date": p.goal.race_date.isoformat(),
             "venue": p.goal.venue}
            for p in loaded.plans
        ],
        "phases": phases,
        "macro_weeks": macro_weeks,
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
        replan_remainder,
        unlink_actual,
    )
    from app.services.week_proposal import (
        plan_from_macro,
    )
    from app.services.week_proposal import (
        propose_week as propose_by_rules,
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

    diff: list[dict[str, Any]] = []

    if command.type is CommandType.PROPOSE_WEEK and week is None:
        # Недели ещё нет в хранилище — она собирается с нуля: объём по
        # видам спорта из макро-плана сезона, качественная работа бега —
        # из правил Дэниэлса, раскладка по слотам — из среды.
        season = container.season_repo.load()
        updated = plan_from_macro(season, season_week, container.planner,
                                  container.methodology_repo.workout_templates())
    elif week is None:
        raise ValueError(f"неделя W{season_week} не найдена")
    elif command.type is CommandType.PROPOSE_WEEK:
        # Неделя предлагается заново по правилам методики: макро берётся
        # из текущей недели, качественная работа — из правил Дэниэлса.
        # Проверка статуса — в сервисе: закрытую и активную неделю
        # предлагать заново нельзя (I23: закрытая неделя не меняется).
        season = container.season_repo.load()
        updated = propose_by_rules(season, week, container.planner,
                                   container.methodology_repo.workout_templates())
    elif command.type is CommandType.ACTIVATE_WEEK:
        updated = activate_week(week)
    elif command.type is CommandType.CLOSE_WEEK:
        # Ритуал закрытия: вытянуть остаток факта → посчитать → записать.
        # Выкачка Garmin может не удаться (нет сети, нет ключа) — тогда
        # закрываем по тому факту, что уже есть: пользователь решил
        # закрыть, и отсутствие выкачки не должно его блокировать.
        _pull_remaining_fact(container, season_week, week)
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
    before = week.status.value if week is not None else "нет"
    diff.append({"path": f"week.W{season_week}", "before": before,
                 "after": updated.status.value})
    return {"status": "applied", "new_version": version, "diff": diff,
            "consequences": {"scope": "local", "affected": [f"W{season_week}"]},
            "warnings": []}


def _pull_remaining_fact(
    container: AppContainer,
    season_week: int,
    week: Week,
) -> list[str]:
    """Вытянуть остаток факта недели перед закрытием.

    Первый шаг ритуала закрытия: «вытянуть остаток факта → сопоставить
    руками → посчитать и записать». Сопоставление — руками, а выкачка
    может быть нечем: Garmin недоступен, ключа нет, сети нет.

    Недоступность источника — не повод отказывать в закрытии: закрываем
    по тому факту, что уже есть, и говорим, что выкачка не удалась.
    Связи пользователя при этом сохраняются.
    """
    try:
        sessions = container.activity_port.pull(week.start, week.end)
    except ExternalSourceError:
        return []

    preserved = preserve_fact_links(
        container.fact_repo.list_for_week(season_week), sessions)
    for session in preserved:
        container.fact_repo.upsert(session)
    return [s.id for s in preserved]


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
        # Версия — та же глобальная, что в снапшоте и в ETag. Если SSE
        # отдаёт версию сезона, клиент видит расхождение и перезагружает
        # данные при каждом событии.
        last = _version(container)
        yield f"data: {json.dumps({'version': last, 'changed': []})}\n\n"
        while True:
            import asyncio

            await asyncio.sleep(25)
            current = _version(container)
            if current != last:
                last = current
                yield f"data: {json.dumps({'version': current, 'changed': []})}\n\n"
            else:
                yield ": heartbeat\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            # Сжатие потока ломает поток: буферизация съедает heartbeat
            # и события приходят пачками вместо сразу.
            "Content-Encoding": "identity",
        },
    )


# ------------------------------------------------------------------ сериализация


def _week_dict(
    week: Week,
    sessions: list[ActualSession] | None = None,
    slots: list[Any] | None = None,
) -> dict[str, Any]:
    # Окно тренировки: слот. Тренировка знает свой слот через размещение
    # запроса, а не напрямую.
    slot_by_id = {s.id: s for s in (slots or [])}
    assignment_by_request = {a.request_id: a for a in week.assignments}

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
            _workout_dict(w, week, slot_by_id, assignment_by_request)
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


def _workout_dict(
    workout: Any,
    week: Week,
    slot_by_id: dict[str, Any],
    assignment_by_request: dict[str, Any],
) -> dict[str, Any]:
    """Тренировка недели — с днём и датой.

    День и дата берутся из окна, в которое тренировка попала: окно
    принадлежит среде, и тренировка без окна (висяк) дня не имеет.
    """
    assignment = assignment_by_request.get(workout.request_id)
    slot = slot_by_id.get(assignment.slot_id) if assignment else None
    day_name, date_iso = _workout_day_date(
        week.start,
        slot.day if slot else None,
        workout.time,
    )
    objective = dict(workout.objective or {})
    # `objective.day` в данных — номер дня (0 — воскресенье). На экране
    # нужен день по-русски, поэтому нормализуем здесь, на границе API.
    objective_day = objective.get("day")
    if isinstance(objective_day, int):
        objective["day"] = _weekday_name(objective_day)
    objective.setdefault("day", day_name)
    objective.setdefault("date", date_iso)
    objective.setdefault("slot_id", slot.id if slot else "")
    return {
        "id": workout.id,
        "request_id": workout.request_id,
        "sport": workout.sport.value,
        "kind": workout.kind,
        "focus": workout.focus,
        "objective": objective,
        "location": workout.location,
        "time": workout.time,
        "day": day_name,
        "date": date_iso,
        "slot_id": slot.id if slot else "",
        "rationale": workout.rationale,
        "duration_min": workout.duration_min,
        "status": workout.status.value,
        "actual_id": workout.actual_id,
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
            for s in workout.steps
        ],
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
        "form": _form_text(profile.form),
        "form_code": profile.form or "",
    }


# Дни недели по-русски. Неделя сезона начинается с воскресенья (вс→сб),
# поэтому `slot.day` = 0 — это воскресенье.
DAY_NAMES = ("ВС", "ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ")

# Состояние атлета — кодом из пайплайна. На экране нужен текст:
# «recovering_after_back_injury» читается как ошибка, а не как состояние.
FORM_NAMES = {
    "recovering_after_back_injury": "Восстановление после травмы спины",
    "fresh": "Форма хорошая",
    "peaking": "Форма на пике",
    "tired": "Усталость",
    "injured": "Травма",
    "unknown": "—",
}


def _form_text(form: str | None) -> str:
    """Состояние атлета по-русски."""
    if not form:
        return "—"
    return FORM_NAMES.get(form, form)


def _slot_dict(slot: Any) -> dict[str, Any]:
    """Окно тренировки — для карточки атлета."""
    day = int(slot.day)
    return {
        "id": slot.id,
        "day": day,
        "day_name": DAY_NAMES[day] if 0 <= day < len(DAY_NAMES) else "",
        "start": slot.start,
        "end": slot.end,
        "capacity_min": slot.capacity_min,
        "equipment_ids": list(slot.equipment_ids),
        "note": slot.note,
    }


def _weekday_name(day: int) -> str:
    """День недели по-русски из номера (0 — воскресенье)."""
    return DAY_NAMES[day] if 0 <= day < len(DAY_NAMES) else ""


def _workout_day_date(
    week_start: date,
    slot_day: int | None,
    slot_start: str | None,
) -> tuple[str, str]:
    """День недели и дата тренировки — по её окну.

    Окно задаёт и день, и время: тренировка без окна (висяк) дня не
    имеет, и показывать ей чужую дату нельзя.
    """
    if slot_day is None or slot_start is None:
        return ("", "")
    day = int(slot_day)
    if not 0 <= day < len(DAY_NAMES):
        return ("", "")
    # Неделя начинается с воскресенья: смещение дня — это сам номер дня.
    offset = day
    day_date = week_start + timedelta(days=offset)
    return (_weekday_name(day), day_date.isoformat())
