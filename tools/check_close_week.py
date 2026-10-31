#!/usr/bin/env python3
"""
check_close_week.py — воспроизвести нажатие «Закрыть неделю».

Работает на КОПИИ боевого хранилища: живое состояние не трогается.
Показывает, что отвечает сервер на команду close_week для текущей недели.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

SOURCE = Path.home() / ".local" / "share" / "coach-app"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "coach-app"
        shutil.copytree(SOURCE, root)
        os.environ["COACH_APP_DATA"] = str(root)

        app = create_app()
        with TestClient(app) as client:
            current = client.get("/api/v1/current-week").json()["data"]
            season_week = current["season_week"]
            print(f"текущая неделя: W{season_week} ({current['start']} — {current['end']})")

            week = client.get(f"/api/v1/week/{season_week}").json()["data"]
            print(f"статус недели: {week.get('status')}")
            print(f"тренировок в плане: {len(week.get('workouts') or [])}")

            snapshot = client.get("/api/v1/snapshot").json()
            version = snapshot["version"]

            print()
            print("--- команда close_week ---")
            response = client.post("/api/v1/commands", json={
                "id": "check-close-week",
                "type": "close_week",
                "target": {},
                "args": {"season_week": season_week},
                "reason": "проверка закрытия недели",
                "issued_by": "user",
                "expected_version": version,
            })
            print(f"HTTP {response.status_code}")
            body = response.json()
            print(json.dumps(body, ensure_ascii=False, indent=1)[:1200])

            after = client.get(f"/api/v1/week/{season_week}").json()["data"]
            print()
            print(f"статус недели после: {after.get('status')}")
            print(f"саммари: {'есть' if after.get('summary') else 'нет'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
