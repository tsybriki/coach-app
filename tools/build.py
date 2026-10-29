#!/usr/bin/env python3
"""
build.py — пересобрать все артефакты Coach App из источников правды.

Запуск:
    python3 tools/build.py

Источники правды (MD + данные + SVG):
  specs/domain/DOMAIN-SPEC.md        доменная модель
  specs/logical/LOGICAL.md            логический уровень
  specs/design/*.md                   дизайн контрактного и физического уровней

Производные (HTML):
  DOMAIN-SPEC.html                    рисуется из specs/domain/
  LOGICAL.html                        рисуется из specs/logical/
  DESIGN.html                         рисуется из specs/design/

Порядок: сначала HTML (из MD), потом проверки.
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPECS = os.path.join(ROOT, "specs")

STEPS = [
    ("доменная модель", ["tools/render_spec.py",
                          "specs/domain/DOMAIN-SPEC.md", "DOMAIN-SPEC.html"]),
    ("логический уровень", ["tools/render_logical.py",
                             "specs/logical/LOGICAL.md", "LOGICAL.html"]),
    ("дизайн", ["tools/render_design.py",
                "specs/design", "DESIGN.html"]),
]


def run(args: list[str]) -> bool:
    r = subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out:
        print(out)
    if r.returncode != 0:
        print(f"  ОШИБКА: {' '.join(args)}\n{err}")
        return False
    return True


def main() -> int:
    print("== сборка HTML из MD ==")
    for label, args in STEPS:
        print(f"-- {label}")
        if not run(args):
            return 1

    print("== проверки ==")
    for label, script in [("утечки знания о хранилище", "tools/check_storage_leaks.py"),
                           ("покрытие инвариантов", "tools/check_invariant_coverage.py"),
                           ("счётчики спецификации", "tools/count_spec.py")]:
        print(f"-- {label}")
        if not run([script]):
            return 1

    print("\nготово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
