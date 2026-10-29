#!/usr/bin/env python3
"""
check_invariant_coverage.py — каждый инвариант спецификации покрыт тестом.

Запуск:
    python3 tools/check_invariant_coverage.py

Читает инварианты из `specs/domain/DOMAIN-SPEC.md`, ищет тесты с именами
`test_i<N>_...` в `tests/` и сверяет. Номера сравниваются как числа, чтобы
`I1` и `I01` считались одним и тем же.

Код выхода: 0 — все покрыты, 1 — есть непокрытые.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "specs" / "domain" / "DOMAIN-SPEC.md"
TESTS = ROOT / "tests"


def main() -> int:
    if not SPEC.exists():
        print(f"нет файла: {SPEC}", file=sys.stderr)
        return 2

    md = SPEC.read_text(encoding="utf-8")
    invariants = re.findall(r"^\| I(\d+) \|", md, re.M)
    if not invariants:
        print("в спецификации не найдено инвариантов", file=sys.stderr)
        return 2
    numbers = {str(int(n)) for n in invariants}

    covered: set[str] = set()
    for path in TESTS.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        covered |= {str(int(n)) for n in re.findall(r"def test_i(\d+)_", text)}

    missing = sorted(numbers - covered, key=int)
    print(f"инвариантов: {len(numbers)} · покрыто тестами: {len(numbers & covered)}")
    if missing:
        print("НЕ покрыты:", ", ".join(f"I{m}" for m in missing))
        return 1
    print("OK: каждый инвариант покрыт тестом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
