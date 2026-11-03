"""Тесты предложения недели по правилам методики."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.domain.entities import (
    Athlete,
    Goal,
    LoadModel,
    MacroWeek,
    Plan,
    Season,
    Slot,
    Week,
    Workout,
)
from app.domain.enums import PlanStatus, Sport, TargetType, WeekStatus
from app.domain.methodology import ZONE_REPETITION, ZONE_THRESHOLD
from app.services.week_planner import WeekPlanner
from app.services.week_proposal import (
    build_targets,
    is_race_week,
    macro_from_week,
    plan_from_macro,
    propose_week,
    weeks_to_race,
)

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118), "Z2": (118, 135), "Z3": (136, 150), "Z4": (150, 160),
    "Z5": (160, 168), "Z6": (169, 172), "Z7": (173, 182),
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


def _macro_weeks() -> list[MacroWeek]:
    """Макро-недели сезона — по 6 недель на фазу, как в реальном плане.

    Объём по видам спорта — из макро: неделя собирается из макро-плана
    сезона, а не из самой себя (иначе повторный propose сжимает неделю).
    """
    weeks: list[MacroWeek] = []
    for season_week in range(1, 29):
        phase = 1 if season_week <= 6 else (
            2 if season_week <= 13 else (
                3 if season_week <= 20 else 4))
        phase_id = {1: "run_base", 2: "run_build",
                    3: "run_specific", 4: "run_taper"}[phase]
        weeks.append(MacroWeek(
            season_week=season_week,
            phase_id=phase_id,
            focus="tempo",
            goal_text="Развиваем базу",
            run_km=41.0,
            total_h=6.62,
            sessions_target=7,
            minutes_by_sport={
                "run": 257.0, "bike": 60.0, "swim": 30.0, "ofp": 50.0,
            },
            long_min=56,
            easy_min=159,
            quality_min=42,
        ))
    return weeks


@pytest.fixture
def season() -> Season:
    goal = Goal(
        id="g1",
        discipline="run_10k",
        race_date=date(2027, 4, 18),
        metric_type="time_sec",
        metric_target=2400.0,
        target_friendly="10К за 40:00",
    )
    plan = Plan(
        id="g1",
        status=PlanStatus.ACTIVE,
        goal=goal,
        period_start=date(2026, 10, 11),
        period_end=date(2027, 9, 18),
        macro_weeks=_macro_weeks(),
    )
    return Season(
        id="S1",
        horizon_start=date(2026, 10, 11),
        horizon_end=date(2027, 9, 18),
        season_week_count=49,
        slots=SLOTS,
        plans=[plan],
    )


@pytest.fixture
def make_week():
    """Фабрика недели с макро: бег, вел, плавание и ОФП.

    Номер недели важен: программа Дэниэлса раскладывается по фазам от
    начала плана. Неделя 3 сезона — это фаза 1 (только лёгкий бег), неделя 7 —
    фаза 2 (качественная работа).
    """
    from app.domain.entities import Step
    from app.domain.enums import FocusType, StepRole, TargetType

    def run_step(workout_id: str, minutes: float) -> Step:
        return Step(
            id=f"{workout_id}-s1",
            role=StepRole.WORK,
            sport=Sport.RUN,
            target_type=TargetType.TIME,
            target_value=minutes,
            focus=FocusType.HR,
            focus_value={"zone": "Z2"},
            duration_min=minutes,
        )

    def bike_step(workout_id: str, minutes: float) -> Step:
        return Step(
            id=f"{workout_id}-s1",
            role=StepRole.WORK,
            sport=Sport.BIKE,
            target_type=TargetType.TIME,
            target_value=minutes,
            focus=FocusType.HR,
            focus_value={"zone": "Z2"},
            duration_min=minutes,
        )

    def factory(season_week: int = 7) -> Week:
        workouts = [
            Workout(
                id="w-easy", request_id="r-easy", sport=Sport.RUN, kind="easy",
                focus="Z2", duration_min=90.0, steps=[run_step("w-easy", 90.0)],
            ),
            Workout(
                id="w-long", request_id="r-long", sport=Sport.RUN, kind="long_Z2",
                focus="Z2", duration_min=80.0, steps=[run_step("w-long", 80.0)],
            ),
            Workout(
                id="w-bike", request_id="r-bike", sport=Sport.BIKE,
                kind="stationary_z2", focus="Z2", duration_min=45.0,
                steps=[bike_step("w-bike", 45.0)],
            ),
        ]
        start = date(2026, 10, 11) + __import__("datetime").timedelta(
            days=7 * (season_week - 1)
        )
        return Week(
            id=f"W{season_week}",
            plan_id="g1",
            season_week=season_week,
            start=start,
            end=start + __import__("datetime").timedelta(days=6),
            status=WeekStatus.PROPOSED,
            focus="Развиваем базу",
            load_target={"hours": 6.24, "sessions": 7.0, "distance_m": 35000.0},
            requests=[],
            workouts=workouts,
        )

    return factory


@pytest.fixture
def current_week(make_week) -> Week:
    """Неделя 7 сезона — фаза 2 программы: там есть качественная работа."""
    return make_week(7)


@pytest.fixture
def templates() -> dict:
    """Каталог шаблонов — из справочника пайплайна."""
    import json
    path = Path.home() / "coach" / "state" / "workout_templates.json"
    if not path.exists():
        pytest.skip(f"нет каталога шаблонов: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("templates", {})


@pytest.fixture
def planner() -> WeekPlanner:
    from app.adapters.daniels import load_paces, load_plan

    athlete = Athlete(
        vdot=48.0, hr_zones=HR_ZONES, hr_max=182, rhr=54, lth=164,
    )
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=load_paces(REFERENCE),
        plan=load_plan(REFERENCE),
    )


def test_macro_reads_minutes_and_km(current_week):
    """Макро недели: минуты по видам спорта и километраж бега."""
    macro = macro_from_week(current_week)
    assert macro.minutes[Sport.RUN] == 170
    assert macro.minutes[Sport.BIKE] == 45
    assert macro.run_km == pytest.approx(35.0)
    assert macro.long_min == 80


def test_targets_keep_long_run_and_other_sports(current_week):
    """Запросы: бег с длинным.

    Не беговые виды спорта в цели не входят: их структуру задаёт не Дэниэлс,
    а макро и среда, поэтому они переносятся из текущей недели как есть.
    """
    macro = macro_from_week(current_week)
    targets = build_targets(macro, current_week)
    run = next(t for t in targets if t.sport is Sport.RUN)
    assert run.duration_min == 170
    assert run.long_min == 80
    assert not [t for t in targets if t.sport is Sport.BIKE]


def test_weeks_to_race_from_goal_date(season):
    """Горизонт сезона — от старта сезона до гонки, в неделях до гонки.

    Горизонт **один на весь сезон**: считать его заново от начала каждой
    недели нельзя — к гонке он сжимается, а номер недели сезона растёт,
    и неделя запрашивается за пределами расписания. Расписание программы
    покрывает недели до гонки: неделя гонки — событие, а не тренировка,
    и своей недели программы у неё нет.
    """
    days = (date(2027, 4, 18) - date(2026, 10, 11)).days
    assert weeks_to_race(season, date(2026, 10, 25)) == days // 7
    # Горизонт не зависит от недели, для которой спрашивают.
    assert weeks_to_race(season, date(2026, 10, 11)) == days // 7
    assert weeks_to_race(season, date(2027, 4, 12)) == days // 7


def test_race_week_is_detected(season):
    """Неделя гонки — та, в которую попадает дата гонки.

    Гонка — событие недели, а не тренировка: в ней нет качественной
    работы по программе.
    """
    assert is_race_week(season, date(2027, 4, 18), date(2027, 4, 24))
    assert not is_race_week(season, date(2027, 4, 11), date(2027, 4, 17))


def test_propose_builds_week_with_quality_from_rules(season, current_week, planner):
    """Предложение недели: качественная работа — из правил Дэниэлса."""
    proposed = propose_week(season, current_week, planner)

    kinds = {w.kind for w in proposed.workouts}
    assert "r" in kinds, "есть работа в повторном темпе"
    assert "t" in kinds, "есть работа в пороговом темпе"
    assert proposed.status is WeekStatus.PROPOSED
    proposed.validate()


def test_propose_keeps_non_run_workouts(season, current_week, planner):
    """Не беговые тренировки текущей недели не теряются."""
    proposed = propose_week(season, current_week, planner)
    assert any(w.sport is Sport.BIKE for w in proposed.workouts)


def test_propose_respects_zone_cap(season, current_week, planner):
    """Объём в зоне за неделю — не больше предела правил.

    Предел считается от **недельного километража** — того, что в макро,
    а не от километража, собранного в неделю.
    """
    proposed = propose_week(season, current_week, planner)
    macro = season.plans[0].macro_week(current_week.season_week)
    assert macro is not None
    for zone in (ZONE_REPETITION, ZONE_THRESHOLD):
        total = sum(
            s.target_value
            for w in proposed.workouts
            for s in w.steps
            if s.focus_value.get("daniels_zone") == zone
        )
        # Предел R — 5 % недельного километража; T ограничением не задан.
        if zone == ZONE_REPETITION:
            limit = macro.run_km * 1000.0 * 0.05
            assert total <= limit + 1, (
                f"работа в зоне R {total:.0f} м, предел {limit:.0f} м"
            )


def test_propose_workout_duration_equals_steps_sum(season, current_week, planner):
    """Инвариант I5: длительность тренировки = Σ шагов."""
    proposed = propose_week(season, current_week, planner)
    for workout in proposed.workouts:
        assert workout.duration_min == pytest.approx(
            sum(step.duration_min for step in workout.steps)
        )


def test_propose_keeps_total_run_volume(season, current_week, planner):
    """Объём бега не теряется: качество + длинный + лёгкий = прежний."""
    proposed = propose_week(season, current_week, planner)
    run_minutes = sum(
        w.duration_min for w in proposed.workouts if w.sport is Sport.RUN
    )
    # Качество добавилось, но лёгкая часть уменьшилась на столько же:
    # суммарный бег остаётся в пределах прежнего плюс качество.
    assert run_minutes >= 170.0

# ------------------------------------------------- планирование из макро


def test_week_keeps_its_goal(season, planner):
    """У недели есть своя цель — из макро.

    Цель недели и описание тренировки — разные вещи: неделя говорит
    «Проверяем форму на контрольной точке», а лёгкая пробежка — «Лёгкий
    бег». Без недельной цели экран не показывает, что неделя про что.
    """
    week = plan_from_macro(season, 7, planner)

    assert week.focus, "у недели нет цели"


def test_no_workout_has_day_before_user_places_it(season, planner):
    """До ручной привязки у тренировок нет дня.

    День появляется, когда пользователь кладёт тренировку в окно.
    Пока она висяк — она ни в какой день не стоит, и карточка не должна
    показывать чужой день.
    """
    week = plan_from_macro(season, 7, planner)

    for workout in week.workouts:
        assert "day" not in (workout.objective or {}), \
            f"у непривязанной тренировки {workout.id} не должно быть дня"
        assert workout.time is None, \
            f"у непривязанной тренировки {workout.id} не должно быть времени"


def test_workout_focus_is_not_week_goal(season, planner):
    """Фокус тренировки — не цель недели.

    Цель недели («Проверяем форму на контрольной точке») на всех
    пробежках недели — враньё: карточка лёгкой пробежки говорит, что
    она проверяет форму на контрольной точке. Описание тренировки
    задаёт планировщик по её виду.
    """
    week = plan_from_macro(season, 7, planner)

    week_goal = week.focus or ""
    for workout in week.workouts:
        if workout.kind == "quality":
            continue
        assert workout.focus != week_goal, \
            f"фокус тренировки {workout.id} повторяет цель недели: {week_goal!r}"


def test_easy_run_has_own_focus(season, planner):
    """Лёгкая пробежка называет себя пробежкой, а не целью недели."""
    week = plan_from_macro(season, 7, planner)

    easy = [w for w in week.workouts if w.kind == "easy"]
    assert easy, "в неделе нет лёгких пробежек"
    for workout in easy:
        assert workout.focus, "у лёгкой пробежки нет описания"


def test_plan_from_macro_creates_week(season, planner):
    """Неделя, которой нет в хранилище, собирается из макро-плана.

    Это то, чем пользователь планирует следующую неделю с телефона:
    кнопка «Спланировать неделю» не требует заранее созданной недели.
    """
    week = plan_from_macro(season, 7, planner)
    assert week.season_week == 7
    assert week.status is WeekStatus.PROPOSED
    assert week.workouts, "неделя собралась пустой"
    week.validate()


def test_plan_from_macro_uses_macro_volume(season, planner):
    """Объём недели — из макро-плана сезона.

    Не из самой недели: при повторном propose объём брался из того, что
    уже собрано, и неделя сжималась с каждым нажатием.
    """
    week = plan_from_macro(season, 7, planner)
    run_minutes = sum(
        w.duration_min for w in week.workouts if w.sport is Sport.RUN
    )
    macro = season.plans[0].macro_week(7)
    assert macro is not None
    # Разбивка макро: длинная + качественная + лёгкая.
    expected = macro.long_min + macro.quality_min + macro.easy_min
    assert run_minutes == pytest.approx(expected, abs=2.0), (
        f"бег {run_minutes} мин, разбивка макро {expected} мин"
    )


def test_plan_from_macro_is_stable_on_repeat(season, planner):
    """Повторное планирование даёт тот же объём.

    Петля обратной связи: неделя собирается из макро, а не из себя.
    """
    first = plan_from_macro(season, 7, planner)
    second = plan_from_macro(season, 7, planner)
    assert first.load_target["hours"] == pytest.approx(
        second.load_target["hours"])
    assert len(first.workouts) == len(second.workouts)


def test_long_run_capped_by_rule(season, planner):
    """Длинный бег — не больше 1,5 часа: потолок правила Дэниэлса.

    «25 % недельного километража или 1,5 часа — что меньше». Без
    потолка длинный пробежек растёт с километражом недели.
    """
    week = plan_from_macro(season, 7, planner)
    long_runs = [w for w in week.workouts if w.kind == "long"]
    assert long_runs, "в неделе нет длинного бега"
    for run in long_runs:
        assert run.duration_min <= 90.0


def test_easy_remainder_is_split_into_parts(season, planner):
    """Лёгкий остаток делится на части, а не одна тренировка.

    Правило Дэниэлса: «7 дней в неделю Л-темп». Одна тренировка
    длиной в полнедели не влезает ни в одно окно.
    """
    week = plan_from_macro(season, 7, planner)
    easy = [w for w in week.workouts if w.kind == "easy" and w.sport is Sport.RUN]
    assert len(easy) >= 2, "лёгкий остаток не разделён"


def test_placed_workout_has_a_time(season, planner):
    """У размещённой тренировки есть время — из слота.

    Клиент показывает время тренировки; без размещения его взять
    неоткуда, и экран показывал пустое время. У висяка времени нет —
    он не стоит ни в одном окне.
    """
    week = plan_from_macro(season, 7, planner)
    hanging = {r.id for r in week.unplaced}
    for workout in week.workouts:
        if workout.request_id in hanging:
            continue
        assert workout.time, f"у тренировки {workout.id} нет времени"


def test_other_sports_are_planned_as_sessions(season, planner):
    """Вел, плавание и ОФП — часть недели, и они висяки, как все.

    Их объём известен точно, и они не должны теряться: висяк — это
    не «тренировка не поместилась», а «время выбирает пользователь».
    """
    week = plan_from_macro(season, 7, planner)
    sports = {w.sport for w in week.workouts}
    assert Sport.BIKE in sports
    assert Sport.SWIM in sports
    # Висят все: размещений нет.
    assert week.assignments == [], "планировщик не должен размещать ничего"
    hanging = {r.sport for r in week.unplaced}
    assert hanging == sports, "висят все тренировки недели"


def test_control_point_title_is_russian(season, planner, templates):
    """Название контрольной точки — по-русски.

    Дефект: в карточке стояло «3K time trial» — внутренний код плана.
    Читателю нужны характер теста и дистанция: «Темповый тест 3К».
    """
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test",
        "kind": "quality",
        "title": "3K time trial",
        "session_goal": "Темповый тест 3К",
        "test_type": "pace",
        "distance_m": 3000,
        "pace_min_per_km": "4:40",
        "variant_id": "tt_pace",
    }
    week = plan_from_macro(season, 4, planner, templates)
    quality = [w for w in week.workouts if w.kind == "quality"]
    assert quality, "контрольная точка не стала качественной работой"
    name = (quality[0].objective or {}).get("name") or ""
    assert name == "Темповый тест 3К", f"название теста: {name!r}"
    assert "time trial" not in name.lower(), "в названии остался внутренний код"


def test_control_point_title_for_max_test(season, planner, templates):
    """Тест на максимум — «Тест на максимум 5К»."""
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test",
        "kind": "quality",
        "title": "5K max",
        "session_goal": "Максимум 5К",
        "test_type": "max",
        "distance_m": 5000,
        "pace_min_per_km": "4:30",
        "variant_id": "tt_max",
    }
    week = plan_from_macro(season, 4, planner, templates)
    quality = [w for w in week.workouts if w.kind == "quality"]
    name = (quality[0].objective or {}).get("name") or ""
    assert name == "Тест на максимум 5К", f"название теста: {name!r}"


def test_control_point_is_unplaced(season, planner, templates):
    """Контрольная точка — висяк: время теста выбирает пользователь."""
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test",
        "kind": "quality",
        "title": "3K time trial",
        "session_goal": "Темповый тест 3К",
        "test_type": "pace",
        "distance_m": 3000,
        "pace_min_per_km": "4:40",
        "variant_id": "tt_pace",
    }
    week = plan_from_macro(season, 4, planner, templates)

    assert week.assignments == [], "планировщик не должен размещать ничего"
    quality = [w for w in week.workouts if w.kind == "quality"]
    assert quality[0].time is None, "у непривязанного теста не должно быть времени"
    assert "day" not in (quality[0].objective or {}), \
        "у непривязанного теста не должно быть дня"


def test_control_point_becomes_quality_work(season, planner, templates):
    """Контрольная точка — качественная работа недели.

    В неделе программы, где по правилам Дэниэлса качественной работы
    нет, CP всё равно её создаёт: это проверка формы.
    """
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test",
        "kind": "quality",
        "title": "3K time trial",
        "session_goal": "Темповый тест 3К",
        "test_type": "pace",
        "distance_m": 3000,
        "pace_min_per_km": "4:40",
        "variant_id": "tt_pace",
    }
    week = plan_from_macro(season, 4, planner, templates)
    quality = [w for w in week.workouts if w.kind == "quality"]
    assert quality, "контрольная точка не стала качественной работой"
    # Работа: 15 мин разминки + 3К на 4:40 + 12 мин заминки.
    assert quality[0].duration_min == pytest.approx(15 + 14 + 12, abs=1.0)
    assert quality[0].steps, "у тестовой сессии нет шагов"


def test_control_point_is_inside_run_volume(season, planner, templates):
    """Тестовая сессия — часть недельного километража, а не добавка к нему.

    Иначе неделя раздувается на дистанцию теста. Проверяем по
    километражу: в фазе I недельный бег задан формой недели (55-57 км),
    и тест входит в эти километры, а не добавляется сверху.
    """
    plan = season.plans[0]
    macro = plan.macro_week(4)
    assert macro is not None
    macro.control_point = {
        "id": "cp_test", "kind": "quality", "title": "3K",
        "distance_m": 3000, "pace_min_per_km": "4:40",
        "variant_id": "tt_pace",
    }
    week = plan_from_macro(season, 4, planner, templates)
    run_km = sum(
        float(step.target_value)
        for workout in week.workouts
        if workout.sport is Sport.RUN
        for step in workout.steps
        if step.target_type == TargetType.DISTANCE
    ) / 1000.0
    assert 55.0 <= run_km <= 57.0, (
        f"бег {run_km:.1f} км — форма фазы требует 55-57 км"
    )
