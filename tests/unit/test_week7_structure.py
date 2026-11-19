"""Структура качественных сессий недели 7 (первая неделя фазы II).

Правила Кирилла (19.11.2026):

**T1 — работа в повторном темпе.** Серия:
200 м Пв → 200 м трусцой → 200 м Пв → 200 м трусцой → 400 м Пв → 400 м трусцой.
Число серий — так, чтобы объём в повторном темпе был примерно 5 %
недельного километража или чуть больше. Перед — разминка минимум 3 км,
после — заминка минимум 1 км.

**T2 — работа в пороговом темпе.** 5 серий по 1600 м в пороговом темпе
+ 1 минута отдыха. Сначала разминка, потом заминка.

**T3 — работа в интервальном темпе.** Серия:
2 мин И → 1 мин трусцой → 1 мин И → 30 с трусцой → 30 с И → 30 с трусцой.
Объём в интервальном темпе — примерно 8 % недельного километража.
Разминка и заминка.

Правила живут в справочнике (`reference/daniels/training_plan_19_1.txt`
→ `tools/parse_daniels_plan.py` → JSON → `app/domain/methodology.py`).
Здесь проверяется, что правила читаются в том виде, в котором заданы.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.daniels import load_plan
from app.domain.entities import Athlete, LoadModel
from app.domain.methodology import (
    ZONE_EASY,
    ZONE_INTERVAL,
    ZONE_REPETITION,
    ZONE_THRESHOLD,
    recipe_zone_volume_m,
)
from app.services.week_planner import WeekPlanner

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118), "Z2": (118, 135), "Z3": (136, 150), "Z4": (150, 160),
    "Z5": (160, 168), "Z6": (169, 172), "Z7": (173, 182),
}

# Неделя 7: 57 км.
WEEK_KM = 57.0
R_LIMIT_M = WEEK_KM * 1000 * 0.05     # 2850 м
I_LIMIT_M = WEEK_KM * 1000 * 0.08     # 4560 м

# Разминка и заминка.
WARMUP_MIN_KM = 3.0
COOLDOWN_MIN_KM = 1.0


@pytest.fixture(scope="module")
def plan():
    return load_plan(REFERENCE)


@pytest.fixture(scope="module")
def athlete() -> Athlete:
    return Athlete(
        vdot=48.0, hr_zones=HR_ZONES, hr_max=182, rhr=54, lth=164,
    )


@pytest.fixture(scope="module")
def paces():
    from app.adapters.daniels import load_paces
    return load_paces(REFERENCE)


def _recipe(plan, kind: str):
    """Рецепт недели 7 по виду работы."""
    entry = plan.week(2, 7)
    assert entry is not None, "нет недели 7 фазы II"
    found = [r for r in entry.recipes if r.kind == kind]
    assert found, f"в неделе 7 нет работы вида {kind}"
    return found[0]


# ───────────────────────────────────────────────────────── T1: повторы


def test_t1_series_structure(plan):
    """Серия повторов: 200 Пв, 200 трусцой, 200 Пв, 200 трусцой, 400 Пв, 400 трусцой."""
    recipe = _recipe(plan, "R")
    assert len(recipe.sets) == 1, "T1 — одна серия, повторённая несколько раз"
    segments = recipe.sets[0].segments
    assert len(segments) == 6, f"в серии {len(segments)} кусков, а должно быть шесть"
    expected = [
        (200.0, ZONE_REPETITION),
        (200.0, ZONE_EASY),
        (200.0, ZONE_REPETITION),
        (200.0, ZONE_EASY),
        (400.0, ZONE_REPETITION),
        (400.0, ZONE_EASY),
    ]
    actual = [(s.distance_m, s.zone) for s in segments]
    assert actual == expected, f"серия T1: {actual}"


def test_t1_has_warmup_and_cooldown(plan):
    """Перед серией — разминка минимум 3 км, после — заминка минимум 1 км."""
    recipe = _recipe(plan, "R")
    warmup_km = recipe.warmup_km
    cooldown_km = recipe.cooldown_km
    assert warmup_km >= WARMUP_MIN_KM, (
        f"разминка {warmup_km} км, а нужно минимум {WARMUP_MIN_KM}"
    )
    assert cooldown_km >= COOLDOWN_MIN_KM, (
        f"заминка {cooldown_km} км, а нужно минимум {COOLDOWN_MIN_KM}"
    )


def test_t1_repetition_volume_about_five_percent(plan, paces):
    """Объём в повторном темпе — примерно 5 % недельного километража.

    «Примерно 5 % или чуть больше»: 4 серии дают 3200 м = 5,6 % при
    недельных 57 км. Больше 4 серий — уже 7 %, это не «чуть больше».
    """
    recipe = _recipe(plan, "R")
    pace_by_zone = paces.pace_by_zone(48.0)
    volume = recipe_zone_volume_m(recipe, pace_by_zone).get(ZONE_REPETITION, 0.0)
    share = volume / (WEEK_KM * 1000.0)
    assert share >= 0.05, f"повторного темпа {share:.1%}, а нужно не меньше 5 %"
    assert share <= 0.065, f"повторного темпа {share:.1%} — это больше «чуть больше 5 %»"


# ───────────────────────────────────────────────────────── T2: порог


def test_t2_five_series_of_1600(plan):
    """Пять серий по 1600 м в пороговом темпе + минута отдыха."""
    recipe = _recipe(plan, "T")
    assert len(recipe.sets) == 1, "T2 — одна серия, повторённая пять раз"
    assert recipe.sets[0].reps_min == 5, (
        f"в T2 {recipe.sets[0].reps_min} повторов, а нужно пять"
    )
    assert recipe.sets[0].reps_max == 5, "у T2 нет диапазона повторов"
    segments = recipe.sets[0].segments
    assert segments[0].distance_m == 1600.0, "работа T2 — 1600 м"
    assert segments[0].zone == ZONE_THRESHOLD, "работа T2 — в пороговом темпе"
    rest = segments[1]
    assert rest.zone == ZONE_EASY, "отдых T2 — в лёгком темпе"
    assert rest.minutes == 1.0, f"отдых T2 — {rest.minutes} мин, а нужно минута"


def test_t2_has_warmup_and_cooldown(plan):
    """Сначала разминка, потом заминка."""
    recipe = _recipe(plan, "T")
    assert recipe.warmup_km >= WARMUP_MIN_KM, (
        f"разминка T2 {recipe.warmup_km} км, нужно минимум {WARMUP_MIN_KM}"
    )
    assert recipe.cooldown_km >= COOLDOWN_MIN_KM, (
        f"заминка T2 {recipe.cooldown_km} км, нужно минимум {COOLDOWN_MIN_KM}"
    )


# ───────────────────────────────────────────────────────── T3: интервал


def test_t3_series_structure(plan):
    """Серия интервалов: 2 мин И, 1 мин трусцой, 1 мин И, 30 с трусцой, 30 с И, 30 с трусцой."""
    recipe = _recipe(plan, "I")
    assert len(recipe.sets) == 1, "T3 — одна серия, повторённая несколько раз"
    segments = recipe.sets[0].segments
    actual = [
        (s.minutes, s.seconds, s.zone) for s in segments
    ]
    expected = [
        (2.0, None, ZONE_INTERVAL),
        (1.0, None, ZONE_EASY),
        (1.0, None, ZONE_INTERVAL),
        (None, 30.0, ZONE_EASY),
        (None, 30.0, ZONE_INTERVAL),
        (None, 30.0, ZONE_EASY),
    ]
    assert actual == expected, f"серия T3: {actual}"


def test_t3_interval_volume_about_eight_percent(plan, paces):
    """Объём в интервальном темпе — примерно 8 % недельного километража."""
    recipe = _recipe(plan, "I")
    pace_by_zone = paces.pace_by_zone(48.0)
    volume = recipe_zone_volume_m(recipe, pace_by_zone).get(ZONE_INTERVAL, 0.0)
    share = volume / (WEEK_KM * 1000.0)
    assert share >= 0.07, f"интервального темпа {share:.1%}, а нужно около 8 %"
    assert share <= 0.09, f"интервального темпа {share:.1%} — больше, чем «примерно 8 %»"


def test_t3_has_warmup_and_cooldown(plan):
    """Разминка и заминка."""
    recipe = _recipe(plan, "I")
    assert recipe.warmup_km >= WARMUP_MIN_KM
    assert recipe.cooldown_km >= COOLDOWN_MIN_KM


# ───────────────────────────────────────────────────────── сборка сессии


def test_quality_workout_starts_with_warmup_and_ends_with_cooldown(
    plan, athlete, paces
):
    """В собранной тренировке первым идёт разминка, последним — заминка.

    Шаги разминки и заминки — отдельные шаги с ролями `warmup` и
    `cooldown`, а не куски работы: иначе они попадают в набор и
    меняют его объём.
    """
    from app.domain.enums import StepRole

    planner = WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
        plan=plan,
    )
    for kind in ("R", "T", "I"):
        recipe = _recipe(plan, kind)
        steps = planner._recipe_steps(recipe, paces.pace_by_zone(48.0))
        assert steps[0].role is StepRole.WARMUP, (
            f"{kind}: первый шаг — {steps[0].role}, а должен быть разминка"
        )
        assert steps[-1].role is StepRole.COOLDOWN, (
            f"{kind}: последний шаг — {steps[-1].role}, а должен быть заминка"
        )
        # Разминка и заминка — расстоянием, а не временем: объём недели
        # считается в километрах.
        for step in (steps[0], steps[-1]):
            assert step.target_type.value == "distance", (
                f"{kind}: разминка/заминка задана временем, а не расстоянием"
            )


def test_warmup_and_cooldown_do_not_enter_sets(plan, athlete, paces):
    """Разминка и заминка не входят в набор работы."""
    from app.domain.enums import StepRole

    planner = WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
        plan=plan,
    )
    recipe = _recipe(plan, "R")
    steps = planner._recipe_steps(recipe, paces.pace_by_zone(48.0))
    set_steps = [s for s in steps if s.role is not StepRole.WARMUP
                 and s.role is not StepRole.COOLDOWN]
    assert set_steps, "в тренировке нет ни одного шага работы"
    for step in set_steps:
        assert step.round is not None, "шаг работы вне набора"
