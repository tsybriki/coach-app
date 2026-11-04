#!/usr/bin/env python3
"""
check_week_lifecycle.py — сквозная проверка жизненного цикла недели.

Работает на КОПИИ боевого хранилища: живое состояние не трогается.
Показывает весь путь: propose → activate → close, и что происходит при
попытке закрыть неактивную неделю.
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
            sw = client.get("/api/v1/current-week").json()["data"]["season_week"]
            week = client.get(f"/api/v1/week/{sw}").json()["data"]
            print(f"неделя W{sw} ({week['start']} — {week['end']}) · "
                  f"статус {week['status']} · "
                  f"тренировок {len(week.get('workouts') or [])}")

            def cmd(cid: str, ctype: str):
                version = client.get("/api/v1/snapshot").json()["version"]
                return client.post("/api/v1/commands", json={
                    "id": cid, "type": ctype, "target": {},
                    "args": {"season_week": sw},
                    "reason": f"проверка {ctype}",
                    "issued_by": "user", "expected_version": version,
                })

            print()
            print("--- 1. закрыть proposed-неделю напрямую ---")
            r = cmd("c1", "close_week")
            # Неделя может быть уже активной — тогда закрытие пройдёт.
            # Чекер не должен падать из-за формы ответа: он показывает
            # путь, а не проверяет конкретный статус боевой недели.
            body = r.json()
            message = (body.get("error") or {}).get("message") or "закрыто"
            print(f"HTTP {r.status_code}: {message}")

            print()
            print("--- 2. активация ---")
            r = cmd("a1", "activate_week")
            print(f"HTTP {r.status_code}")
            week = client.get(f"/api/v1/week/{sw}").json()["data"]
            print(f"статус: {week['status']}")

            print()
            print("--- 3. закрытие ---")
            r = cmd("c2", "close_week")
            print(f"HTTP {r.status_code}")
            week = client.get(f"/api/v1/week/{sw}").json()["data"]
            summary = week.get("summary") or {}
            print(f"статус: {week['status']}")
            print(f"closed_at: {summary.get('closed_at')}")
            print(f"итоги: {json.dumps(summary.get('totals'), ensure_ascii=False)}")
            print(f"вердикты: {json.dumps(summary.get('verdict'), ensure_ascii=False)}")
            intensity = summary.get("intensity") or {}
            contributions = intensity.get("contributions") or []
            total = sum(int(c.get("moderate_min", 0)) for c in contributions)
            print(f"интенсивность: moderate {intensity.get('actual_moderate')} "
                  f"· Σ вкладов {total} "
                  f"· {'СХОДИТСЯ' if total == intensity.get('actual_moderate') else 'РАСХОДИТСЯ'}")

            print()
            print("--- 4. propose на закрытой неделе ---")
            r = cmd("p1", "propose_week")
            print(f"HTTP {r.status_code}: {r.json()['error']['message']}")
            after = client.get(f"/api/v1/week/{sw}").json()["data"]
            print(f"статус после propose: {after['status']} "
                  f"· саммари {'есть' if after.get('summary') else 'НЕТ'}")

            problems = []
            if after["status"] != "closed":
                problems.append("закрытая неделя переоткрылась")
            if not after.get("summary"):
                problems.append("саммари затёрто")
            if not summary.get("closed_at"):
                problems.append("closed_at пуст")
            if total != intensity.get("actual_moderate"):
                problems.append("вклады не сходятся с итогом (I16)")

            print()
            if problems:
                print("РАСХОЖДЕНИЯ:")
                for problem in problems:
                    print("  " + problem)
                return 1
            print("OK: полный путь работает, закрытая неделя не меняется, "
                  "саммари сходится")
    return 0


if __name__ == "__main__":
    sys.exit(main())
