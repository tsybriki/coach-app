"""Перепланирование остатка недели: план не пересобирается.

Репорт Кирилла (22.11.2026):

  «Сначала после нажатия кнопки перепланировать на главном экране, все
  тренировки можно было снова привязать, несмотря на то, что две уроки
  были сделаны и к ним был привязан факт. Однако выполненные тренировки всё
  ещё отображались выполненными. Таким образом общее количество тренировок
  в неделю стало 10, а не 8. Когда я попробовал удалить дубликат из списка
  планирования, он удалил ещё и сделанную тренировку. При нажатии на
  перепланировать неделю я хочу сбрасывать только те тренировки, у которых
  не привязан факт.»

Три дефекта, все — следствие одного: команда пересобирала неделю по
правилам методики вместо того, чтобы просто отвязать тренировки без
факта.

1. **Пересборка создаёт тренировки с теми же id.** Планировщик даёт
   запросы `r7-1…r7-6`, а выполненные тренировки сохраняют свои `r7-4`,
   `w-ofp-1`. Дальше выполненные возвращаются в пересобранную неделю —
   и id задваиваются. Неделя показывает 10 тренировок вместо 8.

2. **Удаление дубликата убивает выполненную.** Удаление идёт по
   `request_id`, а у выполненной и у дубликата он один и тот же.

3. **Отвязка задевает выполненное.** Раз размещение снимается у всех без
   факта, а у выполненной — по тому же запросу, связь факта рвётся.

Правильное поведение: `replan_remainder` отвязывает от слотов тренировки
без факта и возвращает неделю в `proposed`. План **не пересобирается**:
пользователь меняет дни, а не получает другой план.

Имена тестов = номера инвариантов из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.entities import (
    ActualSession,
    Assignment,
    Request,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FactSource,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
    WorkoutStatus,
)
from app.services.week_lifecycle import TransitionError, replan_remainder


def make_step(step_id: str = "s1", duration: float = 60.0) -> Step:
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=duration,
        duration_min=duration,
    )


def make_workout(wid: str, req_id: str, *, actual_id: str | None = None,
                 kind: str = "easy") -> Workout:
    return Workout(
        id=wid,
        request_id=req_id,
        sport=Sport.RUN,
        kind=kind,
        focus="base",
        objective={"name": "Лёгкий бег", "day": 1, "slot_id": "s1"},
        steps=[make_step()],
        duration_min=60.0,
        actual_id=actual_id,
        status=WorkoutStatus.DONE if actual_id else WorkoutStatus.PLANNED,
    )


def make_request(req_id: str, kind: str = "easy") -> Request:
    return Request(id=req_id, sport=Sport.RUN, kind=kind, focus="base",
                   duration_min=60)


def active_week() -> Week:
    """Активная неделя: две тренировки выполнены, три — нет.

    Идентификаторы — как у настоящей недели 7: беговые тренировки
    `r7-1…r7-6`, не беговые — `r7-other-1…r7-other-4`. Это важно:
    дефект воспроизводится именно с такими id, какие даёт планировщик.
    """
    done_run = make_request("r7-4", "long")
    done_ofp = make_request("r7-other-3", "ofp")
    rest = [
        make_request("r7-1", "r"),
        make_request("r7-2", "t"),
        make_request("r7-3", "i"),
        make_request("r7-5"),
        make_request("r7-6"),
        make_request("r7-other-1", "bike"),
        make_request("r7-other-2", "swim"),
        make_request("r7-other-4", "ofp"),
    ]
    assignments = [
        Assignment(request_id="r7-4", slot_id="win-ВС-1", start="11:00",
                   duration_min=60),
        Assignment(request_id="r7-other-3", slot_id="win-ВС-1", start="11:00",
                   duration_min=60),
        Assignment(request_id="r7-1", slot_id="win-ПН-1", start="18:45",
                   duration_min=60),
        Assignment(request_id="r7-2", slot_id="win-ЧТ-1", start="18:45",
                   duration_min=60),
        Assignment(request_id="r7-3", slot_id="win-СР-1", start="17:00",
                   duration_min=60),
        Assignment(request_id="r7-5", slot_id="win-ВТ-1", start="09:00",
                   duration_min=60),
        Assignment(request_id="r7-6", slot_id="win-СБ-1", start="10:00",
                   duration_min=60),
        Assignment(request_id="r7-other-1", slot_id="win-ЧТ-1", start="18:45",
                   duration_min=60),
        Assignment(request_id="r7-other-2", slot_id="win-ПТ-1", start="18:00",
                   duration_min=60),
        Assignment(request_id="r7-other-4", slot_id="win-СР-1", start="17:00",
                   duration_min=60),
    ]
    workouts = [
        make_workout("w-r7-4", "r7-4", actual_id="a1", kind="long"),
        make_workout("w-ofp-1", "r7-other-3", actual_id="a2", kind="ofp"),
        make_workout("w-r7-1", "r7-1", kind="r"),
        make_workout("w-r7-2", "r7-2", kind="t"),
        make_workout("w-r7-3", "r7-3", kind="i"),
        make_workout("w-r7-5", "r7-5"),
        make_workout("w-r7-6", "r7-6"),
        make_workout("w-bike-1", "r7-other-1", kind="bike"),
        make_workout("w-swim-1", "r7-other-2", kind="swim"),
        make_workout("w-ofp-2", "r7-other-4", kind="ofp"),
    ]
    return Week(
        id="W7",
        plan_id="p1",
        season_week=7,
        start=date(2026, 11, 22),
        end=date(2026, 11, 28),
        status=WeekStatus.ACTIVE,
        requests=[done_run, done_ofp] + rest,
        assignments=assignments,
        workouts=workouts,
    )


# ------------------------------------------------------------------ I22


def test_i22_replan_keeps_exactly_the_same_workouts():
    """I22: переплан не создаёт новых тренировок.

    Ключевое: **число тренировок не меняется**. Пересборка по правилам
    создавала план заново — и в неделе оказывалось 10 тренировок вместо
    8, причём с задвоенными id.
    """
    week = active_week()
    before = [w.id for w in week.workouts]

    replanned = replan_remainder(week)

    assert [w.id for w in replanned.workouts] == before, (
        "переплан изменил состав тренировок — он должен только отвязывать"
    )
    assert len(replanned.workouts) == 10


def test_i22_replan_has_no_duplicate_workout_ids():
    """I22: в неделе не может быть двух тренировок с одним id.

    Дубликат и был виден на экране: «Лёгкий бег + отрезки» дважды в
    один день.
    """
    week = active_week()

    replanned = replan_remainder(week)

    ids = [w.id for w in replanned.workouts]
    assert len(ids) == len(set(ids)), f"дубликаты id тренировок: {ids}"


def test_i22_replan_has_no_duplicate_request_ids():
    """I22: у тренировок не может быть одного request_id.

    Дубликат request_id — прямая причина того, что удаление дубликата
    убивало выполненную тренировку: удаление идёт по запросу.
    """
    week = active_week()

    replanned = replan_remainder(week)

    request_ids = [w.request_id for w in replanned.workouts]
    assert len(request_ids) == len(set(request_ids)), (
        f"дубликаты request_id: {request_ids}"
    )


def test_i22_replan_keeps_done_workout_with_its_fact():
    """I22: выполненная тренировка остаётся на месте и со своим фактом.

    Факт, запрос, размещение и сама тренировка — всё на месте.
    """
    week = active_week()

    replanned = replan_remainder(week)

    done = next(w for w in replanned.workouts if w.id == "w-r7-4")
    assert done.actual_id == "a1"
    assert done.status is WorkoutStatus.DONE
    assert any(a.request_id == "r7-4" for a in replanned.assignments)
    assert "r7-4" in {r.id for r in replanned.requests}


def test_i22_replan_keeps_second_done_workout_with_its_fact():
    """I22: обе выполненные тренировки остаются на месте.

    В репорте — две сделанные тренировки: длинный бег и ОФП. Обе
    должны уцелеть, а не одна.
    """
    week = active_week()

    replanned = replan_remainder(week)

    done_ofp = next(w for w in replanned.workouts if w.id == "w-ofp-1")
    assert done_ofp.actual_id == "a2"
    assert done_ofp.status is WorkoutStatus.DONE
    assert any(a.request_id == "r7-other-3" for a in replanned.assignments)


def test_i22_replan_unplaces_only_workouts_without_fact():
    """I22: отвязываются только тренировки без факта.

    Выполненные остаются привязанными к своим окнам.
    """
    week = active_week()

    replanned = replan_remainder(week)

    placed = {a.request_id for a in replanned.assignments}
    assert placed == {"r7-4", "r7-other-3"}, (
        f"размещены не только выполненные: {placed}"
    )
    unplaced = {r.id for r in replanned.unplaced}
    assert "r7-1" in unplaced
    assert "r7-other-4" in unplaced
    assert "r7-4" not in unplaced
    assert "r7-other-3" not in unplaced


def test_i22_replan_clears_day_of_workout_without_fact():
    """У отвязанной тренировки убирается день: она больше не размещена."""
    week = active_week()

    replanned = replan_remainder(week)

    planned = next(w for w in replanned.workouts if w.id == "w-r7-1")
    assert "day" not in planned.objective
    assert "slot_id" not in planned.objective
    assert planned.status is WorkoutStatus.PLANNED


def test_i22_replan_keeps_day_of_workout_with_fact():
    """У выполненной тренировки день остаётся: она выполнена в этот день."""
    week = active_week()

    replanned = replan_remainder(week)

    done = next(w for w in replanned.workouts if w.id == "w-r7-4")
    assert done.objective.get("day") == 1
    assert done.objective.get("slot_id") == "s1"


def test_i22_replan_returns_week_to_proposed():
    """После переплана неделя снова proposed — её можно править."""
    week = active_week()

    replanned = replan_remainder(week)

    assert replanned.status is WeekStatus.PROPOSED


def test_i22_replan_result_passes_invariants():
    """Результат переплана проходит проверки недели."""
    week = active_week()

    replanned = replan_remainder(week)

    replanned.validate()


def test_i22_replan_result_can_be_activated():
    """После переплана неделю можно активировать — обычный режим."""
    from app.services.week_lifecycle import activate_week

    week = active_week()

    replanned = replan_remainder(week)
    activated = activate_week(replanned)

    assert activated.status is WeekStatus.ACTIVE


def test_i22_replan_is_idempotent():
    """Повторный переплан ничего не ломает.

    Кнопку можно нажать второй раз — неделя уже proposed, висяки уже
    отвязаны. Отвязывать нечего.
    """
    week = active_week()

    once = replan_remainder(week)
    twice = replan_remainder(once)

    assert twice.assignments == once.assignments
    assert {r.id for r in twice.unplaced} == {r.id for r in once.unplaced}
    assert [w.id for w in twice.workouts] == [w.id for w in once.workouts]


# ------------------------------------------------------------------ I39


def test_i39_replan_divides_by_fact_not_by_date():
    """I39: деление — по факту, а не по календарной дате.

    Тренировка «в прошлом» по дате, но без факта, — невыполненная:
    её переплан трогает.
    """
    week = active_week()
    past = make_workout("w-past", "r-past")
    week.workouts.append(past)
    week.requests.append(make_request("r-past"))
    week.assignments.append(
        Assignment(request_id="r-past", slot_id="s3", start="18:45",
                   duration_min=60))

    replanned = replan_remainder(week)

    assert "r-past" in {r.id for r in replanned.unplaced}
    assert not any(a.request_id == "r-past" for a in replanned.assignments)


# ------------------------------------------------------------------ I23


def test_i23_replan_closed_week_is_rejected():
    """I23: закрытая неделя не перепланируется."""
    week = active_week()
    week.status = WeekStatus.CLOSED

    with pytest.raises(TransitionError, match="закрыт"):
        replan_remainder(week)


# ------------------------------------------------- удаление выполненной (I22)


def test_i22_removing_a_workout_with_fact_is_rejected():
    """Тренировку с фактом удалить нельзя.

    Удаление идёт по запросу. Если у выполненной тренировки и у
    дубликата один и тот же запрос, удаление дубликата сносит и её.
    Поэтому удаление выполненной — запрещено: факт не должен теряться.
    """
    from app.services.week_lifecycle import remove_workout

    week = active_week()

    with pytest.raises(TransitionError, match="факт"):
        remove_workout(week, "w-r7-4")


def test_i22_removing_a_workout_with_fact_is_rejected_even_if_proposed():
    """Запрет действует и у proposed-недели.

    Неделя после переплана — proposed, и кнопка удаления там есть.
    Запрет не должен зависеть от статуса недели: факт есть факт.
    """
    from app.services.week_lifecycle import remove_workout

    week = active_week()
    week.status = WeekStatus.PROPOSED

    with pytest.raises(TransitionError, match="факт"):
        remove_workout(week, "w-ofp-1")


# ------------------------------- удаление и обратная ссылка факта (I44)


def test_i44_removing_workout_keeps_request_needed_by_another_workout():
    """Удаление тренировки не уносит запрос, который нужен другой.

    Удаление идёт по запросу. Если у двух тренировок один запрос
    (так получалось при пересборке), удаление одной роняло запрос
    второй — и инвариант I20 («у каждой тренировки есть запрос»)
    оказывался нарушен.
    """
    from app.services.week_lifecycle import remove_workout

    week = active_week()
    week.status = WeekStatus.PROPOSED
    # Второй работник с тем же запросом — как после пересборки.
    twin = make_workout("w-r7-4-dup", "r7-4", kind="long")
    week.workouts.append(twin)

    updated = remove_workout(week, "w-r7-4-dup")

    assert "r7-4" in {r.id for r in updated.requests}, (
        "запрос удалён вместе с тренировкой — у другой тренировки "
        "теперь нет запроса"
    )
    updated.validate()


def test_i44_removing_workout_drops_its_request_when_unused():
    """Запрос удаляется, когда он больше никому не нужен."""
    from app.services.week_lifecycle import remove_workout

    week = active_week()
    week.status = WeekStatus.PROPOSED

    updated = remove_workout(week, "w-r7-1")

    assert "r7-1" not in {r.id for r in updated.requests}
    assert "r7-1" not in {r.id for r in updated.unplaced}
    assert not any(a.request_id == "r7-1" for a in updated.assignments)


# --------------------- факт помнит тренировку, тренировка — нет (I44)


def test_i44_replan_recognizes_done_by_fact_back_link():
    """Выполненной считается и тренировка, которую помнит факт.

    Связь хранится с обеих сторон (I44), но после удаления дубликата
    она разъезжалась: факт помнил тренировку, а тренировка — нет.
    Деление по одному `actual_id` тогда видело «невыполненное» и
    отвязывало сделанную тренировку.

    Факт — источник истины: он переживает пересборку плана, а
    `actual_id` у тренировки — нет.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource

    week = active_week()
    # Тренировка выполнена, но её actual_id пуст — факт помнит её.
    done = next(w for w in week.workouts if w.id == "w-r7-4")
    done.actual_id = None
    done.status = WorkoutStatus.PLANNED
    fact = ActualSession(
        id="a1", date=date(2026, 11, 22), sport=Sport.RUN,
        source=FactSource.GARMIN, duration_min=80, distance_m=14534.0,
        external_id="ext-1", linked_workout_id="w-r7-4",
    )

    replanned = replan_remainder(week, actuals=[fact])

    kept = next(w for w in replanned.workouts if w.id == "w-r7-4")
    assert kept.actual_id == "a1", (
        "факт помнит тренировку, а переплан её отвязал — связь "
        "разъехалась в одну сторону"
    )
    assert kept.status is WorkoutStatus.DONE
    assert any(a.request_id == "r7-4" for a in replanned.assignments)


