"""Темпы на текущей форме — для карточки профиля.

Карточка атлета показывает темпы по зонам методики, посчитанные по текущей
форме атлета (VDOT). Темпы считает домен: клиент не знает таблицы Дэниэлса
и не должен её дублировать.

Что тут проверяется:

- темпы по зонам считаются по VDOT из справочника;
- лёгкий бег — 5:40 (решение по спортсмену, а не «E» из таблицы);
- без VDOT темпов нет — это «не задано», а не ноль;
- без справочника — тоже нет, и ошибки не происходит;
- названия зон — по-русски, без кодов.

Имя тестов: `test_i49_...` — инвариант I49 из спецификации.
"""
from __future__ import annotations

from pathlib import Path

from app.adapters.daniels import load_paces
from app.domain.entities import Athlete
from app.domain.methodology import (
    form_paces,
    pace_zone_rows,
)

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

HR_ZONES = {
    "Z1": (100, 118),
    "Z2": (118, 135),
    "Z3": (136, 150),
    "Z4": (150, 160),
    "Z5": (160, 168),
    "Z6": (169, 172),
    "Z7": (173, 182),
}


def athlete(vdot: float = 48.0) -> Athlete:
    return Athlete(vdot=vdot, hr_zones=HR_ZONES, hr_max=182, rhr=54, lth=164)


# ------------------------------------------------------------------ I49


def test_i49_form_paces_from_vdot():
    """I49: темпы на текущей форме считаются по VDOT.

    Таблица Дэниэлса для VDOT 48: порог 264 с/км (4:24), интервал
    243 (4:03), повторный 225 (3:45), марафонский 281 (4:41).
    """
    paces = load_paces(REFERENCE)

    result = form_paces(athlete(), paces)

    assert result["T"] == "4:24"
    assert result["I"] == "4:03"
    assert result["R"] == "3:45"
    assert result["M"] == "4:41"


def test_i49_easy_pace_is_athlete_decision_not_table():
    """Лёгкий бег — 5:40, а не «E» из таблицы (5:28 для VDOT 48).

    Таблица даёт верх лёгкой зоны. План бежит лёгкий в 5:40 — карточка
    профиля обязана показывать то же, иначе экран врать относительно
    плана будет.
    """
    paces = load_paces(REFERENCE)

    result = form_paces(athlete(), paces)

    assert result["E"] == "5:40"


def test_i49_no_vdot_means_no_paces():
    """Без формы темпов нет — это «не задано», а не ноль.

    Профиль без VDOT — пустой профиль, а не ошибка. Карточка в этом
    случае показывает пустоту, а не выдуманные темпы.
    """
    paces = load_paces(REFERENCE)

    result = form_paces(athlete(vdot=0.0), paces)

    assert result == {}


def test_i49_no_reference_means_no_paces():
    """Без справочника темпов нет, и ошибки не происходит.

    Справочник — часть репозитория, но приложение обязано работать и
    без него: методика просто не знает темпов.
    """
    result = form_paces(athlete(), None)

    assert result == {}


def test_i49_zone_rows_have_russian_names():
    """Строки темпов — с русскими названиями зон.

    Коды «E», «T», «I» — внутренний язык методики, на экране они
    ничего не значат.
    """
    paces = load_paces(REFERENCE)

    rows = pace_zone_rows(athlete(), paces)

    names = [row["name"] for row in rows]
    assert names == ["Лёгкий бег", "Марафонский темп", "Пороговый темп",
                     "Интервальный темп", "Повторный темп"]
    # Название зоны методики — по-русски, без кодов.
    for row in rows:
        assert row["zone"] in ("E", "M", "T", "I", "R")
        assert row["name"]


def test_i49_zone_rows_are_empty_without_paces():
    """Без темпов строк нет — карточка не рисует пустой список зон."""
    rows = pace_zone_rows(athlete(), None)

    assert rows == []
