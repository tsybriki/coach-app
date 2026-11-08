#!/usr/bin/env python3
"""
parse_all_details.py — разобрать FIT-файлы всех сессий сезона.

Разбор нужен для метрик формы: зоны пульса, темп в зоне, нагрузка,
каденция считаются по нему. Без разбора метрик нет.

**Что делает.**
1. Берёт факт из хранилища — все недели.
2. Для каждой сессии ищет FIT-файл (индекс выкачки Garmin).
3. Разбирает и кладёт разбор в `details/`.

Работает на копии боевого хранилища: `--live` — на боевом.

Запуск:
    python tools/parse_all_details.py             # копия боевого хранилища
    python tools/parse_all_details.py --live      # боевое хранилище
    python tools/parse_all_details.py --week 4    # только неделя
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters.fit import parse_fit  # noqa: E402
from app.adapters.garmin import GarminFitPort  # noqa: E402
from app.adapters.storage.files import FileStorage  # noqa: E402
from app.adapters.storage.ports import (  # noqa: E402
    AthleteRepoAdapter,
    DetailRepoAdapter,
    FactRepoAdapter,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="работать с боевым хранилищем (по умолчанию — копия)")
    ap.add_argument("--week", type=int, default=0,
                    help="только неделя сезона")
    args = ap.parse_args()

    source = Path.home() / ".local" / "share" / "coach-app"
    if args.live:
        data_root = source
        print(f"работаем с боевым хранилищем: {data_root}")
    else:
        tmp = tempfile.mkdtemp(prefix="coach-app-parse-")
        data_root = Path(tmp) / "coach-app"
        shutil.copytree(source, data_root)
        print(f"работаем с копией: {data_root}")

    storage = FileStorage(data_root)
    facts = FactRepoAdapter(storage)
    details = DetailRepoAdapter(storage)
    athlete = AthleteRepoAdapter(storage).get()
    fit_port = GarminFitPort()

    sessions = []
    for week in storage.weeks():
        if args.week and week.season_week != args.week:
            continue
        sessions.extend(facts.list_for_week(week.season_week))

    print(f"сессий: {len(sessions)}")
    parsed = 0
    skipped = 0
    existing = 0

    for session in sessions:
        if details.detail(session.id) is not None:
            existing += 1
            continue
        if not session.external_id:
            skipped += 1
            continue
        fit_path = fit_port.fit_path_for(session.external_id)
        if fit_path is None:
            skipped += 1
            continue
        try:
            detail = parse_fit(
                fit_path,
                hr_max=athlete.hr_max or 182,
                zones=athlete.hr_zones or None,
            )
        except Exception as error:  # noqa: BLE001 — один файл не роняет всё
            print(f"  {session.id}: не разобран ({error})")
            skipped += 1
            continue
        detail.actual_id = session.id
        details.save_detail(detail)
        parsed += 1
        print(f"  {session.id} {session.date} {session.sport.value}: разобран")

    print(f"\nразобрано: {parsed} · уже было: {existing} · пропущено: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