def test_i44_replan_restores_back_link_of_done_workout():
    """Переплан чинит связь: `actual_id` у выполненной тренировки есть.

    Связь хранится с обеих сторон (I44). Если одна сторона потерялась,
    переплан её восстанавливает — иначе тренировка снова выглядит
    невыполненной при следующем переплане.
    """
    from app.domain.entities import ActualSession
    from app.domain.enums import FactSource

    week = active_week()
    done = next(w for w in week.workouts if w.id == "w-r7-4")
    done.actual_id = None
    done.status = WorkoutStatus.PLANNED
    fact = ActualSession(
        id="a1", date=date(2026, 11, 22), sport=Sport.RUN,
        source=FactSource.GARMIN, duration_min=80, distance_m=14534.0,
        external_id="ext-1", linked_workout_id="w-r7-4",
    )

    replanned = replan_remainder(week, actuals=[fact])

    kept = next(w for w in replanned.workouts if w.id == "w-r7-4")
    assert kept.actual_id == "a1"


def test_i44_replan_without_facts_keeps_actual_id_rule():
    """Без фактов деление остаётся по `actual_id` — как раньше."""
    week = active_week()

    replanned = replan_remainder(week)

    kept = next(w for w in replanned.workouts if w.id == "w-r7-4")
    assert kept.actual_id == "a1"
    assert kept.status is WorkoutStatus.DONE


