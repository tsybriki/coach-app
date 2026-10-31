#!/usr/bin/env python3
"""
parse_daniels_plan.py — разбор Табл. 19.1 (Daniels' Running Formula).

Источник правды: `reference/daniels/training_plan_19_1.txt` — промежуточное
представление с явно разведёнными колонками. Скрипт превращает его в JSON,
который читает приложение.

Запуск:
    python3 tools/parse_daniels_plan.py
    python3 tools/parse_daniels_plan.py --check   # только проверить, что JSON свеж

Формат промежуточного файла:
    <фаза> <неделя> <ТИП> <тело>
    <фаза> <неделя> cap <ЗОНА> <доля> [<потолок_км>]
    <фаза> <неделя> note <текст>
    MAP <фаза_сезона> <фаза_данiels> <первая_неделя> <последняя_неделя>
    FRONT <фаза,...> — фазы, в которые лишняя неделя встаёт в НАЧАЛО
    SINGLE <фаза>:<неделя> — план лишней недели, когда она одна

Тело тренировки: части через « + ».
    Nx(...)             — повтор группы (N или N-M)
    200m@R             — 200 м в зоне R
    2min@I             — 2 минуты в зоне I
    3200m@T~10-12min@T — 3200 м (= 10-12 мин) в зоне T: «~» = эквивалент
    3min@I il 800m@I   — «il» = альтернативы (выбрать одно)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = Path(REPO) / "reference" / "daniels" / "training_plan_19_1.txt"
DST = Path(REPO) / "reference" / "daniels" / "training_plan_19_1.json"

ZONE_NAMES = {"E": "Л", "M": "М", "T": "П", "I": "И", "R": "Пв"}
ZONE_FULL = {
    "E": "лёгкий темп",
    "M": "марафонский темп",
    "T": "пороговый темп",
    "I": "интервальный темп",
    "R": "повторный темп",
}


# ------------------------------------------------------------------ разбор кусков


def parse_amount(token: str) -> tuple[float | None, float | None, float | None]:
    """'200m' → (200 м, None, None); '2min' → (None, 2 мин, None); '30s' → (None, None, 30 с)."""
    match = re.fullmatch(r"(\d+(?:-\d+)?)(m|min|s)", token)
    if not match:
        return (None, None, None)
    raw, unit = match.group(1), match.group(2)
    if "-" in raw:
        low, high = raw.split("-")
        value = float(low)
        span = float(high) - float(low)
    else:
        value = float(raw)
        span = 0.0
    if unit == "m":
        return (value, None, None)
    if unit == "min":
        return (None, value, None)
    return (None, None, value)


def parse_segment(token: str) -> dict[str, Any]:
    """Один кусок работы: объём или время в одной зоне."""
    alternatives: list[dict[str, Any]] = []
    for alternative in token.split(" il "):
        alternatives.append(_parse_single(alternative))
    primary = alternatives[0]
    primary["alternatives"] = alternatives[1:]
    return primary


def _parse_single(token: str) -> dict[str, Any]:
    """'3200m@T~10-12min@T' → одна работа, выраженная двумя способами."""
    parts = token.split("~")
    zone = ""
    distance_m: float | None = None
    minutes: float | None = None
    seconds: float | None = None
    for part in parts:
        if "@" in part:
            amount, zone = part.rsplit("@", 1)
            zone = zone.strip()
            dist, mins, secs = parse_amount(amount.strip())
            distance_m = dist if dist is not None else distance_m
            minutes = mins if mins is not None else minutes
            seconds = secs if secs is not None else seconds
        else:
            dist, mins, secs = parse_amount(part.strip())
            distance_m = dist if dist is not None else distance_m
            minutes = mins if mins is not None else minutes
            seconds = secs if secs is not None else seconds
    return {
        "zone": zone,
        "distance_m": distance_m,
        "minutes": minutes,
        "seconds": seconds,
    }


def split_top(body: str) -> list[str]:
    """Разделить по « + » на верхнем уровне (скобки не разрываются)."""
    parts: list[str] = []
    depth = 0
    current = ""
    index = 0
    while index < len(body):
        char = body[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if body[index:index + 3] == " + " and depth == 0:
            parts.append(current.strip())
            current = ""
            index += 3
            continue
        current += char
        index += 1
    if current.strip():
        parts.append(current.strip())
    return parts


# Повтор: «5-6 × (...)», «2 × 200 м», «3 × 1000 м».
#
# Форма бывает двух видов: со скобками (внутри — несколько кусков) и без
# (внутри — один кусок). Оба надо понимать: «5-6 × (2 × 200 м + 200 м Л)»
# иначе посчитается как 5-6 повторов по 200 м, а это втрое меньше.
REPEAT_RE = re.compile(r"^(\d+)(?:-(\d+))?x(?:\((.*)\)|(.+))$", re.DOTALL)


def parse_body(body: str) -> dict[str, Any]:
    """Тело тренировки → наборы (с повторами) или плоский список кусков.

    Наборы могут быть вложенными: «5-6 × (2 × 200 м + 200 м Л)» — это
    5-6 повторов, каждый из которых состоит из двух 200-метровых отрезков
    и 200 м лёгкого бега. Вложенный набор разворачивается в
    последовательность сегментов, иначе объём в зоне посчитать нельзя.
    """
    sets: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for part in split_top(body):
        group = REPEAT_RE.match(part)
        if group:
            low = int(group.group(1))
            high = int(group.group(2)) if group.group(2) else low
            inner = _inner_parts(group)
            segments = expand_segments(inner)
            sets.append({
                "reps_min": low,
                "reps_max": high,
                "segments": segments,
                "label": set_label(low, high, segments),
            })
            continue
        flat.append(parse_segment(part))
    return {"sets": sets, "flat": flat}


def _inner_parts(group: re.Match[str]) -> list[str]:
    """Части внутри повтора: скобки — несколько кусков, без скобок — один."""
    if group.group(3) is not None:
        return split_top(group.group(3))
    return [group.group(4).strip()]


def expand_segments(parts: list[str]) -> list[dict[str, Any]]:
    """Развернуть список частей в последовательность сегментов.

    Вложенный набор «2 × 200 м» становится двумя сегментами по 200 м.
    """
    segments: list[dict[str, Any]] = []
    for part in parts:
        group = REPEAT_RE.match(part)
        if group:
            low = int(group.group(1))
            inner = expand_segments(_inner_parts(group))
            for _ in range(low):
                segments.extend(inner)
            continue
        segments.append(parse_segment(part))
    return segments


def set_label(low: int, high: int, segments: list[dict[str, Any]]) -> str:
    """Название сета для карточки: «5-6×(2×200м Пв + 200м Л)»."""
    counter = f"{low}" if low == high else f"{low}-{high}"
    pieces = []
    for segment in segments:
        pieces.append(segment_label(segment))
    return f"{counter}×({pieces[0]}" + "".join(f" + {p}" for p in pieces[1:]) + ")"


def segment_label(segment: dict[str, Any]) -> str:
    """«200м Пв» / «2мин И»."""
    if segment.get("distance_m"):
        amount = f"{int(segment['distance_m'])}м"
    elif segment.get("minutes"):
        amount = f"{int(segment['minutes'])}мин"
    elif segment.get("seconds"):
        amount = f"{int(segment['seconds'])}с"
    else:
        amount = "?"
    zone = ZONE_NAMES.get(segment.get("zone", ""), segment.get("zone", ""))
    return f"{amount} {zone}"


# ------------------------------------------------------------------ сборка


def parse(text: str) -> dict[str, Any]:
    weeks: dict[str, dict[str, Any]] = {}
    phase_map: list[dict[str, Any]] = []
    notes: list[str] = []
    schedules: list[dict[str, Any]] = []
    base_schedule: dict[str, Any] | None = None
    extra_phases: tuple[int, ...] = ()
    extra_plans: dict[int, tuple[int, ...]] = {}
    extra_single: dict[int, int] = {}
    front_phases: tuple[int, ...] = ()
    program_weeks: dict[int, tuple[int, ...]] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("MAP "):
            parts = line.split()
            phase_map.append({
                "season_phase": parts[1],
                "daniels_phase": int(parts[2]),
                "week_from": int(parts[3]),
                "week_to": int(parts[4]),
            })
            continue

        if line.startswith("EXTRA "):
            extra_phases = tuple(
                int(p) for p in line.split()[1].split(",") if p
            )
            continue

        if line.startswith("PLANS "):
            for item in line.split()[1:]:
                phase_token, weeks_list = item.split(":")
                extra_plans[int(phase_token)] = tuple(
                    int(w) for w in weeks_list.split(",") if w
                )
            continue

        if line.startswith("SINGLE "):
            for item in line.split()[1:]:
                phase_token, week = item.split(":")
                extra_single[int(phase_token)] = int(week)
            continue

        if line.startswith("FRONT "):
            front_phases = tuple(
                int(p) for p in line.split()[1].split(",") if p
            )
            continue

        if line.startswith("PROGRAM "):
            for item in line.split()[1:]:
                phase_token, weeks_list = item.split(":")
                program_weeks[int(phase_token)] = tuple(
                    int(w) for w in weeks_list.split(",") if w
                )
            continue

        if line.startswith("SCHED ") or line.startswith("BASE "):
            parts = line.split()
            is_base = parts[0] == "BASE"
            weeks_to_race = int(parts[1])
            phases_split: dict[int, list[int]] = {}
            for item in parts[2:]:
                phase_token, weeks_list = item.split(":")
                phases_split[int(phase_token)] = [
                    int(w) for w in weeks_list.split(",") if w
                ]
            if is_base:
                base_schedule = {
                    "weeks": weeks_to_race,
                    "phases": phases_split,
                }
            else:
                schedules.append({"weeks": weeks_to_race, "phases": phases_split})
            continue

        parts = line.split(None, 3)
        if len(parts) < 4:
            raise ValueError(f"строка без тела: {line!r}")
        phase_token, week_token, kind, body = parts
        phase = int(phase_token.lstrip("Pp"))
        week = int(week_token)
        key = f"{phase}:{week}"
        # Разделитель «|» в исходнике — только для глаз, в данных его нет.
        body = body.lstrip("| ").strip()

        if kind == "note":
            notes.append({"phase": phase, "week": week, "text": body})
            continue

        if kind == "cap":
            cap_parts = body.split()
            zone = cap_parts[0]
            fraction = float(cap_parts[1])
            ceiling_km = float(cap_parts[2]) if len(cap_parts) > 2 else None
            entry = weeks.setdefault(key, {"phase": phase, "week": week,
                                           "sessions": [], "caps": []})
            entry["caps"].append({
                "zone": zone,
                "fraction_of_week": fraction,
                "ceiling_km": ceiling_km,
            })
            continue

        entry = weeks.setdefault(key, {"phase": phase, "week": week,
                                       "sessions": [], "caps": []})
        session_kind = kind[:-1] if kind.endswith("2") and kind[:-1] in (
            "R", "T", "I") else kind
        # T3 — это третья колонка таблицы (ТЗ), а не отдельный вид работы.
        if session_kind == "T3":
            session_kind = "T"
        session = {
            "kind": session_kind,
            "label": session_label(session_kind, body),
            "body": body,
        }
        if session_kind == "ACC":
            # Бег с ускорением: дистанция и прирост темпа.
            parts = body.split()
            distance = parse_amount(parts[0])[0] or 0.0
            growth = 5.0
            final_zone = "I"
            if "pace_growth" in parts:
                index = parts.index("pace_growth")
                if index + 1 < len(parts):
                    growth = float(parts[index + 1])
            if "final_zone" in parts:
                index = parts.index("final_zone")
                if index + 1 < len(parts):
                    final_zone = parts[index + 1]
            session["distance_m"] = distance
            session["pace_growth_sec_per_400m"] = growth
            session["final_zone"] = final_zone
            session["sets"] = []
            session["flat"] = []
        elif session_kind == "FILL":
            session["sets"] = []
            session["flat"] = []
        elif session_kind == "LONG":
            session["sets"] = []
            session["flat"] = []
        elif session_kind == "RACE":
            session["sets"] = []
            session["flat"] = []
        elif session_kind == "ACC":
            session["sets"] = []
            session["flat"] = []
        else:
            parsed = parse_body(body)
            session["sets"] = parsed["sets"]
            session["flat"] = parsed["flat"]
        entry["sessions"].append(session)

    for key, entry in weeks.items():
        entry["notes"] = [n["text"] for n in notes
                          if f"{n['phase']}:{n['week']}" == key]

    phases: dict[str, list[dict[str, Any]]] = {}
    for key, entry in sorted(weeks.items(), key=lambda kv: (kv[1]["phase"], kv[1]["week"])):
        phase_key = str(entry["phase"])
        phases.setdefault(phase_key, []).append(entry)

    return {
        "_source": "Daniels' Running Formula, Табл. 19.1 — программа для дистанций "
                   "5000-15000 м",
        "_source_file": "reference/daniels/training_plan_19_1.txt",
        "_parsed_by": "tools/parse_daniels_plan.py",
        "_zone_names": ZONE_NAMES,
        "_zone_full": ZONE_FULL,
        "phase_map": phase_map,
        "schedules": schedules,
        "base_schedule": base_schedule,
        "extra_phases": list(extra_phases),
        "extra_plans": {str(k): list(v) for k, v in extra_plans.items()},
        "extra_single": {str(k): v for k, v in extra_single.items()},
        "front_phases": list(front_phases),
        "program_weeks": {str(k): list(v) for k, v in program_weeks.items()},
        "phases": phases,
    }


def session_label(kind: str, body: str) -> str:
    """Короткое название тренировки по виду работы."""
    if kind == "FILL":
        return "Лёгкий бег"
    if kind == "LONG":
        return "Длинный бег"
    if kind == "RACE":
        return "Соревнование"
    if kind == "ACC":
        return "Бег с ускорением"
    return {
        "R": "Работа в повторном темпе",
        "T": "Работа в пороговом темпе",
        "I": "Работа в интервальном темпе",
        "M": "Работа в марафонском темпе",
    }.get(kind, kind)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="только проверить, что JSON соответствует исходнику")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"нет исходника: {SRC}", file=sys.stderr)
        return 1

    parsed = parse(SRC.read_text(encoding="utf-8"))
    payload = json.dumps(parsed, ensure_ascii=False, indent=1, sort_keys=True)

    if args.check:
        if not DST.exists():
            print(f"нет разобранного файла: {DST}", file=sys.stderr)
            return 1
        current = DST.read_text(encoding="utf-8")
        if current.rstrip("\n") != payload.rstrip("\n"):
            print("РАСХОЖДЕНИЕ: JSON разошёлся с исходником", file=sys.stderr)
            return 1
        print("OK: JSON соответствует исходнику")
        return 0

    DST.write_text(payload + "\n", encoding="utf-8")
    weeks = sum(len(entries) for entries in parsed["phases"].values())
    print(f"written: {DST}")
    print(f"фаз: {len(parsed['phases'])} · недель: {weeks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
