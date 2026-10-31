#!/usr/bin/env python3
"""
check_daniels_planner.py — прогон планировщика по правилам Дэниэлса.

Показывает, что даёт правило для недели программы: какие тренировки,
какие темпы, какой объём в зонах и укладывается ли он в ограничения
недели («R — не более 5 % недельного километража» и т. п.).

Запуск:
    python3 tools/check_daniels_planner.py
    python3 tools/check_daniels_planner.py --vdot 48 --run-km 35 --week 7
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.daniels import load_paces, load_plan  # noqa: E402
from app.domain.entities import Athlete, LoadModel, Slot  # noqa: E402
from app.domain.methodology import (  # noqa: E402
    ZONE_NAMES,
    recipe_zone_volume_m,
)
from app.services.week_planner import WeekPlanInput, WeekPlanner, WeeklyTarget  # noqa: E402
from app.domain.enums import Sport  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "reference" / "daniels"

# Профиль Кирилла: 7 зон, HRmax 182.
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
    Slot(id="win-ПН-1", day=1, start="18:45", end="20:15", capacity_min=90),
    Slot(id="win-ВТ-1", day=2, start="09:00", end="09:30", capacity_min=30),
    Slot(id="win-ВТ-2", day=2, start="18:30", end="19:45", capacity_min=75),
    Slot(id="win-СР-1", day=3, start="17:00", end="19:00", capacity_min=120),
    Slot(id="win-ЧТ-1", day=4, start="10:30", end="11:15", capacity_min=45),
    Slot(id="win-ПТ-1", day=5, start="18:00", end="19:00", capacity_min=60),
    Slot(id="win-СБ-1", day=6, start="10:00", end="11:00", capacity_min=60),
    Slot(id="win-ВС-1", day=0, start="11:00", end="13:00", capacity_min=120),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vdot", type=float, default=48.0)
    ap.add_argument("--run-km", type=float, default=35.0)
    ap.add_argument("--week", type=int, default=7, help="неделя программы")
    ap.add_argument("--phase", type=int, default=2)
    ap.add_argument("--run-minutes", type=int, default=198,
                    help="минут бега в неделе")
    args = ap.parse_args()

    paces = load_paces(REFERENCE)
    plan = load_plan(REFERENCE)

    athlete = Athlete(
        vdot=args.vdot,
        hr_zones=HR_ZONES,
        hr_max=182,
        rhr=54,
        lth=164,
    )

    pace_by_zone = paces.pace_by_zone(args.vdot)
    print(f"VDOT {args.vdot} · темпы зон:")
    for zone, pace in sorted(pace_by_zone.items(), key=lambda kv: -kv[1]):
        minutes = int(pace // 60)
        seconds = int(pace % 60)
        print(f"   {ZONE_NAMES.get(zone, zone):>3}  {minutes}:{seconds:02d}/км")

    entry = plan.week(args.phase, args.week)
    if entry is None:
        print(f"нет недели программы: фаза {args.phase}, неделя {args.week}")
        return 1

    print(f"\nФаза {args.phase}, неделя {args.week} — правила недели:")
    for cap in entry.caps:
        limit = args.run_km * cap.fraction_of_week
        if cap.ceiling_km is not None:
            limit = min(limit, cap.ceiling_km)
        print(f"   предел {ZONE_NAMES.get(cap.zone, cap.zone)}: "
              f"{limit:.1f} км (из {cap.fraction_of_week:.0%} недельного "
              f"километража" + (f", потолок {cap.ceiling_km:g} км)" if cap.ceiling_km else "") + ")")

    print("\nрецепты недели:")
    for recipe in entry.recipes:
        volumes = recipe_zone_volume_m(recipe)
        volume_text = ", ".join(
            f"{ZONE_NAMES.get(z, z)} {v:.0f}м" for z, v in sorted(volumes.items())
        )
        print(f"   [{recipe.kind}] {recipe.label}" + (f" — {volume_text}" if volume_text else ""))

    planner = WeekPlanner(
        templates={},
        load_model=LoadModel(adaptation_rate={"run": 1.0}),
        athlete=athlete,
        paces=paces,
        plan=plan,
    )

    week = planner.build_from(WeekPlanInput(
        season_week=args.week,
        week_start=__import__("datetime").date(2026, 10, 25),
        week_end=__import__("datetime").date(2026, 10, 31),
        targets=[
            WeeklyTarget(sport=Sport.RUN, duration_min=args.run_minutes,
                         focus="база", long_min=70),
        ],
        slots=SLOTS,
        phase=args.phase,
        week=args.week,
        run_km=args.run_km,
    ))

    print(f"\nсобранная неделя {week.id}: "
          f"{len(week.requests)} запросов, {len(week.assignments)} размещений, "
          f"{len(week.unplaced)} висяков")
    for workout in week.workouts:
        zone_text = ""
        steps = workout.steps
        zones = {s.focus_value.get("daniels_zone") for s in steps if s.focus_value.get("daniels_zone")}
        if zones:
            zone_text = " зоны " + ",".join(sorted(ZONE_NAMES.get(z, z) for z in zones))
        print(f"   {workout.kind:<8} {workout.duration_min:>6.1f} мин  "
              f"{len(steps):>2} шагов{zone_text}  {workout.focus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
