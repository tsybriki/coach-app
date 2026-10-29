#!/usr/bin/env python3
"""
check_storage_leaks.py — проверка: физическое хранилище знает только адаптер.

Правило (из design/02-хранилище.md):
    Никто, кроме адаптера хранилища, не знает, как состояние физически хранится.
    Доступ к данным — только через порты.

Проверяет:
  1. В коде вне app/adapters/storage/ нет импортов и упоминаний формата хранения.
  2. В дизайн-документах вне 02-хранилище.md нет знаний о формате хранения,
     кроме явно помеченных мест (import/backup/развилка про формат).

Запуск:
    python3 tools/check_storage_leaks.py
    python3 tools/check_storage_leaks.py --repo ~/projects/coach-app

Код выхода: 0 — чисто, 1 — есть утечки.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# --- маркеры физического хранилища ---
STORAGE_TOKENS = [
    r"\bsqlite3?\b", r"\bSQL\b", r"\bSELECT\b.*\bFROM\b", r"\bINSERT\b", r"\bCREATE TABLE\b",
    r"\bjson\.dump", r"\bjson\.load\b", r"\bread_text\b", r"\bwrite_text\b",
    r"\bos\.replace\b", r"\bflock\b", r"\bopen\(", r"\bPath\(", r"\bos\.path\b",
    r"\.json\b", r"\bdata/", r"\bstate/", r"\btmp\b",
]

# --- директории, которым знать положено ---
ALLOWED_CODE_DIRS = ("adapters/storage", "adapters/migrations", "tools", "tests", "migrations")

# --- места в дизайне, где знание о формате — по делу ---
# (имя файла, регулярка, обязательное пояснение рядом)
DOC_ALLOWLIST = {
    "00-index.md": [
        (r"~/coach/state", "импорт из пайплайна — одноразовая операция"),
    ],
    "01-контракты.md": [],
    "02-хранилище.md": [],   # сам документ о хранилище
    "03-BFF.md": [
        (r"storage", "имя адаптера, не формат"),
    ],
    "04-хостинг.md": [],
    "05-клиент.md": [
        (r"manifest\.json", "манифест PWA — не хранилище состояния"),
    ],
    "06-адаптеры.md": [
        (r"reference/daniels/", "пути к файлам пайплайна-источника, не хранилище приложения"),
        (r"state/workout_templates", "путь к файлу пайплайна-источника, не хранилище приложения"),
    ],
    "07-реализация.md": [
        (r"~/coach/state", "импорт из пайплайна"),
        (r"storage/files\.py", "имя адаптера"),
        (r"storage/sqlite\.py", "имя адаптера"),
        (r"SQLite-адаптер", "вторая реализация тех же портов"),
        (r"Схема в SQL", "этап 2б — работа адаптера хранилища"),
        (r"SQL-", "этап 2б — работа адаптера хранилища"),
        (r"reference/daniels/", "пути к файлам пайплайна-источника, не хранилище приложения"),
        (r"state/workout_templates", "путь к файлу пайплайна-источника, не хранилище приложения"),
    ],
    "08-развилки.md": [
        (r"SQLite", "путь развития зафиксирован, не утечка"),
        (r"файлы", "путь развития зафиксирован, не утечка"),
    ],
    # сводные документы: они пересказывают 02-хранилище.md, поэтому формат там по делу
    "DESIGN.md": [],
}


def scan_code(repo: str) -> list[str]:
    leaks: list[str] = []
    app = os.path.join(repo, "app")
    if not os.path.isdir(app):
        return leaks  # репозитория ещё нет — нечего проверять
    for root, dirs, files in os.walk(app):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        # путь относительно app/ — чтобы совпадение с allowlist было точным
        rel_root = os.path.relpath(root, app)
        if rel_root == "." or any(rel_root == d or rel_root.startswith(d + os.sep)
                                  for d in ALLOWED_CODE_DIRS):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            seen: set[int] = set()
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if i in seen:
                    continue
                for pat in STORAGE_TOKENS:
                    if re.search(pat, line):
                        seen.add(i)
                        leaks.append(f"app/{rel_root}/{fn}:{i}: {line.strip()[:100]}")
                        break
    return leaks


def scan_docs(design_dir: str) -> list[str]:
    leaks: list[str] = []
    for fn in sorted(os.listdir(design_dir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(design_dir, fn)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        if fn == "DESIGN.md":
            continue  # сводка: пересказывает 02-хранилище.md, формат там по делу
        allowed = DOC_ALLOWLIST.get(fn, [])
        for i, line in enumerate(lines, 1):
            for pat in STORAGE_TOKENS:
                if not re.search(pat, line):
                    continue
                # разрешено, если строка попадает под allowlist
                if any(re.search(ap, line) for ap, _ in allowed):
                    continue
                # или если это сам документ о хранилище
                if fn == "02-хранилище.md":
                    continue
                leaks.append(f"specs/design/{fn}:{i}: {line.strip()[:100]}")
    return leaks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.expanduser("~/projects/coach-app"),
                    help="репозиторий приложения (код)")
    ap.add_argument("--design", default=os.path.join(os.path.dirname(HERE), "specs", "design"),
                    help="папка с дизайн-документами")
    args = ap.parse_args()

    doc_leaks = scan_docs(args.design)
    code_leaks = scan_code(args.repo) if os.path.isdir(os.path.join(args.repo, "app")) else []

    print(f"дизайн: {len(doc_leaks)} утечек")
    for l in doc_leaks:
        print("  " + l)
    print(f"код:    {len(code_leaks)} утечек")
    for l in code_leaks:
        print("  " + l)

    if doc_leaks or code_leaks:
        print("\nПРОВАЛ: физическое хранилище знает не только адаптер")
        return 1
    print("\nOK: знание о формате хранения — только у адаптера")
    return 0


if __name__ == "__main__":
    sys.exit(main())
