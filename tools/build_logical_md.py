#!/usr/bin/env python3
"""
build_logical_md.py — собрать LOGICAL.md из logical.json.

Запуск:
    python3 tools/build_logical_md.py

На входе:  logical.json (source of truth)
На выходе: LOGICAL.md — текстовая копия логического уровня, чтобы читать и
           сверять по нему при реализации, а не только по HTML.

MD собирается скриптом. Руками не править.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "specs", "logical", "logical.json")
OUT = os.path.join(ROOT, "specs", "logical", "LOGICAL.md")


def build(d: dict) -> str:
    m = d["meta"]
    out: list[str] = []
    A = out.append

    A("# Coach App — логический уровень")
    A("")
    A(f"> **Статус:** {d['subtitle']}")
    A(f"> **Версия:** v{d['version']} · подсистем: {m['subsystems']} · "
      f"взаимодействий: {m['interactions']} · развилок: {m['forks']}")
    A("> **Источник правды:** `logical.json`. Этот файл собирается скриптом "
      "`build_logical_md.py`, руками не править.")
    A("")

    A("## Что это")
    A("")
    A(d["lead"])
    A("")

    A("## Уровни абстракции")
    A("")
    A("| Уровень | Вопрос | Состояние | Что это значит |")
    A("|---|---|---|---|")
    for lv in d["levels"]:
        A(f"| **{lv['name']}** | {lv['q']} | {lv['state']} | {lv['detail']} |")
    A("")

    A("## 1. Схема")
    A("")
    A(d["diagram"]["caption"])
    A("")
    A("Полосы сверху вниз:")
    A("")
    for s in d["diagram"]["strips"]:
        A(f"- **{s['title']}** — {s.get('sub', '')}")
        for ln in s.get("lines", []):
            A(f"  - {ln}")
        if s.get("foot"):
            A(f"  - _{s['foot']}_")
    A("")
    A("Связи (номера — как на схеме):")
    A("")
    A("| # | Откуда | Куда | Что | Когда |")
    A("|---|---|---|---|---|")
    for it in d["interactions"]:
        A(f"| {it['n']} | {it['from']} | {it['to']} | {it['what']} | {it['when']} |")
    A("")

    A("## 2. Планировщик")
    A("")
    A(d["planner"]["lead"])
    A("")
    for i, e in enumerate(d["planner"]["entries"], 1):
        A(f"### Шаг {i} · {e['name']}")
        A("")
        A(f"**Вход:** {e['input']}")
        A("")
        for j, s in enumerate(e["steps"], 1):
            A(f"{j}. {s}")
        A("")
        A(f"- **Цифры:** {e['numbers']}")
        if e.get("have"):
            A(f"- **Есть:** {e['have']}")
        if e.get("missing"):
            A(f"- **Нет:** {e['missing']}")
        A("")

    A("## 3. Подсистемы")
    A("")
    for s in d["subsystems"]:
        A(f"### {s['name']}")
        A("")
        A(f"- **Роль:** {s['role']}")
        A(f"- **Решает:** {s['decides']}")
        A(f"- **Владеет:** {s['owns']}")
        A(f"- **Обращается к:** {s['calls']}")
        A(f"- **Граница:** {s['boundary']}")
        A("")

    A("## 4. Куда это ложится физически")
    A("")
    A(d["physical"]["lead"])
    A("")
    A("| Подсистема | Физическое размещение |")
    A("|---|---|")
    for r in d["physical"]["rows"]:
        A(f"| {r['from']} | {r['to']} |")
    A("")

    A("## 5. Развилки")
    A("")
    for f in d["forks"]:
        state = "**решено**" if f.get("decided") else "открыто"
        A(f"### {f['n']}. {f['question']}")
        A("")
        A(f"- A — {f['a']}")
        A(f"- B — {f['b']}")
        A(f"- Решение: {state}. {f['changes']}")
        A("")

    A("## 6. Замечания по текущему состоянию")
    A("")
    for n in d.get("notes", []):
        A(f"- {n}")
    A("")

    return "\n".join(out) + "\n"


def main() -> int:
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    md = build(data)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"written: {OUT} ({os.path.getsize(OUT)} bytes)")
    print(f"subsystems={len(data['subsystems'])} interactions={len(data['interactions'])} "
          f"forks={len(data['forks'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
