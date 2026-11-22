"""Сценарии над состоянием.

Сервисы связывают правила домена и контракты портов. Они не знают, где лежат
данные: только через порты.

Жизненный цикл недели: `proposed → active → closed`. Все переходы — команды
пользователя, ничего не инициируется само.
"""
from __future__ import annotations

from app.domain.entities import (
    ActualSession,
    Assignment,
    Command,
    InvariantViolationError,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import CommandType, WeekStatus, WorkoutStatus


class TransitionError(Exception):
    """Переход невозможен в текущем состоянии."""


def propose_week(week: Week, new_content: Week) -> Week:
    """I21/I40: повторный propose полностью заменяет содержимое proposed-недели.

    Новый propose вытирает предыдущий: неделю можно предлагать заново, пока она
    не активна. Привязки факта пользователь ставит заново.
    """
    if week.status is not WeekStatus.PROPOSED:
        raise TransitionError(
            f"предложить заново можно только proposed-неделю, а не {week.status}"
        )

    replaced = Week(
        id=week.id,
        plan_id=week.plan_id,
        season_week=week.season_week,
        start=week.start,
        end=week.end,
        status=WeekStatus.PROPOSED,
        focus=new_content.focus,
        load_target=new_content.load_target,
        requests=list(new_content.requests),
        assignments=list(new_content.assignments),
        unplaced=list(new_content.unplaced),
        slot_overrides=list(new_content.slot_overrides),
        # привязки факта сброшены: пользователь ставит их заново
        workouts=[_without_actual(w) for w in new_content.workouts],
        summary=None,
        version=week.version,
    )
    replaced.validate()
    return replaced


def _without_actual(workout: Workout) -> Workout:
    """Сброс привязки факта — при повторном propose она ставится заново."""
    return Workout(
        id=workout.id,
        request_id=workout.request_id,
        sport=workout.sport,
        kind=workout.kind,
        focus=workout.focus,
        objective=workout.objective,
        equipment_ids=workout.equipment_ids,
        location=workout.location,
        time=workout.time,
        steps=workout.steps,
        duration_min=workout.duration_min,
        priority=workout.priority,
        status=WorkoutStatus.PLANNED,
        rationale=workout.rationale,
        actual_id=None,
    )


def activation_blocker(week: Week, earlier: list[Week]) -> str | None:
    """Номер недели, которую надо закрыть до активации этой.

    Активация следующей недели доступна только после закрытия
    предыдущей: пока та не закрыта, активировать нельзя. `None` — можно.

    Возвращается номер недели (`W4`), а не текст: текст собирает тот,
    кто показывает, — клиент или BFF.
    """
    for other in sorted(earlier, key=lambda w: w.season_week):
        if other.season_week >= week.season_week:
            continue
        if other.status is not WeekStatus.CLOSED:
            return f"W{other.season_week}"
    return None


def activate_week(week: Week, earlier: list[Week] | None = None) -> Week:
    """proposed → active. Висяки остаются висять: расписание мягкое.

    I45: активировать можно только после закрытия предыдущей недели.
    Планировать следующую можно и раньше — активировать нельзя.
    """
    if week.status is not WeekStatus.PROPOSED:
        raise TransitionError(f"активировать можно только proposed, а не {week.status}")

    blocker = activation_blocker(week, earlier or [])
    if blocker is not None:
        raise TransitionError(
            f"активировать можно после закрытия недели {blocker}"
        )

    activated = week.copy_with(status=WeekStatus.ACTIVE)
    activated.validate()
    return activated


def close_week(week: Week, summary: WeekSummary) -> Week:
    """active → closed. Саммари пишется и фиксируется.

    I23: закрытая неделя не меняется — после закрытия переходов больше нет.
    I25: переносов между неделями нет — закрываем одну, потом планируем следующую.
    """
    if week.status is not WeekStatus.ACTIVE:
        raise TransitionError(f"закрыть можно только active, а не {week.status}")

    closed = week.copy_with(status=WeekStatus.CLOSED)
    closed.summary = summary
    closed.validate()
    return closed


def replan_remainder(week: Week,
                     actuals: list[ActualSession] | None = None) -> Week:
    """Перепланировать остаток недели: сделанное оставить, остальное — наново.

    Что делает команда (Кирилл): «все тренировки, которым не привязан
    факт, переходят в состояние proposed, неделя приходит назад в
    состояние proposed, и можно поменять все тренировки, которым не
    привязан факт».

    Поэтому деление — **по факту**, а не по дате:

      - тренировка с фактом — выполнена, её не трогаем: факт остаётся
        связан, тренировка остаётся на своём месте;
      - тренировка без факта — не выполнена: она снова планируемая.
        Её запрос уходит в `unplaced` (висяк), размещение снимается, а
        день и окно из карточки убираются — иначе висяк остался бы
        ещё и в списке размещённых.

    Неделя возвращается в `proposed`: дальше работает обычный режим
    propose — ручная правка и активация.

    **План не пересобирается.** Пересборка по правилам создаёт
    тренировки заново, а это ровно то, чего пользователь не просил:
    отвязать тренировки, чтобы двигать их. Побочный эффект пересборки
    был разрушительным — новые тренировки получали те же id, что у
    выполненных (`r7-1…r7-6`, `r7-other-*`), и в неделе оказывалось
    10 тренировок вместо 8, с задвоенными id. А удаление дубликата
    идёт по запросу — и сносило выполненную тренировку вместе с её
    фактом (Кирилл, 22.11.2026).

    Закрытая неделя не перепланируется (I23).
    """
    if week.status is WeekStatus.CLOSED:
        raise TransitionError("закрытая неделя не перепланируется")

    # Выполненное — это тренировка, у которой есть факт. Факт известен
    # с двух сторон: `Workout.actual_id` и обратная ссылка
    # `ActualSession.linked_workout_id` (I44). Стороны могут разъехаться:
    # после удаления дубликата факт помнил тренировку, а тренировка —
    # нет. Делить по одной стороне тогда нельзя: выполненное
    # выглядело невыполненным и отвязывалось вместе со своим фактом
    # (Кирилл, 22.11.2026).
    #
    # Факт — источник истины: он переживает пересборку плана, а
    # `actual_id` у тренировки — нет. Расхождение чинится здесь же:
    # выполненной тренировке возвращается её факт.
    done_by_id = {w.id for w in week.workouts if w.actual_id}
    done_by_fact = {
        session.linked_workout_id
        for session in (actuals or [])
        if session.linked_workout_id
    }
    done_workout_ids = done_by_id | done_by_fact

    # Факт каждой выполненной тренировки — по обеим сторонам связи.
    actual_by_workout: dict[str, str] = {
        w.id: w.actual_id for w in week.workouts if w.actual_id
    }
    for session in (actuals or []):
        if session.linked_workout_id and session.id not in actual_by_workout.values():
            actual_by_workout[session.linked_workout_id] = session.id

    done_request_ids = {
        workout.request_id
        for workout in week.workouts
        if workout.id in done_workout_ids
    }

    # Выполненное — на месте: тренировка, запрос и размещение.
    done_workouts = [
        _as_done(w, actual_by_workout.get(w.id))
        for w in week.workouts
        if w.request_id in done_request_ids
    ]
    done_requests = [r for r in week.requests if r.id in done_request_ids]
    done_assignments = [
        a for a in week.assignments if a.request_id in done_request_ids
    ]

    # Невыполненное — снова на проекте.
    rest_requests = [r for r in week.requests if r.id not in done_request_ids]
    rest_workouts = [_as_plannable(w) for w in week.workouts
                     if w.request_id not in done_request_ids]

    # `unplaced` — это **все запросы без размещения**, а не
    # «невыполненные». Иначе выполненный запрос без размещения
    # выпадает из обеих корзин: его нет ни среди размещённых, ни среди
    # висяков — и инвариант I7 падает («запрос r7-other-3 без
    # размещения не в unplaced»). Такое состояние — после «Предложить
    # заново»: размещения сброшены, а факты помнят свои тренировки
    # (Кирилл, 22.11.2026).
    placed_ids = {a.request_id for a in done_assignments}
    unplaced_requests = [r for r in week.requests if r.id not in placed_ids]

    replanned = week.copy_with(
        status=WeekStatus.PROPOSED,
        requests=done_requests + rest_requests,
        assignments=done_assignments,
        unplaced=unplaced_requests,
        workouts=done_workouts + rest_workouts,
    )
    replanned.validate()
    return replanned


def _as_done(workout: Workout, actual_id: str | None = None) -> Workout:
    """Выполненная тренировка — с фактом и статусом «выполнена».

    Факт возвращается, даже если у тренировки он потерялся: связь
    хранится с обеих сторон (I44), и переплан её чинит.
    """
    return Workout(
        id=workout.id,
        request_id=workout.request_id,
        sport=workout.sport,
        kind=workout.kind,
        focus=workout.focus,
        objective=workout.objective,
        equipment_ids=workout.equipment_ids,
        location=workout.location,
        time=workout.time,
        steps=workout.steps,
        duration_min=workout.duration_min,
        priority=workout.priority,
        status=WorkoutStatus.DONE,
        rationale=workout.rationale,
        actual_id=actual_id or workout.actual_id,
    )


def _as_plannable(workout: Workout) -> Workout:
    """Тренировка без факта — снова планируемая.

    День и окно убираются: тренировка больше не размещена, иначе она
    осталась бы и в списке размещённых, и среди висяков. Статус —
    «запланирована»: она не выполнена и не пропущена, её можно
    перенести или заменить.
    """
    objective = dict(workout.objective or {})
    objective.pop("day", None)
    objective.pop("slot_id", None)
    return Workout(
        id=workout.id,
        request_id=workout.request_id,
        sport=workout.sport,
        kind=workout.kind,
        focus=workout.focus,
        objective=objective,
        equipment_ids=workout.equipment_ids,
        location=workout.location,
        time=workout.time,
        steps=workout.steps,
        duration_min=workout.duration_min,
        priority=workout.priority,
        status=WorkoutStatus.PLANNED,
        rationale=workout.rationale,
        actual_id=None,
    )


def link_actual(week: Week, workout_id: str, actual: ActualSession) -> Week:
    """I9/I10/I11/I15: связь факта и тренировки — только вручную, 1:1.

    Один факт — максимум одна плановая тренировка, и наоборот.
    """
    workouts = [w for w in week.workouts if w.id == workout_id]
    if not workouts:
        raise TransitionError(f"в неделе {week.id} нет тренировки {workout_id}")

    for other in week.workouts:
        if other.id != workout_id and other.actual_id == actual.id:
            raise TransitionError(
                f"факт {actual.id} уже связан с тренировкой {other.id} — связь 1:1"
            )

    updated = week.copy_with()
    for workout in updated.workouts:
        if workout.id == workout_id:
            workout.actual_id = actual.id
            workout.status = WorkoutStatus.DONE
    updated.validate()
    return updated


def link_actual_session(session: ActualSession, workout_id: str) -> ActualSession:
    """Обратная ссылка на факте: факт занят этой тренировкой.

    Без неё факт остаётся «свободным» — и снова предлагается к связыванию.
    Ссылка ставится вручную, как и сама связь (I15).
    """
    session.linked_workout_id = workout_id
    return session


def unlink_actual(week: Week, workout_id: str) -> Week:
    """Разрыв связи факта и тренировки."""
    updated = week.copy_with()
    for workout in updated.workouts:
        if workout.id == workout_id:
            workout.actual_id = None
            if workout.status is WorkoutStatus.DONE:
                workout.status = WorkoutStatus.PLANNED
    updated.validate()
    return updated


def close_week_is_forbidden_after_close(week: Week) -> None:
    """I23/I24: закрытая неделя не меняется; закрытие — только по команде."""
    if week.status is WeekStatus.CLOSED:
        raise TransitionError("неделя уже закрыта")


def place_unplaced(week: Week, request_id: str, slot_id: str,
                   start: str | None = None,
                   day: int | None = None) -> Week:
    """Привязать висяка к окну — вручную, без проверок.

    Расписание мягкое: висяк — это тренировка, которой не нашлось окна,
    и решение о её времени принимает пользователь, а не планировщик.
    Поэтому здесь **нет** валидаций: ни «окно ли свободно», ни «влезает
    ли тренировка по длительности», ни «тот ли это вид спорта».

    Почему так: авто-привязка работает плохо, и любая проверка здесь —
    это ещё один способ сказать пользователю «нельзя». Если он привязал
    тренировку к окну, значит, он так решил.

    Что делаем:
      - запрос уходит из `unplaced` в `assignments` — он размещён;
      - его тренировка получает день и время этого окна.
    """
    request = next((r for r in week.unplaced if r.id == request_id), None)
    if request is None:
        raise TransitionError(
            f"в неделе {week.id} нет висяка {request_id}"
        )
    if not slot_id:
        raise TransitionError("нужно указать окно для привязки")

    updated = week.copy_with(
        unplaced=[r for r in week.unplaced if r.id != request_id],
        assignments=list(week.assignments) + [
            Assignment(
                request_id=request.id,
                slot_id=slot_id,
                start=start or "",
                duration_min=request.duration_min,
            )
        ],
    )

    # Тренировка запроса получает день и время окна: карточка должна
    # показать, в какой день тренировка теперь стоит. День — из нового
    # окна: перенос в другой день обязан менять и день в карточке,
    # иначе тренировка стоит в понедельнике, а подписана средой.
    for workout in updated.workouts:
        if workout.request_id != request_id:
            continue
        objective = dict(workout.objective or {})
        objective["slot_id"] = slot_id
        if day is not None:
            objective["day"] = day
        workout.objective = objective
        if start:
            workout.time = start

    updated.validate()
    return updated


def unplace_request(week: Week, request_id: str) -> Week:
    """Отвязать размещённый запрос: он снова становится висяком.

    Обратная операция к `place_unplaced`: пользователь передумал и
    вернул тренировку в список непривязанных.
    """
    assignment = next((a for a in week.assignments
                       if a.request_id == request_id), None)
    if assignment is None:
        raise TransitionError(
            f"в неделе {week.id} нет размещения для запроса {request_id}"
        )
    request = next((r for r in week.requests if r.id == request_id), None)
    if request is None:
        raise TransitionError(f"в неделе {week.id} нет запроса {request_id}")

    updated = week.copy_with(
        assignments=[a for a in week.assignments
                     if a.request_id != request_id],
        unplaced=list(week.unplaced) + [request],
    )
    for workout in updated.workouts:
        if workout.request_id != request_id:
            continue
        objective = dict(workout.objective or {})
        objective.pop("slot_id", None)
        workout.objective = objective

    updated.validate()
    return updated


def remove_workout(week: Week, workout_id: str,
                   actuals: list[ActualSession] | None = None) -> Week:
    """Удалить тренировку из недели.

    **Только пока неделя не активна.** Активная неделя — это то, что уже
    исполняется: её тренировки привязаны к факту, и удаление тренировки
    порвало бы связь с фактом. Закрытая неделя не меняется вообще (I23).

    Правило: удалять можно у `proposed`-недели. Это ровно то окно, когда
    план ещё можно переделать: пользователь увидел, что тренировка не
    та, и убрал её.

    Удаляются вместе с тренировкой:
      - её запрос (`Request`) — из `requests` и `unplaced`;
      - её размещение (`Assignment`) — из `assignments`.

    Иначе остался бы запрос без тренировки, и неделю нельзя было бы
    собрать заново.
    """
    workout = next((w for w in week.workouts if w.id == workout_id), None)
    if workout is None:
        raise TransitionError(
            f"в неделе {week.id} нет тренировки {workout_id}"
        )

    # Тренировку с фактом удалить нельзя: факт — это сделанная работа,
    # и он не должен теряться вместе с тренировкой.
    #
    # Проверка идёт **до** проверки статуса недели: «к ней привязан
    # факт» — ответ по существу, а «нельзя в активной неделе» — про
    # второстепенное. Раньше удаление шло по `request_id`, и у
    # выполненной тренировки и у дубликата он был один и тот же —
    # удаление дубликата сносило и выполненную (Кирилл, 22.11.2026).
    # Теперь дубликатов нет, но запрет остаётся: страховка от
    # рассинхрона связи.
    # Факт проверяется с обеих сторон связи (I44): и по `actual_id`
    # тренировки, и по обратной ссылке факта. Стороны могут разъехаться
    # — так было в боевой неделе 7: факт помнил тренировку, а у неё
    # `actual_id` был пуст. Проверка только по `actual_id` такую
    # тренировку пропускала, и удаление роняло связь окончательно.
    has_fact = bool(workout.actual_id) or any(
        session.linked_workout_id == workout_id
        for session in (actuals or [])
    )
    if has_fact:
        raise TransitionError(
            f"тренировку {workout_id} нельзя удалить: к ней привязан факт"
        )

    if week.status is not WeekStatus.PROPOSED:
        # Статусы — внутренние (active, closed), пользователю это
        # ничего не говорит. Поэтому по-русски и словами.
        labels = {
            WeekStatus.ACTIVE: "активной",
            WeekStatus.CLOSED: "закрытой",
        }
        raise TransitionError(
            f"удалить тренировку можно только в запланированной неделе, "
            f"а не в {labels.get(week.status, week.status.value)}"
        )

    request_id = workout.request_id

    # Запрос удаляется, только если он больше никому не нужен.
    #
    # Удаление идёт по запросу, а запрос могут делить несколько
    # тренировок — так получалось после пересборки плана, и удаление
    # одной тренировки роняло запрос у другой: инвариант I20
    # («у каждой тренировки есть запрос») оказывался нарушен.
    others_use_request = any(
        w.request_id == request_id
        for w in week.workouts
        if w.id != workout_id
    )

    requests = week.requests
    unplaced = week.unplaced
    assignments = week.assignments
    if not others_use_request:
        requests = [r for r in requests if r.id != request_id]
        unplaced = [r for r in unplaced if r.id != request_id]
        assignments = [a for a in assignments if a.request_id != request_id]

    updated = week.copy_with(
        requests=requests,
        unplaced=unplaced,
        assignments=assignments,
        workouts=[w for w in week.workouts if w.id != workout_id],
    )
    updated.validate()
    return updated


def check_status_changed_by_command(week: Week, command: Command) -> None:
    """I19: статус недели меняется только через Command."""
    if command.type not in (
        CommandType.PROPOSE_WEEK,
        CommandType.ACTIVATE_WEEK,
        CommandType.CLOSE_WEEK,
        CommandType.REPLAN_REMAINDER,
    ):
        raise InvariantViolationError(
            "I19", f"команда {command.type} не может менять статус недели"
        )


def check_single_week_proposed(season_week_numbers: list[int]) -> None:
    """I41: план готовит propose для одной следующей недели."""
    if len(season_week_numbers) > 1:
        raise TransitionError(
            f"propose готовится для одной недели, а передано {len(season_week_numbers)}"
        )


