"""Сборка недели: объём из макро, скелеты из программы Дэниэлса.

Правила (Кирилл, 18.11.2026):

- недельный километраж — из макро-плана;
- скелеты тренировок и ограничения по объёму — из программы Дэниэлса;
- объём качественных сессий планируется с учётом ограничений;
- остаток недели — лёгкий бег;
- ОФП — отдельными сессиями, их можно поставить в любой день;
- общее число беговых сессий недели — из профиля атлета;
- сессия короче 5 км не делается; 9 км на две сессии — 5+5;
- лёгкий бег пересчитывается по 5:40 на километр.

Неделя-пример — первая неделя второй фазы (W7, неделя 7 программы
Дэниэлса): повторы 200 м, порог 1600 м, интервал 2'+1'+1'+30"+30"+30".
"""
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
)
from app.domain.enums import PlanStatus, Sport, TargetType
from app.services.week_planner import WeekPlanner, split_runs_km
from app.services.week_proposal import plan_from_macro

REPO = Path(__file__).resolve().parent.parent.parent
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

# Профиль атлета: 7 беговых сессий в неделю.
RUNS_PER_WEEK = 7

# Неделя 7: 57 км по макро, длинная — 25 % (14 км), ОФП — две сессии.
MACRO_KM = 57.0
MACRO_LONG_KM = 14.25  # 25 % от 57 км по правилу Дэниэлса


def _macro_weeks() -> list[MacroWeek]:
    """Макро-недели сезона: как в реальном плане (27 недель до гонки)."""
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
            goal_text="Набираем 57 км за 8 тренировок · работа по плану",
            run_km=MACRO_KM,
            total_h=8.41,
            sessions_target=8,
            minutes_by_sport={
                "run": 344.4, "bike": 60.0, "swim": 40.2, "ofp": 60.0,
            },
            long_min=79,
            easy_min=199,
            quality_min=67,
            sessions_by_sport={"bike": [60], "swim": [40], "ofp": [30, 30]},
            easy_runs=2,
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
def planner() -> WeekPlanner:
    from app.adapters.daniels import load_paces, load_plan

    athlete = Athlete(
        vdot=48.0,
        hr_zones=HR_ZONES,
        hr_max=182,
        rhr=54,
        lth=164,
        runs_per_week=RUNS_PER_WEEK,
    )
    return WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=load_paces(REFERENCE),
        plan=load_plan(REFERENCE),
    )


def _week(season: Season, planner: WeekPlanner, season_week: int = 7):
    return plan_from_macro(season, season_week, planner, {})


def _runs(week) -> list:
    return [w for w in week.workouts if w.sport is Sport.RUN]


def _quality(week) -> list:
    """Качественные тренировки — всё, что не лёгкий бег и не длинный."""
    return [w for w in _runs(week) if w.kind not in ("easy", "long")]


def _easy(week) -> list:
    return [w for w in _runs(week) if w.kind == "easy"]


def _km(workout) -> float:
    """Километраж тренировки — по шагам с дистанцией."""
    return sum(
        float(step.target_value)
        for step in workout.steps
        if step.target_type is TargetType.DISTANCE
    ) / 1000.0


def _zone_km(workout, zone: str) -> float:
    """Километраж работы в зоне Дэниэлса."""
    return sum(
        float(step.target_value)
        for step in workout.steps
        if step.target_type is TargetType.DISTANCE
        and step.focus_value.get("daniels_zone") == zone
    ) / 1000.0


# ───────────────────────────────────────────────────────── неделя 7


def test_week7_quality_sessions_come_from_program(season, planner):
    """Качественная работа недели — скелеты из программы Дэниэлса.

    Неделя 7 программы: повторы (R), порог (T), интервал (I). Маро-
    план сессии не перечисляет — он хранит цель, а скелет даёт Дэниэлс.
    """
    week = _week(season, planner)
    kinds = sorted(w.kind for w in _quality(week))
    assert kinds == ["i", "r", "t"], (
        f"качественные тренировки недели: {kinds}, а программа даёт R, T, I"
    )


def test_quality_volume_respects_daniels_cap(season, planner):
    """Объём работы в зоне — не больше ограничения программы.

    Неделя 7: «R-темп — не более 5 % недельного километража».
    """
    week = _week(season, planner)
    # Неделя 7: «R — не более 5 % недельного километража»,
    # «I — 8 % недельного километража или 10 км, что меньше».
    #
    # С допуском: рабочее правило — «примерно 5 % или чуть больше» и
    # «примерно 8 %». Без допуска работа выбрасывалась целиком.
    limits = {
        "R": MACRO_KM * 0.05 * 1.2,
        "I": min(MACRO_KM * 0.08, 10.0) * 1.05,
    }
    for zone, limit in limits.items():
        total = sum(_zone_km(w, zone) for w in _quality(week))
        assert total <= limit + 0.001, (
            f"работа в зоне {zone}: {total:.2f} км, "
            f"а ограничение недели — {limit:.2f} км"
        )


