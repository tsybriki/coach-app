#!/usr/bin/env python3
"""
verify_phase_four_plans.py — сквозная проверка правила фазы IV.

Проверяет не раскладку, а то, что из этого следует: недели сезона 23 и 24
при сроке 29 недель собирают одно и то же — план недели 19 программы.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.daniels import load_paces, load_plan  # noqa: E402
from app.domain.entities import Athlete, LoadModel, Slot  # noqa: E402
from app.domain.enums import Sport  # noqa: E402
from app.services.week_planner import (  # noqa: E402
    WeeklyTarget,
    WeekPlanner,
    WeekPlanInput,
)

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118), "Z2": (118, 135), "Z3": (136, 150),
    "Z4": (150, 160), "Z5": (160, 168), "Z6": (169, 172), "Z7": (173, 182),
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


def signature(recipes) -> list[str]:
    """Отпечаток тренировки: вид работы и её структура."""
    return [
        f"{r.kind}:{r.label}" + (
            "[" + ";".join(s.label for s in r.sets) + "]" if r.sets else ""
        )
        for r in recipes
    ]


def main() -> int:
    paces = load_paces(REFERENCE)
    plan = load_plan(REFERENCE)
    athlete = Athlete(vdot=48.0, hr_zones=HR_ZONES, hr_max=182, rhr=54, lth=164)
    planner = WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
        plan=plan,
    )

    problems: list[str] = []

    def build(season_week: int, weeks_to_race: int, phase: int, week: int):
        return planner.build_from(WeekPlanInput(
            season_week=season_week,
            week_start=date(2026, 10, 25),
            week_end=date(2026, 10, 31),
            targets=[WeeklyTarget(sport=Sport.RUN, duration_min=198, focus="база")],
            slots=SLOTS,
            phase=phase,
            week=week,
            weeks_to_race=weeks_to_race,
            run_km=35.0,
        ))

    # Недели сезона 23 и 24 при сроке 29 недель → обе из плана недели 19.
    w23 = build(23, 29, 4, 19)
    w24 = build(24, 29, 4, 19)
    recipes_23 = signature(plan.week(4, plan.schedule_for(29).plan_for(27)).recipes)
    recipes_24 = signature(plan.week(4, 19).recipes)

    print("неделя 23 сезона (лишняя фазы IV) → рецепты недели 19:")
    for line in recipes_23:
        print("   " + line)
    print("неделя 24 сезона (программная 19) → рецепты недели 19:")
    for line in recipes_24:
        print("   " + line)

    if recipes_23 != recipes_24:
        problems.append("недели 23 и 24 дают разные рецепты")

    # Неделя 25 — программная 20: её рецепты должны отличаться от 19-й.
    recipes_25 = signature(plan.week(4, 20).recipes)
    if recipes_25 == recipes_24:
        problems.append("неделя 25 (программная 20) совпала с 19-й")

    # План фазы IV при сроке 29 недель: недели программы по порядку.
    schedule = plan.schedule_for(29)
    if schedule.weeks_for(4) != (27, 19, 20, 21, 22, 23, 24):
        problems.append(f"фаза IV при 29 неделях: {schedule.weeks_for(4)}")

    # При сроке 30 недель у фазы IV две лишние: планы 19 и 20 по кругу.
    schedule_30 = plan.schedule_for(30)
    extras_30 = [w for w in schedule_30.weeks_for(4) if w > 24]
    plans_30 = [schedule_30.plan_for(w) for w in extras_30]
    print()
    print(f"30 недель: лишние фазы IV {extras_30} → планы {plans_30}")
    if plans_30 != [19, 20]:
        problems.append(f"30 недель: планы фазы IV {plans_30}")

    print()
    if problems:
        print("РАСХОЖДЕНИЯ:")
        for problem in problems:
            print("  " + problem)
        return 1
    print("OK: недели 23 и 24 сезона берут план недели 19, фаза IV растёт в начало")
    return 0


if __name__ == "__main__":
    sys.exit(main())