# ------------- выполненный запрос без размещения (I7)


def test_i22_replan_keeps_done_request_without_assignment_in_unplaced():
    """Выполненный запрос без размещения остаётся в unplaced.

    I7: запрос либо размещён, либо висит. Третий вариант — ни там, ни
    там — нарушение инварианта, и любая следующая команда на неделе
    падает: «запрос r7-other-3 без размещения не в unplaced».

    Случай реальный: после «Предложить заново» размещения сбрасываются,
    а факты помнят свои тренировки. Дальше переплан делит неделю по
    факту: выполненный запрос попадает в «выполненное» (ему не
    полагается размещение) и одновременно выпадает из `unplaced`,
    потому что unplaced собирался из невыполненных.

    Правило: `unplaced` — это **все запросы без размещения**, а не
    «невыполненные». Иначе выполненный без размещения исчезает из
    обеих корзин.
    """
    week = active_week()
    week.status = WeekStatus.PROPOSED
    # Выполненный запрос без размещения — после propose размещения
    # сброшены, а факт помнит тренировку.
    week.assignments = [a for a in week.assignments
                         if a.request_id != "r7-other-3"]
    week.unplaced = [r for r in week.unplaced
                     if r.id != "r7-other-3"]

    replanned = replan_remainder(week, actuals=[
        ActualSession(id="a2", date=date(2026, 11, 22), sport=Sport.OFP,
                      source=FactSource.GARMIN, duration_min=15,
                      distance_m=0.0, external_id="ext-2",
                      linked_workout_id="w-ofp-1"),
    ])

    placed = {a.request_id for a in replanned.assignments}
    unplaced = {r.id for r in replanned.unplaced}
    requests = {r.id for r in replanned.requests}
    assert not (requests - placed - unplaced), (
        f"запросы без размещения и не в unplaced: "
        f"{requests - placed - unplaced}"
    )
    assert "r7-other-3" in unplaced, (
        "выполненный запрос без размещения выпал из unplaced — "
        "инвариант I7 нарушен"
    )


def test_i22_replan_unplaced_is_every_request_without_assignment():
    """unplaced — это все запросы без размещения, а не «невыполненные»."""
    week = active_week()
    week.status = WeekStatus.PROPOSED

    replanned = replan_remainder(week)

    placed = {a.request_id for a in replanned.assignments}
    unplaced = {r.id for r in replanned.unplaced}
    requests = {r.id for r in replanned.requests}
    assert unplaced == requests - placed, (
        "unplaced — не все запросы без размещения"
    )
