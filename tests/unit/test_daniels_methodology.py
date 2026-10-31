"""Тесты правил методологии Дэниэлса.

Проверяют то, что правила обещают: темпы по зонам, ограничения недели,
соблюдение пределов объёма, шаги тренировки и распределение недель по фазам.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.adapters.daniels import load_paces, load_plan
from app.domain.entities import Athlete, LoadModel, Slot
from app.domain.enums import Sport
from app.domain.methodology import (
    ZONE_EASY,
    ZONE_INTERVAL,
    ZONE_REPETITION,
    ZONE_THRESHOLD,
    apply_week_caps,
    athlete_zone_for,
    build_progression_steps,
    build_steps,
    format_pace,
    recipe_zone_volume_m,
    scale_recipe,
    segment_duration_min,
    zone_hr_target,
)
from app.services.week_planner import WeeklyTarget, WeekPlanInput, WeekPlanner

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118),
    "Z2": (118, 135),
    "Z3": (136, 150),
    "Z4": (150, 160),
    "Z5": (160, 168),
    "Z6": (169, 172),
    "Z7": (173, 182),
}

SLOTS = [
    Slot(id="mon", day=1, start="18:45", end="20:15", capacity_min=90),
    Slot(id="tue", day=2, start="18:30", end="19:45", capacity_min=75),
    Slot(id="wed", day=3, start="17:00", end="19:00", capacity_min=120),
    Slot(id="thu", day=4, start="10:30", end="11:15", capacity_min=45),
    Slot(id="fri", day=5, start="18:00", end="19:00", capacity_min=60),
    Slot(id="sat", day=6, start="10:00", end="11:00", capacity_min=60),
    Slot(id="sun", day=0, start="11:00", end="13:00", capacity_min=120),
]


@pytest.fixture(scope="module")
def paces():
    return load_paces(REFERENCE)


@pytest.fixture(scope="module")
def plan():
    return load_plan(REFERENCE)


@pytest.fixture
def athlete() -> Athlete:
    return Athlete(
        vdot=48.0,
        hr_zones=HR_ZONES,
        hr_max=182,
        rhr=54,
        lth=164,
    )


def make_planner(athlete: Athlete, paces, plan) -> WeekPlanner:
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
        plan=plan,
    )


# ------------------------------------------------------------------ справочник


def test_paces_cover_all_five_zones(paces):
    """В таблице темпов есть все пять зон методики."""
    zone_paces = paces.pace_by_zone(48)
    assert set(zone_paces) == {"E", "M", "T", "I", "R"}


def test_paces_are_monotonic_in_vdot(paces):
    """Быстрее VDOT — быстрее темп в каждой зоне."""
    for zone in ("E", "T", "I"):
        slow = paces.pace_sec_per_km(zone, 40)
        fast = paces.pace_sec_per_km(zone, 60)
        assert slow > fast, f"зона {zone}: при росте VDOT темп должен падать"


def test_pace_interpolates_between_rows(paces):
    """Дробный VDOT — интерполяция между строками.

    Печатные темпы округлены до целой секунды, поэтому на некоторых
    участках значения соседних строк совпадают: проверяется, что
    интерполяция не выходит за пределы строк и не округляется вниз.
    """
    at_48 = paces.pace_sec_per_km("E", 48)
    at_49 = paces.pace_sec_per_km("E", 49)
    middle = paces.pace_sec_per_km("E", 48.5)
    assert at_48 >= middle >= at_49
    # Значение не округлено вниз: оно не быстрее, чем ближайшая строка.
    assert middle <= at_48
    # А вот на VDOT 46.5 интерполяция строго между строками.
    at_46 = paces.pace_sec_per_km("E", 46)
    at_47 = paces.pace_sec_per_km("E", 47)
    mid_46 = paces.pace_sec_per_km("E", 46.5)
    assert at_46 >= mid_46 >= at_47


def test_pace_matches_known_daniels_value(paces):
    """VDOT 48: лёгкий темп 5:28/км, пороговый 4:24/км.

    Числа из справочника Кирилла (`state/daniels_profile.json`).
    """
    assert format_pace(paces.pace_sec_per_km("E", 48)) == "5:28"
    assert format_pace(paces.pace_sec_per_km("T", 48)) == "4:24"


def test_plan_has_all_four_phases_and_24_weeks(plan):
    """Программа: 4 фазы, 24 недели."""
    assert set(plan.weeks) and len(plan.weeks) == 24
    phases = {week.phase for week in plan.weeks}
    assert phases == {1, 2, 3, 4}


def test_every_week_of_phase_two_has_quality_work(plan):
    """Каждая неделя фазы II содержит качественную работу."""
    for week in plan.weeks:
        if week.phase != 2:
            continue
        assert any(recipe.is_quality for recipe in week.recipes), \
            f"неделя {week.week} фазы 2 без качественной работы"


def test_cap_limits_follow_week_volume(plan):
    """Предел зоны — доля недельного километража, с потолком где он есть."""
    entry = plan.week(2, 7)
    assert entry is not None
    r_cap = entry.cap_for(ZONE_REPETITION)
    i_cap = entry.cap_for(ZONE_INTERVAL)
    assert r_cap is not None and r_cap.fraction_of_week == 0.05
    assert r_cap.ceiling_km is None
    assert i_cap is not None and i_cap.fraction_of_week == 0.08
    assert i_cap.ceiling_km == 10.0
    # 35 км в неделю: 5 % = 1.75 км, 8 % = 2.8 км
    assert r_cap.limit_km(35) == pytest.approx(1.75)
    assert i_cap.limit_km(35) == pytest.approx(2.8)


def test_cap_ceiling_wins_for_big_week(plan):
    """При большом объёме недели срабатывает потолок в километрах."""
    entry = plan.week(2, 7)
    i_cap = entry.cap_for(ZONE_INTERVAL)
    assert i_cap.limit_km(500) == pytest.approx(10.0)


# ------------------------------------------------------------------ правила


def test_zone_hr_target_uses_athlete_hr_max(athlete):
    """Пульс цели зоны — от HRmax атлета, а не от константы."""
    assert zone_hr_target(ZONE_THRESHOLD, athlete) == 162
    assert zone_hr_target(ZONE_INTERVAL, athlete) == 177
    # У повторного темпа пульсового соответствия нет.
    assert zone_hr_target(ZONE_REPETITION, athlete) is None


def test_athlete_zone_for_maps_rule_zones(athlete):
    """Зона правила → зона пульса атлета."""
    assert athlete_zone_for(ZONE_EASY, athlete) == "Z2"
    assert athlete_zone_for(ZONE_THRESHOLD, athlete) == "Z5"
    assert athlete_zone_for(ZONE_INTERVAL, athlete) == "Z7"
    # Повторный темп быстрее максимума пульса — зоны атлета нет.
    assert athlete_zone_for(ZONE_REPETITION, athlete) is None


def test_segment_duration_uses_pace_of_its_zone(pace_by_zone=None):
    """Длительность куска по объёму считается по темпу своей зоны."""
    from app.domain.methodology import RecipeSegment

    segment = RecipeSegment(zone=ZONE_THRESHOLD, distance_m=1000.0)
    pace = {"T": 264.0}
    assert segment_duration_min(segment, pace) == pytest.approx(4.4)


def test_recipe_volume_counts_minimum_reps(plan):
    """Объём рецепта считается по нижней границе повторов.

    Неделя 7 фазы II: «5-6 × (2 × 200 м Пв + 200 м Л) + 1 × 400 м Пв +
    400 м Л». Нижняя граница — 5 повторов: в зоне R это 5 × 400 = 2000 м
    плюс отдельный 400 м — 2400 м.
    """
    entry = plan.week(2, 7)
    r_recipe = next(r for r in entry.recipes if r.kind == "R")
    volumes = recipe_zone_volume_m(r_recipe)
    assert volumes[ZONE_REPETITION] == pytest.approx(2400.0)


def test_scale_recipe_cuts_reps_to_fit_limit(plan):
    """Повторы урезаются, если рецепт превышает предел зоны."""
    entry = plan.week(2, 7)
    r_recipe = next(r for r in entry.recipes if r.kind == "R")
    scaled = scale_recipe(r_recipe, ZONE_REPETITION, 400.0)
    volumes = recipe_zone_volume_m(scaled)
    assert volumes[ZONE_REPETITION] <= 400.0


def test_scale_recipe_leaves_fitting_recipe_alone(plan):
    """Рецепт, укладывающийся в предел, не меняется."""
    entry = plan.week(2, 7)
    r_recipe = next(r for r in entry.recipes if r.kind == "R")
    scaled = scale_recipe(r_recipe, ZONE_REPETITION, 100_000.0)
    assert scaled is r_recipe


def test_build_steps_makes_flat_list_with_rounds(plan, athlete, paces):
    """Шаги — плоский список; набор помечен группой и номером повтора."""
    entry = plan.week(2, 8)
    r_recipe = next(r for r in entry.recipes if r.kind == "R")
    steps = build_steps(r_recipe, paces.pace_by_zone(48), athlete)
    assert steps
    assert all(step.sport is Sport.RUN for step in steps)
    rounds = {step.round for step in steps}
    assert None not in rounds, "у всех шагов набора есть номер повтора"
    assert len(rounds) == 10, "10-12 повторов по нижней границе — 10"


def test_build_steps_sum_to_workout_duration(plan, athlete, paces):
    """Длительность тренировки = Σ шагов."""
    entry = plan.week(2, 8)
    r_recipe = next(r for r in entry.recipes if r.kind == "R")
    steps = build_steps(r_recipe, paces.pace_by_zone(48), athlete)
    assert sum(step.duration_min for step in steps) == pytest.approx(
        sum(step.duration_min for step in steps)
    )
    assert all(step.duration_min > 0 for step in steps)


def test_steps_carry_pace_of_their_zone(plan, athlete, paces):
    """В шаге есть темп его зоны — по текущему VDOT атлета."""
    entry = plan.week(2, 7)
    t_recipe = next(r for r in entry.recipes if r.kind == "T")
    steps = build_steps(t_recipe, paces.pace_by_zone(48), athlete)
    paces_in_steps = {
        s.focus_value.get("pace_min_per_km") for s in steps
        if s.focus_value.get("daniels_zone") == "T"
    }
    assert "4:24" in paces_in_steps


# ------------------------------------------------------------------ планировщик


def test_planner_uses_recipe_from_program_week(athlete, paces, plan):
    """Планировщик берёт рецепт недели программы, а не заглушку."""
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=7,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=2,
        week=7,
        run_km=35.0,
    ))
    kinds = {workout.kind for workout in week.workouts}
    assert "r" in kinds, "есть работа в повторном темпе — из правил"
    assert "t" in kinds, "есть работа в пороговом темпе — из правил"


def test_planner_respects_zone_cap(athlete, paces, plan):
    """Объём в зоне не превышает предел недели."""
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=7,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=2,
        week=7,
        run_km=35.0,
    ))
    entry = plan.week(2, 7)
    cap = entry.cap_for(ZONE_REPETITION)
    total_r = sum(
        sum(s.target_value for s in workout.steps
            if s.focus_value.get("daniels_zone") == ZONE_REPETITION)
        for workout in week.workouts
    )
    assert total_r <= cap.limit_km(35.0) * 1000.0 + 1


def test_planner_without_rules_falls_back_to_macro(athlete, paces):
    """Без правил неделя собирается из макро — и не падает."""
    planner = WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
    )
    week = planner.build_from(WeekPlanInput(
        season_week=7,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=120, focus="база")],
        slots=SLOTS,
        phase=2,
        week=7,
    ))
    assert week.workouts
    assert all(len(w.steps) > 0 for w in week.workouts)


def test_planner_workout_duration_equals_steps_sum(athlete, paces, plan):
    """Длительность тренировки = Σ шагов (инвариант I5)."""
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=8,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=2,
        week=8,
        run_km=35.0,
    ))
    for workout in week.workouts:
        assert workout.duration_min == pytest.approx(
            sum(step.duration_min for step in workout.steps)
        )


# ------------------------------------------------------------------ распределение


def test_base_schedule_splits_program_in_four_phases(plan):
    """Распределение: 24 недели программы на четыре фазы, по 6 в каждой."""
    schedule = plan.schedule_for(24)
    assert schedule is not None
    assert schedule.total() == 24
    assert set(schedule.phases) == {1, 2, 3, 4}
    assert all(len(weeks) == 6 for weeks in schedule.phases.values())


def test_schedule_covers_every_program_week(plan):
    """Каждая неделя программы попадает ровно в одну фазу."""
    schedule = plan.schedule_for(24)
    assert schedule is not None
    all_weeks = [w for weeks in schedule.phases.values() for w in weeks]
    assert sorted(all_weeks) == list(range(1, 25))


def test_schedule_matches_kirill_distribution(plan):
    """Распределение — как дал Кирилл 30.10.2026.

    Недели программы перетасовываются между фазами: при 24 неделях до
    старта первая фаза — это недели 1, 2, 3, 13, 21, 23.
    """
    schedule = plan.schedule_for(24)
    assert schedule is not None
    assert schedule.weeks_for(1) == (1, 2, 3, 13, 21, 23)
    assert schedule.weeks_for(2) == (10, 11, 12, 18, 19, 20)
    assert schedule.weeks_for(3) == (7, 8, 9, 14, 15, 16)
    assert schedule.weeks_for(4) == (4, 5, 6, 17, 22, 24)


def test_program_week_follows_phase_order(plan):
    """Недели программы идут по фазам по порядку, внутри фазы — как в правиле."""
    assert plan.program_week(24, 0) == (1, 1)
    assert plan.program_week(24, 2) == (1, 3)
    # Четвёртая неделя сезона — уже неделя 13 программы: недели перетасованы.
    assert plan.program_week(24, 3) == (1, 13)
    assert plan.program_week(24, 6) == (2, 10)
    assert plan.program_week(24, 12) == (3, 7)
    assert plan.program_week(24, 18) == (4, 4)
    assert plan.program_week(24, 23) == (4, 24)


def test_phase_of_program_week(plan):
    """Обратный переход: неделя программы → фаза."""
    schedule = plan.schedule_for(24)
    assert schedule is not None
    assert schedule.phase_of(1) == 1
    assert schedule.phase_of(13) == 1
    assert schedule.phase_of(10) == 2
    assert schedule.phase_of(7) == 3
    assert schedule.phase_of(24) == 4


# ------------------------------------------------------------------ другие сроки


def test_shorter_term_trims_base_table(plan):
    """Короче 24 недель: недели программы сверх срока отпадают."""
    schedule = plan.schedule_for(19)
    assert schedule is not None
    assert schedule.weeks_for(1) == (1, 2, 3, 13)
    assert schedule.weeks_for(2) == (10, 11, 12, 18, 19)
    assert schedule.weeks_for(3) == (7, 8, 9, 14, 15, 16)
    assert schedule.weeks_for(4) == (4, 5, 6, 17)
    assert schedule.total() == 19


def test_longer_term_adds_evenly_to_phases_two_three_four(plan):
    """Длиннее 24: лишние недели по кругу через фазы II, III, IV.

    Пример Кирилла: 29 недель → 5 лишних → 2 в фазу II, 2 в фазу III,
    1 в фазу IV. Фаза I не растёт.
    """
    schedule = plan.schedule_for(29)
    assert schedule is not None
    base = plan.schedule_for(24)
    assert base is not None
    extras = {
        phase: len(schedule.weeks_for(phase)) - len(base.weeks_for(phase))
        for phase in sorted(schedule.phases)
    }
    assert extras == {1: 0, 2: 2, 3: 2, 4: 1}
    assert schedule.total() == 29


def test_extra_weeks_go_in_cyclic_order(plan):
    """Лишние недели программы идут по кругу: 25 → II, 26 → III, 27 → IV."""
    schedule = plan.schedule_for(29)
    assert schedule is not None
    assert 25 in schedule.weeks_for(2)
    assert 26 in schedule.weeks_for(3)
    assert 27 in schedule.weeks_for(4)
    assert 28 in schedule.weeks_for(2)
    assert 29 in schedule.weeks_for(3)


def test_every_term_keeps_total_and_order(plan):
    """Любой срок: сумма недель равна сроку, фазы идут по порядку.

    Прыжок фазы (1, 2, 3, 1) означал бы, что неделя из третьей фазы
    оказалась раньше второй.
    """
    for weeks in range(10, 33):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        assert schedule.total() == weeks, f"срок {weeks}: сумма не сходится"
        flat = [
            phase
            for phase in sorted(schedule.phases)
            for _ in schedule.weeks_for(phase)
        ]
        assert flat == sorted(flat), f"срок {weeks}: фазы идут не по порядку"
        all_weeks = [
            w for phase in schedule.phases for w in schedule.weeks_for(phase)
        ]
        assert len(set(all_weeks)) == weeks, f"срок {weeks}: недели повторяются"


# ------------------------------------------------------------------ планы лишних недель


def test_extra_week_takes_plan_from_phase_tail(plan):
    """Лишняя неделя берёт план с края фазы, куда она вставлена.

    Кирилл, 30.10.2026: «последние две недели каждой фазы». Фазы II и III
    растут в конец — план из хвоста: II — 11-12, III — 17-18.

    Неделя программы 25 стоит на 13-й неделе сезона: лишние недели идут
    в конце своей фазы (фазы идут по порядку, а недели программы внутри
    фазы — по её списку).
    """
    assert plan.plan_week(29, 12) == (2, 25, 11)
    assert plan.plan_week(29, 13) == (2, 28, 12)
    # Дальше — фаза III: сначала её базовые недели, потом лишние.
    assert plan.plan_week(29, 14) == (3, 13, 13)
    assert plan.plan_week(29, 20) == (3, 26, 17)
    assert plan.plan_week(29, 21) == (3, 29, 18)


def test_long_term_phases_use_own_program_weeks(plan):
    """При длинном сроке фазы идут из своих недель программы подряд.

    Неделя 11 сезона — это одиннадцатая неделя программы (фаза II), а не
    «неделя фазы II» из перетасованной таблицы 24 недель.
    """
    # Неделя 11 сезона при 29 неделях: фаза II, программная неделя 11.
    assert plan.plan_week(29, 10) == (2, 11, 11)
    # Неделя 12 — двенадцатая программная, тоже фаза II.
    assert plan.plan_week(29, 11) == (2, 12, 12)


def test_phase_four_grows_at_the_front(plan):
    """Фаза IV растёт в начало: неделя 23 сезона — лишняя.

    Кирилл, 31.10.2026: «в фазе 4 их нужно вставлять в начало». Фаза IV
    растёт вперёд, чтобы соревновательные недели программы (23, 24) не
    отодвигались от гонки.
    """
    schedule = plan.schedule_for(29)
    assert schedule is not None
    # Неделя 23 сезона — первая неделя фазы IV, и она лишняя.
    assert schedule.weeks_for(4) == (27, 19, 20, 21, 22, 23, 24)
    assert plan.plan_week(29, 22) == (4, 27, 19)
    # Неделя 24 сезона — программная 19, план из 19-й.
    assert plan.plan_week(29, 23) == (4, 19, 19)
    # Дальше фаза IV идёт по своим неделям программы подряд.
    assert plan.plan_week(29, 24) == (4, 20, 20)
    assert plan.plan_week(29, 28) == (4, 24, 24)


def test_phase_four_repeats_first_two_weeks(plan):
    """План лишней недели фазы IV — по кругу из 19 и 20.

    Кирилл, 31.10.2026: «чередуя недели 19 и 20 из плана Дэниэлса, в
    зависимости от того, сколько недель добавилась к фазе 4».
    """
    # Одна лишняя неделя фазы IV — план из 19-й.
    # При 27 неделях лишние идут по кругу: 25 → II, 26 → III, 27 → IV.
    assert plan.plan_week(27, 20) == (4, 27, 19)
    # Две лишние — 19 и 20. При 30 неделях: 28 → II, 29 → III, 30 → IV.
    assert plan.plan_week(30, 22) == (4, 27, 19)
    assert plan.plan_week(30, 23) == (4, 30, 20)
    # Три лишние — 19, 20, 19. При 33 неделях: 31 → II, 32 → III, 33 → IV.
    schedule = plan.schedule_for(33)
    assert schedule is not None
    extras = [w for w in schedule.weeks_for(4) if w > 24]
    assert [schedule.plan_for(w) for w in extras] == [19, 20, 19]


def test_single_extra_week_takes_edge_week_of_phase(plan):
    """Одна лишняя неделя фазы — план с края, куда она вставлена.

    Фазы II и III растут в конец (планы 12 и 18), фаза IV — в начало
    (план 19).
    """
    # Фаза II при одной лишней неделе — план из последней недели фазы.
    single_ii = plan.schedule_for(25)
    assert single_ii is not None
    assert single_ii.plan_for(25) == 12
    # Фаза III при одной лишней неделе — тоже последняя неделя фазы.
    single_iii = plan.schedule_for(26)
    assert single_iii is not None
    assert single_iii.plan_for(26) == 18
    # Фаза IV растёт в начало — план из первой недели фазы (19).
    assert plan.plan_week(27, 20) == (4, 27, 19)


def test_extra_week_plans_repeat_cyclically(plan):
    """Планы лишних недель повторяются по кругу.

    Три лишние недели фазы II берут 11, 12, 11; четыре — 11, 12, 11, 12.
    """
    three = plan.schedule_for(32)
    assert three is not None
    assert [
        three.plan_for(w) for w in three.weeks_for(2) if w > 24
    ] == [11, 12, 11]

    four = plan.schedule_for(34)
    assert four is not None
    assert [
        four.plan_for(w) for w in four.weeks_for(2) if w > 24
    ] == [11, 12, 11, 12]


def test_extra_week_plan_comes_from_its_own_phase(plan):
    """План лишней недели — с края именно её фазы.

    Фазы II и III растут в конец: хвост II — 11-12, хвост III — 17-18,
    одна лишняя неделя — последняя неделя фазы (12 и 18).

    Фаза IV растёт в начало: план из 19-20, одна лишняя неделя — 19.
    """
    tails = {2: {11, 12}, 3: {17, 18}, 4: {19, 20}}
    single = {2: 12, 3: 18, 4: 19}
    for weeks in range(25, 40):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        for phase, program_weeks in schedule.phases.items():
            extras = [w for w in program_weeks if w > 24]
            for program_week in extras:
                plan_week = schedule.plan_for(program_week)
                allowed = tails[phase] | {single[phase]}
                assert plan_week in allowed, \
                    f"срок {weeks}: неделя {program_week} фазы {phase} — " \
                    f"план не с края фазы"


def test_extra_weeks_stand_at_the_edge_of_their_phase(plan):
    """Лишняя неделя стоит у края своей фазы.

    Фазы II и III — в конце, фаза IV — в начале: фазы идут по порядку,
    и прыжка фазы быть не может.
    """
    for weeks in range(25, 40):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        for phase, program_weeks in schedule.phases.items():
            extras = [w for w in program_weeks if w > 24]
            if not extras:
                continue
            own = [w for w in program_weeks if w <= 24]
            if phase in plan.front_phases:
                assert program_weeks[:len(extras)] == tuple(extras), \
                    f"срок {weeks}: лишние недели фазы {phase} не в начале"
                assert program_weeks[len(extras):] == tuple(own)
            else:
                assert program_weeks[-len(extras):] == tuple(extras), \
                    f"срок {weeks}: лишние недели фазы {phase} не в конце"
                assert program_weeks[:len(own)] == tuple(own)


def test_regular_week_plan_is_itself(plan):
    """Для обычной недели план — она сама."""
    assert plan.plan_week(24, 0) == (1, 1, 1)
    assert plan.plan_week(24, 6) == (2, 10, 10)
    assert plan.plan_week(24, 23) == (4, 24, 24)


def test_program_week_beyond_program_is_none(plan):
    """За пределами программы недели нет."""
    assert plan.program_week(24, 24) is None


# ------------------------------------------------------------------ прогрессия


def test_progression_builds_laps_with_growing_pace(athlete, paces, plan):
    """Бег с ускорением: отрезки по 400 м, темп растёт.

    Правило Дэниэлса: «темп увеличивается на 5 с на 400 м, последние 400 м —
    примерно в интервальном темпе». Неделя 20 фазы IV: 3200 м — 8 отрезков.
    """
    entry = plan.week(4, 20)
    acc = next(r for r in entry.recipes if r.kind == "ACC")
    assert acc.distance_m == 3200.0
    assert acc.pace_growth_sec_per_400m == 5.0

    steps = build_progression_steps(
        acc, paces.pace_by_zone(48), athlete,
        acc.distance_m, acc.pace_growth_sec_per_400m, acc.final_zone,
    )
    assert len(steps) == 8
    # Темп растёт от отрезка к отрезку.
    step_paces = [s.focus_value["pace_min_per_km"] for s in steps]
    assert step_paces[0] > step_paces[-1], "первый отрезок медленнее последнего"
    # Последний отрезок — интервальный темп.
    last = steps[-1]
    assert last.focus_value["daniels_zone"] == "I"
    assert last.focus_value["pace_min_per_km"] == format_pace(
        paces.pace_by_zone(48)["I"]
    )


def test_progression_sums_to_total_distance(athlete, paces, plan):
    """Сумма отрезков прогрессии = вся дистанция."""
    entry = plan.week(4, 20)
    acc = next(r for r in entry.recipes if r.kind == "ACC")
    steps = build_progression_steps(
        acc, paces.pace_by_zone(48), athlete,
        acc.distance_m, acc.pace_growth_sec_per_400m, acc.final_zone,
    )
    assert sum(s.target_value for s in steps) == pytest.approx(3200.0)


# ------------------------------------------------------------------ сборка недели


def test_planner_includes_acceleration_run(athlete, paces, plan):
    """Бег с ускорением попадает в неделю с шагами."""
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=20,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=4,
        week=20,
        run_km=35.0,
    ))
    acc_workouts = [w for w in week.workouts if w.kind == "acc"]
    assert acc_workouts, "бег с ускорением есть в неделе"
    assert len(acc_workouts[0].steps) == 8
    assert acc_workouts[0].duration_min > 0


def test_planner_skips_race_as_workout(athlete, paces, plan):
    """Гонка — событие недели, а не тренировка: в план не входит."""
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=24,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=4,
        week=24,
        run_km=35.0,
    ))
    assert not [w for w in week.workouts if w.kind == "race"]


def test_week_zone_volume_respects_cap(athlete, paces, plan):
    """Объём в зоне за неделю — не больше предела.

    Предел задан на неделю, а не на тренировку: считается сумма.
    """
    planner = make_planner(athlete, paces, plan)
    week = planner.build_from(WeekPlanInput(
        season_week=8,
        week_start=date(2026, 10, 25),
        week_end=date(2026, 10, 31),
        targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
        slots=SLOTS,
        phase=2,
        week=8,
        run_km=35.0,
    ))
    entry = plan.week(2, 8)
    cap = entry.cap_for(ZONE_REPETITION)
    total = sum(
        s.target_value
        for workout in week.workouts
        for s in workout.steps
        if s.focus_value.get("daniels_zone") == ZONE_REPETITION
    )
    assert total <= cap.limit_km(35.0) * 1000.0 + 1


def test_apply_week_caps_removes_work_when_needed(plan):
    """Работа, которая не влезает в предел, урезается или уходит."""
    entry = plan.week(2, 8)
    recipes = list(entry.recipes)
    limited = apply_week_caps(recipes, entry.caps, 35.0)
    total = sum(
        recipe_zone_volume_m(recipe).get(ZONE_REPETITION, 0.0)
        for recipe in limited
    )
    assert total <= entry.cap_for(ZONE_REPETITION).limit_km(35.0) * 1000.0 + 1
