"""Согласие макро-плана сезона с планировщиком Дэниэлса.

Правило (зафиксировано Кириллом 31.10.2026, уточнено 01.11.2026):

- **горизонт один на весь сезон** — от даты старта сезона до даты гонки,
  считается один раз и подставляется в расписание программы для всех недель;
- **горизонт — недели ДО гонки**: расписание покрывает `schedule_for(N)`,
  где N — недель до гонки, а не N+1;
- **неделя гонки в макро-плана НЕТ**: гонка — событие, а не тренировка, и
  планировать её не нужно (Кирилл, 01.11.2026). Макро покрывает W1..W(N),
  где N — недель до гонки;
- **неделя сезона и неделя программы — разные числа**: неделя W4 сезона
  стоит на 4-й неделе программы, а не на 13-й.

Нарушение любого из пунктов даёт план, который показывает одни недели,
а собранная неделя содержит другие. Расхождение не видно ни в guard'е, ни
в артефактах — его ловит только сверка по всем неделям сразу.

Тест проверяет **живое состояние сезона** (`~/coach/state/season_plan.json`):
макро и планировщик обязаны совпадать на каждой неделе.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.adapters.daniels import load_plan
from app.domain.methodology import MethodPlan, recipe_zone_volume_m

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"
PIPELINE_STATE = Path.home() / "coach" / "state"
SEASON_PLAN = PIPELINE_STATE / "season_plan.json"

# Фаза Дэниэлса → фаза сезона пайплайна. Сопоставление по смыслу:
# база → база, порог → build, специфика → specific, подводка к гонке → taper.
DANIELS_PHASE_TO_SEASON = {
    1: "run_base",
    2: "run_build",
    3: "run_specific",
    4: "run_taper",
}

# Гонка — часть четвёртой фазы, своей фазы не имеет.
RACE_PHASE = "run_taper"


@pytest.fixture(scope="module")
def season_plan() -> dict[str, Any]:
    if not SEASON_PLAN.exists():
        pytest.skip(f"нет состояния сезона: {SEASON_PLAN}")
    data: dict[str, Any] = json.loads(
        SEASON_PLAN.read_text(encoding="utf-8")
    )
    return data


@pytest.fixture(scope="module")
def daniels_plan() -> MethodPlan:
    return load_plan(REFERENCE)


def _race(season_plan: dict[str, Any]) -> tuple[date, str]:
    """Дата гонки и id её цели — по основной цели сезона."""
    primary = next(
        (g for g in season_plan.get("goals", []) if g.get("primary")),
        None,
    )
    assert primary is not None, "в сезоне нет основной цели"
    race = next(
        (r for r in season_plan.get("races", [])
         if r.get("goal_id") == primary.get("id")),
        None,
    )
    assert race is not None, "у основной цели нет гонки"
    return date.fromisoformat(race["date"]), primary["id"]


def _horizon(season_plan: dict[str, Any]) -> int:
    """Горизонт расписания программы: недели сезона **до** гонки.

    Неделя гонки в макро-плана НЕТ (событие, а не тренировка), поэтому
    расписание программы покрывает ровно N недель, где N — недель до
    гонки, и макро заканчивается на неделе N.
    """
    start = date.fromisoformat(season_plan["season_start_date"])
    race_date, _ = _race(season_plan)
    return (race_date - start).days // 7


def _race_week(season_plan: dict[str, Any]) -> int:
    """Номер недели гонки в сезоне.

    Недели гонки в макро-плана нет: это номер недели, в которую попадает
    дата гонки, а не строка макро.
    """
    return _horizon(season_plan) + 1


def _season_week_start(season_plan: dict[str, Any], season_week: int) -> date:
    start = date.fromisoformat(season_plan["season_start_date"])
    return start + timedelta(days=7 * (season_week - 1))


def test_horizon_is_weeks_before_race(season_plan: dict[str, Any]) -> None:
    """Горизонт — недели сезона до гонки.

    Неделя гонки в макро-плана НЕТ: гонка — событие, а не тренировка.
    Расписание программы покрывает недели до гонки, и макро заканчивается
    на последней из них.
    """
    start = date.fromisoformat(season_plan["season_start_date"])
    race_date, _ = _race(season_plan)
    weeks_before = (race_date - start).days // 7
    horizon = _horizon(season_plan)
    assert horizon == weeks_before, (
        f"горизонт {horizon} ≠ недель до гонки {weeks_before}"
    )


def test_macro_covers_all_plan_weeks(season_plan: dict[str, Any]) -> None:
    """Макро покрывает все недели плана — до последней недели перед гонкой."""
    horizon = _horizon(season_plan)
    weeks = {w["season_week"] for w in season_plan.get("weekly_macro") or []}
    missing = sorted(set(range(1, horizon + 1)) - weeks)
    assert not missing, f"в макро нет недель: {missing}"


def test_macro_has_no_extra_weeks(season_plan: dict[str, Any]) -> None:
    """В макро нет недель сверх горизонта.

    Неделя гонки не планируется (Кирилл, 01.11.2026): макро заканчивается
    на последней неделе перед гонкой, а лишних строк быть не должно.
    """
    horizon = _horizon(season_plan)
    weeks = {w["season_week"] for w in season_plan.get("weekly_macro") or []}
    extra = sorted(w for w in weeks if w > horizon)
    assert not extra, f"в макро есть недели сверх горизонта: {extra}"


def test_race_week_is_not_planned(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Неделя гонки — вне макро и вне расписания программы.

    Гонка — событие, а не тренировка: своей недели программы у неё нет, и
    в макро она не планируется.
    """
    horizon = _horizon(season_plan)
    race_week = _race_week(season_plan)
    macro = {w["season_week"]: w for w in season_plan.get("weekly_macro") or []}
    assert race_week not in macro, (
        f"неделя {race_week} (гонка) не должна быть в макро — её не планируют"
    )
    assert daniels_plan.plan_week(horizon, race_week - 1) is None, (
        f"неделя {race_week} (гонка) не должна быть в расписании программы"
    )


