#!/usr/bin/env python3
"""
build_design_md.py — собрать единый DESIGN.md из девяти файлов дизайна.

Запуск:
    python3 tools/build_design_md.py

На входе:  design/*.md  (девять файлов)
На выходе: DESIGN.md — весь дизайн одним текстом, чтобы читать и сверять по нему
           при реализации, а не только по HTML.

Файлы не переписываются, а склеиваются с разделителями. Каждый файл сохраняет
свою структуру; DESIGN.md — навигация по ним.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESIGN = os.path.join(ROOT, "specs", "design")
OUT = os.path.join(ROOT, "specs", "design", "DESIGN.md")

FILES = [
    ("00-index.md", "Карта", "что уже есть и что предложено"),
    ("01-контракты.md", "Контракты", "как подсистемы общаются"),
    ("02-хранилище.md", "Хранилище", "где состояние и как пишется"),
    ("03-BFF.md", "BFF", "HTTP-слой"),
    ("04-хостинг.md", "Хостинг", "доступ: в базе по локальной сети"),
    ("05-клиент.md", "Клиент", "PWA, офлайн, очередь команд"),
    ("06-адаптеры.md", "Адаптеры", "Garmin, нарратор, Дэниэлс (правила)"),
    ("07-реализация.md", "Реализация", "этапы и что не входит в базу"),
    ("08-развилки.md", "Решения", "10 развилок закрыты"),
]


def main() -> int:
    if not os.path.isdir(DESIGN):
        print(f"MISSING: {DESIGN}", file=sys.stderr)
        return 1

    parts: list[str] = []
    A = parts.append

    A("# Coach App — дизайн")
    A("")
    A("> **Статус:** дизайн готов, развилки закрыты. Код не начат — ждёт отдельной команды. · 26.10.2026")
    A("> **Источник правды:** `design/*.md` — девять отдельных файлов. Этот `DESIGN.md` "
      "собран скриптом `build_design_md.py`, руками не править.")
    A("> **Сборка в HTML:** `render_design.py` → `DESIGN.html` (читается с телефона).")
    A("")

    A("## Навигация")
    A("")
    A("| Файл | Раздел | О чём |")
    A("|---|---|---|")
    for fname, short, sub in FILES:
        p = os.path.join(DESIGN, fname)
        if not os.path.exists(p):
            print(f"MISSING: {p}", file=sys.stderr)
            return 1
        A(f"| `design/{fname}` | {short} | {sub} |")
    A("")

    for fname, short, sub in FILES:
        p = os.path.join(DESIGN, fname)
        with open(p, encoding="utf-8") as f:
            md = f.read().rstrip()
        # заголовок первого уровня файла → второй уровень в сборке
        md = re.sub(r"^#\s+", "## ", md, count=1)
        A("---")
        A("")
        A(md)
        A("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    print(f"written: {OUT} ({os.path.getsize(OUT)} bytes)")
    print(f"sections={len(FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