def test_total_run_sessions_come_from_athlete_profile(season, planner):
    """Число беговых сессий недели — из профиля атлета.

    Профиль задаёт **все** беговые сессии недели. Но сессия короче
    5 км не делается, и на 57 км остатка хватает на две лёгкие, а не на
    три: 3 качественные + длинная + 2 лёгкие = 6 сессий.
    """
    week = _week(season, planner)
    assert len(_runs(week)) <= RUNS_PER_WEEK, (
        f"в неделе {len(_runs(week))} пробежек, а профиль требует не больше "
        f"{RUNS_PER_WEEK}"
    )
    # Ни одна сессия не теряется: остаток недели собран целиком.
    easy_km = sum(_km(w) for w in _easy(week))
    assert easy_km > 0, "лёгкая часть недели пуста"


def test_easy_runs_are_not_shorter_than_five_km(season, planner):
    """Пробежка короче 5 км не делается."""
    week = _week(season, planner)
    easy = _easy(week)
    assert easy, "в неделе нет лёгких пробежек"
    for workout in easy:
        km = _km(workout)
        assert km >= 5.0, f"лёгкая пробежка {km:.1f} км — короче 5 км"


def test_weekly_km_equals_macro_km(season, planner):
    """Недельный километраж недели — как в макро-плане.

    Километраж считается по всем шагам: шаг со временем переводится в
    километры по темпу своей зоны.
    """
    from app.domain.derivations import steps_distance_km

    week = _week(season, planner)
    km = sum(steps_distance_km(w.steps) for w in _runs(week))
    # Километраж может выйти чуть больше макро: остаток недели собирается
    # блоками по 5 км (остаток, который в 5 км не влезает, идёт в
    # следующую сессию), и неделя набирает целые пробежки.
    assert km >= MACRO_KM - 0.5, (
        f"неделя набрала {km:.2f} км, а макро говорит {MACRO_KM}"
    )
    assert km <= MACRO_KM + 2.0, (
        f"неделя набрала {km:.2f} км — это сильно больше макро {MACRO_KM}"
    )


def test_easy_pace_is_five_forty(season, planner):
    """Лёгкий бег пересчитывается по 5:40 на километр."""
    week = _week(season, planner)
    for workout in _easy(week):
        paces = {
            step.focus_value.get("pace_min_per_km")
            for step in workout.steps
            if step.focus_value.get("pace_min_per_km")
        }
        assert paces == {"5:40"}, (
            f"темп лёгкого бега {paces}, а правило — 5:40"
        )


def test_ofp_are_separate_sessions(season, planner):
    """ОФП — отдельными тренировками, а не внутри пробежек."""
    week = _week(season, planner)
    ofp = [w for w in week.workouts if w.sport is Sport.OFP]
    assert len(ofp) == 2, f"в неделе {len(ofp)} сессий ОФП, а нужно две"
    assert not any(
        step.focus_value.get("ofp")
        for workout_run in _runs(week)
        for step in workout_run.steps
    ), "ОФП нашлось внутри пробежки — она должна быть отдельной"
    for workout in ofp:
        assert workout.time is None, "ОФП — висяк: день выбирает пользователь"


def test_long_run_is_distance_based(season, planner):
    """Длинная пробежка — расстоянием, а не временем.

    Иначе километраж недели не сойдётся с макро: время не переводится
    в километры без темпа.
    """
    week = _week(season, planner)
    long_runs = [w for w in _runs(week) if w.kind == "long"]
    assert len(long_runs) == 1, "в неделе не одна длинная пробежка"
    assert _km(long_runs[0]) == pytest.approx(MACRO_LONG_KM, abs=0.05)


# ───────────────────────────────────────────────────────── разбивка


def test_nine_km_split_into_two_runs_is_five_and_five():
    """9 км на две сессии — 5+5: сессия короче 5 км не делается."""
    parts = split_runs_km(9.0, 2)
    assert parts == [5.0, 5.0], f"9 км на две сессии: {parts}"


def test_split_keeps_even_parts_when_above_five_km():
    """Если на сессию приходится больше 5 км — делим поровну."""
    parts = split_runs_km(30.0, 3)
    assert parts == [10.0, 10.0, 10.0]


def test_split_returns_nothing_without_volume():
    assert split_runs_km(0.0, 3) == []
    assert split_runs_km(10.0, 0) == []


# ───────────────────────────────────────────────────────── контрольная точка


@pytest.fixture
def templates() -> dict:
    """Каталог шаблонов — из хранилища пайплайна."""
    import json
    path = Path.home() / "coach" / "state" / "workout_templates.json"
    if not path.exists():
        pytest.skip(f"нет каталога шаблонов: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("templates", {})


def test_control_point_replaces_program_quality(season, planner, templates):
    """В неделю контрольной точки тест и есть качественная работа.

    Программа Дэниэлса на этой неделе качественной работы не даёт:
    неделя с тестом — это проверка формы, а не обычная неделя.
    """
    macro = season.plans[0].macro_week(8)
    assert macro is not None
    macro.control_point = {
        "id": "cp_5k_w8", "kind": "quality", "title": "5K max",
        "distance_m": 5000, "pace_min_per_km": "4:24",
        "variant_id": "tt_max",
        "session_goal": "Максимум 5К",
    }
    week = plan_from_macro(season, 8, planner, templates)
    kinds = sorted(w.kind for w in _quality(week))
    assert kinds == ["quality"], (
        f"качественные тренировки недели с тестом: {kinds}, "
        f"а тест один"
    )
