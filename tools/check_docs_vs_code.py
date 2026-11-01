#!/usr/bin/env python3
"""
check_docs_vs_code.py — документы не врут о коде.

Проблема: документы репозитория отстают от кода молча. `.hermes.md` и
`specs/design/00-index.md` утверждали «18 сущностей, 43 инварианта», «Garmin
не подключён», «код не начат» — тогда как в коде было 21 сущность, 44
инварианта, Garmin был подключён, а код давно был написан. Ничего не падало.

Этот чекер сверяет то, что можно посчитать, а не то, что можно пересказать:

  1. Счётчики домена в `.hermes.md` и `README.md` — против фактических строк
     `specs/domain/DOMAIN-SPEC.md`.
  2. Число команд в `specs/design/01-контракты.md` — против `CommandType`
     в `app/domain/enums.py`.
  3. Число маршрутов в `specs/design/03-BFF.md` — против `@router` в коде.
  4. Разделы клиента в `specs/design/05-клиент.md` — против `SCREENS`
     в `client/app.js`.
  5. Число сущностей в шапке `README.md` и `.hermes.md` — против счётчика
     спецификации.

Запуск:
    .venv/bin/python tools/check_docs_vs_code.py

Код выхода: 0 — расхождений нет, 1 — есть.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOMAIN_MD = ROOT / "specs" / "domain" / "DOMAIN-SPEC.md"
HERMES_MD = ROOT / ".hermes.md"
README_MD = ROOT / "README.md"
CONTRACTS_MD = ROOT / "specs" / "design" / "01-контракты.md"
BFF_MD = ROOT / "specs" / "design" / "03-BFF.md"
CLIENT_MD = ROOT / "specs" / "design" / "05-клиент.md"
ENUMS_PY = ROOT / "app" / "domain" / "enums.py"
ROUTES_PY = ROOT / "app" / "api" / "routes.py"
CLIENT_JS = ROOT / "client" / "app.js"


def domain_facts() -> tuple[int, int, int]:
    """Сущности, инварианты и вопросы — из строк MD-источника."""
    if not DOMAIN_MD.exists():
        return (0, 0, 0)
    text = DOMAIN_MD.read_text(encoding="utf-8")
    header = re.search(
        r"Coach App · v[\d.]+ · (\d+) сущностей · (\d+) инвариантов "
        r"\((\d+) подтверждено\) · (\d+) вопросов",
        text,
    )
    if not header:
        return (0, 0, 0)
    entities, invariants, _confirmed, questions = (int(x) for x in header.groups())
    return (entities, invariants, questions)


def command_types() -> set[str]:
    """Типы команд из перечисления в коде."""
    if not ENUMS_PY.exists():
        return set()
    text = ENUMS_PY.read_text(encoding="utf-8")
    block = re.search(r"class CommandType\(StrEnum\):(.*?)(?=\n\nclass |\Z)", text, re.S)
    if not block:
        return set()
    return set(re.findall(r'=\s*"([a-z_]+)"', block.group(1)))


def bff_routes() -> set[str]:
    """Маршруты BFF из кода: `GET /api/v1/week/{season_week}`.

    В коде путь задан относительно префикса `router = APIRouter(prefix="/api/v1")`,
    в документе — полным. Здесь приводим к виду документа.
    """
    if not ROUTES_PY.exists():
        return set()
    text = ROUTES_PY.read_text(encoding="utf-8")
    prefix = re.search(r'APIRouter\(prefix="([^"]+)"\)', text)
    prefix = prefix.group(1) if prefix else ""
    routes: set[str] = set()
    for method, path in re.findall(
        r'@router\.(get|post)\("([^"]+)"\)', text
    ):
        routes.add(f"{method.upper()} {_normalize_path(prefix + path)}")
    return routes


def client_screens() -> list[str]:
    """Разделы нижней навигации из клиента."""
    if not CLIENT_JS.exists():
        return []
    text = CLIENT_JS.read_text(encoding="utf-8")
    block = re.search(r"const SCREENS = \[(.*?)\];", text, re.S)
    if not block:
        return []
    return re.findall(r"\['([a-z_]+)',\s*'([^']+)'", block.group(1))


def _normalize_path(path: str) -> str:
    """Имя параметра пути в документе и в коде может различаться.

    Документ пишет `/week/{n}`, код — `/week/{season_week}`. Сравнивать надо
    по форме пути, а не по имени параметра: иначе чекер ругается на
    безобидное расхождение и перестаёт быть полезным.
    """
    return re.sub(r"\{[^}]+\}", "{}", path)


def check_counters(problems: list[str]) -> None:
    """Счётчики домена в `.hermes.md` и `README.md`."""
    entities, invariants, questions = domain_facts()
    if not entities:
        problems.append("в DOMAIN-SPEC.md не разобрана строка счётчиков")
        return

    for path in (HERMES_MD, README_MD):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # «21 сущность» / «21 сущностей» / «18 сущностей»
        ent = re.search(r"(\d+)\s+сущност", text)
        if ent and int(ent.group(1)) != entities:
            problems.append(
                f"{path.name}: сущностей {ent.group(1)}, а в спецификации {entities}"
            )
        inv = re.search(r"(\d+)\s+инвариант", text)
        if inv and int(inv.group(1)) != invariants:
            problems.append(
                f"{path.name}: инвариантов {inv.group(1)}, а в спецификации {invariants}"
            )
        # «5 вопросов» / «6 вопросов»
        que = re.search(r"(\d+)\s+вопросов", text)
        if que and int(que.group(1)) != questions:
            problems.append(
                f"{path.name}: вопросов {que.group(1)}, а в спецификации {questions}"
            )


def check_commands(problems: list[str]) -> None:
    """Число типов команд в контрактах — против `CommandType`."""
    types = command_types()
    if not types:
        problems.append("не найден перечень CommandType в app/domain/enums.py")
        return
    if not CONTRACTS_MD.exists():
        return
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    declared = re.search(r"Полный список — (\d+) тип", text)
    if not declared:
        problems.append(
            "в specs/design/01-контракты.md нет строки «Полный список — N тип»"
        )
        return
    claimed = int(declared.group(1))
    if claimed != len(types):
        problems.append(
            f"в контрактах заявлено {claimed} типов команд, в коде {len(types)}"
        )


def check_routes(problems: list[str]) -> None:
    """Маршруты, перечисленные в `03-BFF.md`, — против кода."""
    routes = bff_routes()
    if not routes:
        problems.append("не найдены маршруты в app/api/routes.py")
        return
    if not BFF_MD.exists():
        return
    text = BFF_MD.read_text(encoding="utf-8")
    # Блок с маршрутами: строки `GET  /api/v1/...`
    block = re.search(r"```\n(GET |POST).*?```", text, re.S)
    if not block:
        problems.append("в specs/design/03-BFF.md не найден блок с маршрутами")
        return
    documented: set[str] = set()
    for method, path in re.findall(r"(GET|POST)\s+(/\S+)", block.group(0)):
        documented.add(f"{method} {_normalize_path(path)}")
    missing = sorted(routes - documented)
    if missing:
        problems.append(
            "маршруты в коде, которых нет в specs/design/03-BFF.md: "
            + ", ".join(missing)
        )


def check_client_screens(problems: list[str]) -> None:
    """Разделы клиента — против `SCREENS` в коде."""
    screens = client_screens()
    if not screens:
        problems.append("не найден список SCREENS в client/app.js")
        return
    if not CLIENT_MD.exists():
        return
    text = CLIENT_MD.read_text(encoding="utf-8")
    claimed = re.search(r"Разделов \*\*(\d+)\*\*", text)
    if not claimed:
        problems.append(
            "в specs/design/05-клиент.md нет строки «Разделов **N**»"
        )
        return
    count = int(claimed.group(1))
    if count != len(screens):
        problems.append(
            f"в 05-клиент.md заявлено {count} разделов, в client/app.js — {len(screens)}"
        )


def main() -> int:
    problems: list[str] = []

    check_counters(problems)
    check_commands(problems)
    check_routes(problems)
    check_client_screens(problems)

    if problems:
        print("ПРОВАЛ: документы расходятся с кодом")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    entities, invariants, questions = domain_facts()
    print(f"сущностей: {entities} · инвариантов: {invariants} · вопросов: {questions}")
    print(f"команд: {len(command_types())} · маршрутов: {len(bff_routes())} "
          f"· разделов клиента: {len(client_screens())}")
    print("OK: документы не врут о коде")
    return 0


if __name__ == "__main__":
    sys.exit(main())
