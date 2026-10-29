#!/usr/bin/env python3
"""Пересчёт счётчиков спецификации DOMAIN-SPEC.html и проверка шапки.

Использование:
    python3 scripts/count_spec.py /home/tsybriki/projects/coach-app/DOMAIN-SPEC.html

Печатает фактические значения и, если строка в шапке расходится — код 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def count(src: str) -> dict[str, int]:
    # Вопросы — ТОЛЬКО список раздела «Вопросы». Селектор `li>b` без привязки
    # к разделу ловит ещё и пункты панели подтверждённых инвариантов (там тоже
    # `<li><b>I1</b> — ...`), из-за чего счётчик завышался.
    questions_block = ""
    m = re.search(r'<section id="p">(.*?)</section>', src, re.S)
    if m:
        questions_block = m.group(1)

    return {
        # карточки сущностей: <div class="ent"> — по одной на сущность
        "entities": len(re.findall(r'class="ent"', src)),
        # инварианты: <td class="n">I<N></td> — только в таблице инвариантов
        "invariants": len(re.findall(r'<td class="n">I\d+</td>', src)),
        # вопросы: пункты списка раздела «Вопросы» (<ol class="probs">)
        "questions": len(re.findall(r'<li>', questions_block)),
        # подтверждённые инварианты: строки с классом confirmed
        "confirmed": len(re.findall(r'<tr class="confirmed"', src)),
        # номера подтверждённых — для проверки уникальности нумерации
        "confirmed_ids": re.findall(
            r'<tr class="confirmed"><td class="n">(I\d+)</td>', src),
        # все номера инвариантов — для проверки сквозной нумерации
        "all_ids": re.findall(r'<td class="n">(I\d+)</td>', src),
    }


def header(src: str) -> str | None:
    m = re.search(r'<div class="meta">Coach App · v[\d.]+ · ([^<]+)</div>', src)
    return m.group(1) if m else None


def md_counters(path: Path) -> dict[str, int] | None:
    """Счётчики из MD-источника: строка «Coach App · vX · N сущностей · …»."""
    if not path.exists():
        return None
    md = path.read_text(encoding="utf-8")
    m = re.search(r"Coach App · v[\d.]+ · (\d+) сущностей · (\d+) инвариантов "
                  r"\((\d+) подтверждено\) · (\d+) вопросов", md)
    if not m:
        return None
    e, i, ok, q = (int(x) for x in m.groups())
    return {"entities": e, "invariants": i, "confirmed": ok, "questions": q}


def main() -> int:
    args = sys.argv[1:]
    html_path = Path(args[0]) if args else Path("DOMAIN-SPEC.html")
    md_path = Path(args[1]) if len(args) > 1 else Path("specs/domain/DOMAIN-SPEC.md")
    if not html_path.exists():
        print(f"нет файла: {html_path}", file=sys.stderr)
        return 2

    src = html_path.read_text(encoding="utf-8")
    c = count(src)
    hdr = header(src)

    print(f"сущностей: {c['entities']}")
    print(f"инвариантов: {c['invariants']}")
    print(f"вопросов: {c['questions']}")
    print(f"подтверждено: {c['confirmed']}")
    if hdr:
        print(f"шапка: {hdr}")

    if hdr is None:
        print("В шапке нет строки со счётчиками", file=sys.stderr)
        return 1

    missing = [
        label
        for label, key in (("сущностей", "entities"),
                           ("инвариантов", "invariants"),
                           ("вопросов", "questions"))
        if not re.search(rf"\b{c[key]}\b", hdr)
    ]
    if missing:
        print(f"шапка не совпадает: не найдены значения для {', '.join(missing)}",
              file=sys.stderr)
        return 1

    # Слово-маркер раздела в шапке: раздел переименован из «Проблемы» в «Вопросы»,
    # но правка шапки идёт текстом — сверяем, что маркер тот, что в файле.
    section_marker = "вопросов" if "вопросов" in hdr else "проблемы"
    if section_marker == "вопросов" and "4 · Вопросы" not in src:
        print("в шапке «вопросов», а раздел так не называется", file=sys.stderr)
        return 1

    # Число подтверждённых в шапке, если оно есть, должно совпадать
    m = re.search(r"\((\d+)\s+подтверждено\)", hdr)
    if m and int(m.group(1)) != c["confirmed"]:
        print(f"шапка не совпадает: подтверждено {m.group(1)} "
              f"в шапке, {c['confirmed']} в файле", file=sys.stderr)
        return 1

    # Нумерация инвариантов должна быть сквозной с 1 и без дублей.
    # Проверяем, потому что перенумерация после удаления строк — регулярная
    # операция, и дубль номера проходит молча.
    ids = c["all_ids"]
    expected = [f"I{i}" for i in range(1, len(ids) + 1)]
    if ids != expected:
        dupes = {i for i in ids if ids.count(i) > 1}
        print(f"нумерация инвариантов не сквозная: ожидалось {expected[:3]}…"
              f" получено {ids[:3]}…"
              + (f"; дубли: {sorted(dupes)}" if dupes else ""),
              file=sys.stderr)
        return 1

    if len(set(c["confirmed_ids"])) != len(c["confirmed_ids"]):
        print("подтверждённые инварианты содержат дубли номеров", file=sys.stderr)
        return 1

    # сверка с MD-источником: HTML собран из устаревшего MD — частая ошибка
    mc = md_counters(md_path)
    if mc:
        diffs = []
        for key, label in (("entities", "сущностей"), ("invariants", "инвариантов"),
                           ("confirmed", "подтверждено"), ("questions", "вопросов")):
            if mc[key] != c[key]:
                diffs.append(f"{label}: MD {mc[key]} ≠ HTML {c[key]}")
        if diffs:
            print("HTML разошёлся с MD-источником:", file=sys.stderr)
            for d in diffs:
                print("  " + d, file=sys.stderr)
            return 1
        print(f"сверено с MD: {md_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
