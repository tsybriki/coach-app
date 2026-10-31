#!/usr/bin/env python3
"""
live_propose_check.py — проверка команды propose_week на живом стеке.

Поднимает приложение на копии данных, отправляет команду `propose_week`
и показывает, что получилось: какие тренировки, какие темпы, какие зоны.

Запуск:
    python3 tools/live_propose_check.py
    python3 tools/live_propose_check.py --week 7
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.domain.methodology import ZONE_NAMES  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=3, help="неделя сезона")
    ap.add_argument("--source", default=str(Path.home() / ".local" / "share" / "coach-app"))
    args = ap.parse_args()

    # Работаем на копии данных: команда меняет состояние.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "coach-app"
        shutil.copytree(args.source, root)
        os.environ["COACH_APP_DATA"] = str(root)

        app = create_app()
        with TestClient(app) as client:
            current = client.get("/api/v1/current-week").json()
            season_week = current["data"]["season_week"]
            print(f"текущая неделя сезона: W{season_week} "
                  f"({current['data']['start']} — {current['data']['end']})")

            snapshot = client.get("/api/v1/snapshot").json()
            version = snapshot["version"]

            week = client.get(f"/api/v1/week/{season_week}")
            if week.status_code != 200:
                print(f"неделя не загрузилась: {week.status_code} {week.text[:200]}")
                return 1
            data = week.json()["data"]
            print(f"до propose: {len(data['workouts'])} тренировок, "
                  f"статус {data['status']}")
            print(f"версия состояния: {version}")

            response = client.post("/api/v1/commands", json={
                "id": f"live-propose-{season_week}",
                "type": "propose_week",
                "target": {},
                "args": {"season_week": season_week},
                "reason": "проверка планировщика на живом стеке",
                "issued_by": "user",
                "expected_version": version,
            })
            print(f"ответ команды: {response.status_code}")
            body = response.json()
            if "error" in body:
                print(f"ошибка: {body['error']}")
                return 1

            after = client.get(f"/api/v1/week/{season_week}").json()["data"]
            print(f"после propose: {len(after['workouts'])} тренировок, "
                  f"статус {after['status']}")
            print(f"load_target: {after.get('load_target')}")
            print()
            for workout in after["workouts"]:
                steps = workout.get("steps") or []
                zones = {
                    s["focus_value"].get("daniels_zone")
                    for s in steps
                    if s.get("focus_value", {}).get("daniels_zone")
                }
                zone_text = ", ".join(
                    sorted(ZONE_NAMES.get(z, z) for z in zones if z)
                )
                print(f"  {workout['kind']:<16} {workout['duration_min']:>6} мин  "
                      f"{len(steps):>2} шагов  {zone_text:<8} {workout.get('focus', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
