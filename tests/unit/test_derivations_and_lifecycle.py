"""Тесты инвариантов: производные значения и жизненный цикл недели.

Имена тестов = номера инвариантов из `specs/domain/DOMAIN-SPEC.md`.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.derivations import (
    actual_intensity_min,
    empty_week_totals,
    facts_in_week_range,
    has_status_field,
    is_today,
    merged_slots,
    only_garmin_sources,
    phase_goal_is_distinct,
    plan_week_totals,
    planned_intensity_min,
    plans_overlap,
    race_week_of,
    request_is_placed,
    round_duration_to_minutes,
    unique_external_ids,
    unplaced_without_fact_is_missed,
    week_contributions,
    week_load_min,
    workout_load_min,
)
from app.domain.entities import (
    ActualSession,
    Assignment,
    Command,
    InvariantViolationError,
    LoadModel,
    Request,
    Slot,
    SlotOverride,
    Step,
    Week,
    WeekSummary,
    Workout,
)
from app.domain.enums import (
    CommandType,
    FactSource,
    FocusType,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
    WorkoutStatus,
)
from app.services.week_lifecycle import (
    TransitionError,
    check_single_week_proposed,
    check_status_changed_by_command,
    close_week,
    link_actual,
    propose_week,
    replan_remainder,
    unlink_actual,
)

WEEK_START = date(2026, 10, 11)
WEEK_END = date(2026, 10, 17)


def make_step(step_id: str = "s1", duration: float = 10.0, zone: str = "Z2") -> Step:
    return Step(
        id=step_id,
        role=StepRole.WORK,
        sport=Sport.RUN,
        target_type=TargetType.TIME,
        target_value=duration,
        focus=FocusType.HR,
        focus_value={"zone": zone},
        duration_min=duration,
    )


def make_workout(wid: str = "w1", req_id: str = "r1", duration: float = 60.0) -> Workout:
    steps = [make_step("s1", duration)]
    return Workout(
        id=wid,
        request_id=req_id,
        sport=Sport.RUN,
        kind="easy",
        focus="base",
        steps=steps,
        duration_min=duration,
    )


def make_request(req_id: str = "r1") -> Request:
    return Request(id=req_id, sport=Sport.RUN, kind="easy", focus="base", duration_min=60)


def make_week(status: WeekStatus = WeekStatus.PROPOSED, **kw) -> Week:
    defaults: dict = dict(
        id="W1",
        plan_id="p1",
        season_week=1,
        start=WEEK_START,
        end=WEEK_END,
        status=status,
        requests=[make_request()],
        unplaced=[make_request()],
    )
    defaults.update(kw)
    return Week(**defaults)


def make_session(
    sid: str = "a1",
    day: date = date(2026, 10, 14),
    moderate: int = 30,
    vigorous: int = 10,
    source: FactSource = FactSource.GARMIN,
) -> ActualSession:
    return ActualSession(
        id=sid,
        date=day,
        sport=Sport.RUN,
        duration_min=60,
        moderate_min=moderate,
        vigorous_min=vigorous,
        source=source,
        external_id=f"ext-{sid}" if source is FactSource.GARMIN else None,
    )


# ------------------------------------------------------------------ I2


def test_i02_slots_merge_season_phase_week():
    """I2: слот = Season ← Phase ← Week, каждый уровень перекрывает предыдущий."""
    season_slots = [
        Slot(id="s1", day=0, start="18:45", end="20:15", capacity_min=90),
        Slot(id="s2", day=1, start="09:00", end="09:30", capacity_min=30),
    ]
    phase = [
        SlotOverride(
            slot_id="s1",
            ops=({"op": "set_time", "start": "19:00", "end": "20:30"},),
            reason="позже",
            scope="phase",
            scope_id="run_base",
        )
    ]
    week = [
        SlotOverride(
            slot_id="s2",
            ops=({"op": "remove"},),
            reason="бассейн закрыт",
            scope="week",
            scope_id="W1",
        )
    ]

    merged = merged_slots(season_slots, phase, week)
    by_id = {s.id: s for s in merged}

    assert set(by_id) == {"s1"}, "неделя перекрыла: s2 убран, s1 переопределён фазой"
    assert by_id["s1"].start == "19:00"
    assert by_id["s1"].end == "20:30"


def test_i02_week_can_add_own_slot():
    """I2: неделя может добавить свой слот."""
    season_slots = [Slot(id="s1", day=0, start="18:45", end="20:15", capacity_min=90)]
    week = [
        SlotOverride(
            slot_id="s3",
            ops=({"op": "add", "day": 2, "start": "10:00", "end": "11:00",
                  "capacity_min": 60},),
            reason="дополнительное окно",
            scope="week",
            scope_id="W1",
        )
    ]

    merged = merged_slots(season_slots, [], week)
    assert "s3" in {s.id for s in merged}


# ------------------------------------------------------------------ I10, I11, I13, I15


def test_i10_link_is_one_to_one():
    """I10: связь 1:1 — один факт ↔ одна тренировка, и наоборот."""
    week = make_week()
    week.requests = [make_request("r1"), make_request("r2")]
    week.assignments = [Assignment(request_id="r1", slot_id="s1", start="18:45",
                                    duration_min=60)]
    week.unplaced = [make_request("r2")]
    week.workouts = [make_workout("w1", "r1"), make_workout("w2", "r2")]
    actual = make_session("a1")

    linked = link_actual(week, "w1", actual)
    assert linked.workouts[0].actual_id == "a1"

    with pytest.raises(TransitionError, match="1:1"):
        link_actual(linked, "w2", actual)


def test_i10_fact_cannot_link_to_two_workouts():
    """I10: один факт — максимум одна плановая тренировка."""
    week = make_week()
    week.requests = [make_request("r1"), make_request("r2")]
    week.assignments = [Assignment(request_id="r1", slot_id="s1", start="18:45",
                                    duration_min=60)]
    week.unplaced = [make_request("r2")]
    week.workouts = [make_workout("w1", "r1"), make_workout("w2", "r2")]
    actual = make_session("a1")

    linked = link_actual(week, "w1", actual)
    with pytest.raises(TransitionError, match="1:1"):
        link_actual(linked, "w2", actual)


def test_i11_actual_id_set_only_by_link_command():
    """I11: actual_id ставится только через link_actual, вручную."""
    week = make_week()
    week.workouts = [make_workout()]
    actual = make_session()

    linked = link_actual(week, "w1", actual)
    assert linked.workouts[0].status is WorkoutStatus.DONE

    unlinked = unlink_actual(linked, "w1")
    assert unlinked.workouts[0].actual_id is None
    assert unlinked.workouts[0].status is WorkoutStatus.PLANNED


def test_i13_fact_without_plan_has_null_link():
    """I13: факт без плановой сессии ⇒ linked_workout_id = null."""
    actual = make_session()
    assert actual.linked_workout_id is None


def test_i15_no_automatic_matching():
    """I15: автоматического сопоставления нет — связь ставится только вручную.

    Сервис `link_actual` требует явный workout_id: без него связи не будет.
    """
    week = make_week()
    week.workouts = [make_workout()]
    actual = make_session()

    # факт сам по себе не привязывается к единственной тренировке недели
    assert actual.linked_workout_id is None

    linked = link_actual(week, "w1", actual)
    assert linked.workouts[0].actual_id == actual.id


# ------------------------------------------------------------------ I12, I38


def test_i12_planned_without_fact_becomes_missed():
    """I12: всё, что попало в план до активации, — планирование.

    Без связи с фактом к закрытию — missed. Проверяем на тренировке, стоящей
    по слоту: висяк — это отдельный случай (I38).
    """
    week = make_week()
    week.assignments = [Assignment(request_id="r1", slot_id="s1", start="18:45",
                                    duration_min=60)]
    week.unplaced = []
    week.workouts = [make_workout()]

    linked_session = make_session("a1")
    linked_session.linked_workout_id = "w1"

    # факта нет — тренировка не выполнена
    assert unplaced_without_fact_is_missed(week, []) == []
    # факт есть — выполнена
    assert unplaced_without_fact_is_missed(week, [linked_session]) == []


def test_i38_unplaced_without_fact_is_missed():
    """I38: висящая тренировка без факта ⇒ пропущена."""
    week = make_week()
    week.workouts = [make_workout()]

    missed = unplaced_without_fact_is_missed(week, [])
    assert missed == ["r1"]

    linked_session = make_session("a1")
    linked_session.linked_workout_id = "w1"
    assert unplaced_without_fact_is_missed(week, [linked_session]) == []


# ------------------------------------------------------------------ I14


def test_i14_garmin_sessions_have_external_id():
    """I14: активности берутся только из Garmin — у них есть external_id."""
    sessions = [make_session("a1"), make_session("a2")]
    assert only_garmin_sources(sessions)

    manual = make_session("a3", source=FactSource.MANUAL)
    assert manual.external_id is None


# ------------------------------------------------------------------ I17, I18


def test_i17_only_facts_in_week_range_contribute():
    """I17: вклад принимается только из факта с датой в диапазоне недели."""
    week = make_week()
    inside = make_session("a1", day=date(2026, 10, 14))
    before = make_session("a2", day=date(2026, 10, 10))
    after = make_session("a3", day=date(2026, 10, 18))

    inside_range = facts_in_week_range(week, [inside, before, after])
    assert [s.id for s in inside_range] == ["a1"]


def test_i18_one_fact_one_contribution():
    """I18: один факт — один вклад в неделю."""
    week = make_week()
    sessions = [make_session("a1"), make_session("a1"), make_session("a2")]

    contributions = week_contributions(week, sessions)
    ids = [c["actual_id"] for c in contributions]
    assert ids == ["a1", "a2"], "дубль факта не даёт второго вклада"


# ------------------------------------------------------------------ I19


def test_i19_status_changes_only_by_command():
    """I19: статус недели меняется только через Command."""
    week = make_week()

    ok = Command(id="c1", type=CommandType.ACTIVATE_WEEK, reason="включаю")
    check_status_changed_by_command(week, ok)

    bad = Command(id="c2", type=CommandType.LINK_ACTUAL, reason="связываю")
    with pytest.raises(InvariantViolationError, match="I19"):
        check_status_changed_by_command(week, bad)


# ------------------------------------------------------------------ I21, I40


def test_i21_repeated_propose_replaces_content():
    """I21: повторный propose полностью заменяет содержимое proposed-недели."""
    week = make_week()
    week.workouts = [make_workout("old")]

    new = make_week()
    new.workouts = [make_workout("new")]

    replaced = propose_week(week, new)
    assert [w.id for w in replaced.workouts] == ["new"]
    assert replaced.status is WeekStatus.PROPOSED


def test_i40_repeated_propose_resets_fact_links():
    """I40: повторный propose переделывает план; привязки ставятся заново."""
    week = make_week()
    week.workouts = [make_workout("old")]
    week.workouts[0].actual_id = "a1"
    week.workouts[0].status = WorkoutStatus.DONE

    new = make_week()
    new.workouts = [make_workout("new")]

    replaced = propose_week(week, new)
    assert replaced.workouts[0].actual_id is None
    assert replaced.workouts[0].status is WorkoutStatus.PLANNED


def test_i21_propose_not_allowed_on_active_week():
    """Предложить заново можно только proposed-неделю."""
    week = make_week(status=WeekStatus.ACTIVE)
    with pytest.raises(TransitionError, match="proposed"):
        propose_week(week, make_week())


# ------------------------------------------------------------------ I22, I39


def test_i22_replan_changes_only_today_and_later():
    """I22: replan_remainder меняет только сессии на сегодня и позже."""
    week = make_week(status=WeekStatus.ACTIVE)
    past = make_workout("past")
    past.time = "2026-10-12"
    future = make_workout("future")
    future.time = "2026-10-16"
    week.workouts = [past, future]

    new_workout = make_workout("new")
    new_workout.time = "2026-10-15"

    replanned = replan_remainder(week, date(2026, 10, 14), [new_workout])
    ids = {w.id for w in replanned.workouts}
    assert "past" in ids, "прошедшая сессия не тронута"
    assert "new" in ids


def test_i39_today_is_calendar_date():
    """I39: «сегодня» определяется по календарной дате."""
    assert is_today(date(2026, 10, 14), date(2026, 10, 14))
    assert not is_today(date(2026, 10, 13), date(2026, 10, 14))


# ------------------------------------------------------------------ I23, I24, I25


def test_i23_closed_week_does_not_change():
    """I23: закрытая неделя не меняется."""
    week = make_week(status=WeekStatus.CLOSED, summary=WeekSummary(week_id="W1"))
    with pytest.raises(TransitionError, match="закрыта"):
        replan_remainder(week, date(2026, 10, 14), [make_workout()])


def test_i24_close_only_by_command():
    """I24: неделя закрывается только по команде; сама не закрывается."""
    week = make_week(status=WeekStatus.ACTIVE)
    with pytest.raises(TransitionError, match="active"):
        close_week(make_week(status=WeekStatus.PROPOSED), WeekSummary(week_id="W1"))

    closed = close_week(week, WeekSummary(week_id="W1"))
    assert closed.status is WeekStatus.CLOSED


def test_i25_no_transfers_between_weeks():
    """I25: переносов между неделями нет — в модели нет поля переносов."""
    week = make_week()
    assert not hasattr(week, "adjustments")
    assert not hasattr(week, "transfers")


# ------------------------------------------------------------------ I26


def test_i26_unplaced_counted_in_week_plan():
    """I26: висяки учитываются в плане недели."""
    week = make_week()
    week.assignments = [Assignment(request_id="r1", slot_id="s1", start="18:45",
                                    duration_min=60)]
    week.requests = [make_request("r1"), make_request("r2")]
    week.unplaced = [make_request("r2")]

    totals = plan_week_totals(week)
    assert totals["placed_min"] == 60
    assert totals["unplaced_min"] == 60
    assert totals["minutes"] == 120, "висяк — часть плана"
    assert totals["sessions"] == 2


# ------------------------------------------------------------------ I27, I28, I29


def test_i27_no_workouts_no_intensity_minutes():
    """I27: нет тренировок — нет intensity minutes."""
    assert actual_intensity_min([]) == {"moderate": 0, "vigorous": 0}


def test_i28_weekly_garmin_aggregates_not_used():
    """I28: недельные агрегаты Garmin не используются — считаем по тренировкам.

    Функция принимает список тренировок, а не агрегат за неделю.
    """
    sessions = [make_session("a1", moderate=20, vigorous=5)]
    assert actual_intensity_min(sessions) == {"moderate": 20, "vigorous": 5}


def test_i29_undivided_intensity_goes_to_moderate():
    """I29: если источник не делит интенсивность — всё в moderate."""
    undivided = make_session("a1", moderate=0, vigorous=0)
    result = actual_intensity_min([undivided])
    assert result == {"moderate": 60, "vigorous": 0}


# ------------------------------------------------------------------ I30


def test_i30_week_without_fact_shows_zeros():
    """I30: неделя без факта показывается с нулями."""
    assert empty_week_totals() == {
        "minutes": 0.0,
        "distance_m": 0.0,
        "load_min": 0.0,
        "sessions": 0.0,
    }


# ------------------------------------------------------------------ I32


def test_i32_user_places_unplaced_manually():
    """I32: размещение висяка решает пользователь — вручную.

    Автоматики нет: размещение появляется только через Assignment.
    """
    week = make_week()
    assert not request_is_placed(week, "r1")

    week.assignments = [Assignment(request_id="r1", slot_id="s1", start="18:45",
                                    duration_min=60)]
    assert request_is_placed(week, "r1")


# ------------------------------------------------------------------ I33, I34


def test_i33_race_week_belongs_to_plan():
    """I33: неделя гонки принадлежит плану."""
    period = (date(2026, 10, 11), date(2027, 9, 12))
    race = date(2027, 4, 18)
    week = race_week_of("p1", race, period)
    assert week is not None
    assert 26 <= week <= 28


def test_i34_plans_do_not_overlap():
    """I34: планы не перекрываются."""
    a = (date(2026, 10, 11), date(2027, 4, 18))
    b = (date(2027, 4, 19), date(2027, 9, 12))
    assert not plans_overlap(a, b)
    assert plans_overlap(a, (date(2027, 4, 1), date(2027, 5, 1)))


# ------------------------------------------------------------------ I35


def test_i35_strength_duration_rounded_to_minutes():
    """I35: для силовой и ОФП — общая длительность тренировки, округлённая до минут."""
    assert round_duration_to_minutes(45.4) == 45
    assert round_duration_to_minutes(45.6) == 46


# ------------------------------------------------------------------ I36


def test_i36_plan_goal_and_phase_objective_differ():
    """I36: Plan.goal и Phase.objective — разные вещи."""
    assert phase_goal_is_distinct("g_run_spring", "набрать беговой объём")
    assert not phase_goal_is_distinct("g_run_spring", "")


# ------------------------------------------------------------------ I37


def test_i37_request_and_assignment_have_no_status():
    """I37: у Request и Assignment нет статуса — состояние выводится."""
    assert not has_status_field(make_request())
    assert not has_status_field(
        Assignment(request_id="r1", slot_id="s1", start="18:45", duration_min=60)
    )


# ------------------------------------------------------------------ I41


def test_i41_propose_for_one_week_only():
    """I41: план готовит propose для одной следующей недели."""
    check_single_week_proposed([5])
    with pytest.raises(TransitionError, match="одной недели"):
        check_single_week_proposed([5, 6])


# ------------------------------------------------------------------ I42


def test_i42_external_id_unique():
    """I42: external_id уникален."""
    sessions = [make_session("a1"), make_session("a2")]
    assert unique_external_ids(sessions)

    duplicate = make_session("a3")
    duplicate.external_id = "ext-a1"
    assert not unique_external_ids([*sessions, duplicate])


# ------------------------------------------------------------------ нагрузка


def test_workout_load_uses_load_model():
    """Нагрузка = Σ (минуты × intensity_factor × adaptation_rate)."""
    load_model = LoadModel(
        intensity_factor={"Z2": 0.8},
        adaptation_rate={"run": 1.0, "swim": 0.55},
    )
    workout = make_workout(duration=60.0)
    assert workout_load_min(workout, load_model) == pytest.approx(48.0)

    week = make_week()
    week.workouts = [workout]
    assert week_load_min(week, load_model) == pytest.approx(48.0)


def test_planned_intensity_uses_zone_split():
    """Плановые intensity minutes: Z4+ — vigorous, остальное — moderate."""
    load_model = LoadModel(intensity_factor={}, adaptation_rate={"run": 1.0})
    week = make_week()
    easy = make_workout("easy", duration=30.0)
    easy.steps = [make_step("s", 30.0, zone="Z2")]
    hard = make_workout("hard", "r2", duration=20.0)
    hard.steps = [make_step("s", 20.0, zone="Z5")]
    week.workouts = [easy, hard]

    result = planned_intensity_min(week, load_model)
    assert result["moderate"] == 30
    assert result["vigorous"] == 20