def test_every_week_has_a_program_week(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Каждая неделя сезона до гонки получает неделю программы.

    `plan_week` возвращает None за пределами расписания: неделя собралась
    бы без качественной работы Дэниэлса молча, без ошибки.
    """
    horizon = _horizon(season_plan)
    for season_week in range(1, horizon + 1):
        located = daniels_plan.plan_week(horizon, season_week - 1)
        assert located is not None, (
            f"неделя {season_week}: нет недели программы при горизонте "
            f"{horizon}"
        )


def test_macro_and_planner_agree_on_every_week(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Макро и планировщик берут одну и ту же неделю программы.

    Сверка по всем неделям сразу: расхождение в одной неделе означает, что
    правило применено к разным горизонтам, и «почти совпадает» быть не
    может.
    """
    horizon = _horizon(season_plan)
    macro = {w["season_week"]: w for w in season_plan.get("weekly_macro") or []}
    mismatches: list[str] = []

    for season_week in range(1, horizon + 1):
        entry = macro.get(season_week)
        assert entry is not None, f"в макро нет недели {season_week}"

        located = daniels_plan.plan_week(horizon, season_week - 1)
        assert located is not None
        daniels_phase, program_week, plan_week = located

        recorded = entry.get("_daniels") or {}
        recorded_phase = recorded.get("daniels_phase")
        recorded_program = recorded.get("program_week")
        recorded_plan = recorded.get("plan_week")

        if recorded_phase != daniels_phase:
            mismatches.append(
                f"неделя {season_week}: фаза Дэниэлса в макро {recorded_phase}, "
                f"у планировщика {daniels_phase}"
            )
        if recorded_program != program_week:
            mismatches.append(
                f"неделя {season_week}: неделя программы в макро "
                f"{recorded_program}, у планировщика {program_week}"
            )
        if recorded_plan != plan_week:
            mismatches.append(
                f"неделя {season_week}: неделя плана в макро {recorded_plan}, "
                f"у планировщика {plan_week}"
            )

    assert not mismatches, "макро и планировщик расходятся:\n" + "\n".join(
        mismatches
    )


def test_macro_phase_matches_daniels_phase(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Фаза сезона в макро — та же, что у планировщика.

    Фаза в плане сезона и фаза в макро — разные вещи, если они разошлись:
    на экране неделя числится в одной фазе, а тренировки собраны по другой.
    """
    horizon = _horizon(season_plan)
    macro = {w["season_week"]: w for w in season_plan.get("weekly_macro") or []}

    for season_week in range(1, horizon + 1):
        entry = macro[season_week]
        located = daniels_plan.plan_week(horizon, season_week - 1)
        assert located is not None
        daniels_phase = located[0]
        expected = DANIELS_PHASE_TO_SEASON[daniels_phase]
        assert entry.get("phase") == expected, (
            f"неделя {season_week}: фаза сезона {entry.get('phase')}, "
            f"у планировщика {expected} (Дэниэлс, фаза {daniels_phase})"
        )


def test_macro_phases_match_season_phase_boundaries(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Границы фаз в плане сезона — те же, что у расписания программы.

    Иначе фаза в плане и фаза в макро — разные недели: план говорит «до
    W13», а макро раскладывает по-другому.
    """
    horizon = _horizon(season_plan)

    expected_bounds: dict[str, tuple[int, int]] = {}
    for season_week in range(1, horizon + 1):
        located = daniels_plan.plan_week(horizon, season_week - 1)
        assert located is not None
        phase = DANIELS_PHASE_TO_SEASON[located[0]]
        if phase not in expected_bounds:
            expected_bounds[phase] = (season_week, season_week)
        else:
            first, _ = expected_bounds[phase]
            expected_bounds[phase] = (first, season_week)

    for phase in season_plan.get("phases") or []:
        phase_id = phase.get("id")
        if phase_id not in expected_bounds:
            continue
        expected_first, expected_last = expected_bounds[phase_id]
        actual_first = phase.get("_season_week_start")
        actual_last = phase.get("_season_week_end")
        assert (actual_first, actual_last) == (expected_first, expected_last), (
            f"фаза {phase_id}: границы в плане W{actual_first}-W{actual_last}, "
            f"по расписанию программы W{expected_first}-W{expected_last}"
        )


def test_macro_work_matches_program_week(
    season_plan: dict[str, Any], daniels_plan: MethodPlan
) -> None:
    """Работа в макро — та же, что в неделе программы.

    Это проверка **подмапливания**: неделя сезона должна брать работу той
    недели программы, чей план к ней применён. Неделя с чужой работой —
    план, который не соответствует ни одной неделе Дэниэлса.

    Объём в зоне в макро — **как в программе**, до пределов: предел зоны
    («R — не более 5 % недельного километража») применяет планировщик при
    сборке недели, а не макро. Проверка предела — в тестах планировщика
    (`test_planner_respects_zone_cap`).
    """
    horizon = _horizon(season_plan)
    macro = {w["season_week"]: w for w in season_plan.get("weekly_macro") or []}

    for season_week in range(1, horizon + 1):
        entry = macro[season_week]
        located = daniels_plan.plan_week(horizon, season_week - 1)
        assert located is not None
        daniels_phase, _program_week, plan_week = located

        program_entry = daniels_plan.week(daniels_phase, plan_week)
        assert program_entry is not None

        recorded = entry.get("_daniels") or {}
        zones = recorded.get("quality_zones") or {}

        expected: dict[str, float] = {}
        for recipe in program_entry.recipes:
            if recipe.kind == "RACE":
                continue
            for zone, value in recipe_zone_volume_m(recipe).items():
                expected[zone] = expected.get(zone, 0.0) + value

        for zone, value in expected.items():
            claimed = float(zones.get(zone) or 0.0)
            assert claimed == pytest.approx(value, abs=1.0), (
                f"неделя {season_week}: в зоне {zone} макро {claimed:.0f} м, "
                f"в неделе программы {plan_week} — {value:.0f} м"
            )
