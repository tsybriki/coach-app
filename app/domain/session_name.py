"""
session_name.py — название тренировки из её состава.

Название тренировки — это **пересказ её содержимого**: «Лёгкий бег +
отрезки», «Лёгкий бег», «Длинный бег», «Темповый тест 3К». Раньше
название бралось из фокуса запроса, а фокус недели копировался в
каждую тренировку — и все семь пробежек недели назывались «Проверяем
форму на контрольной точке». Читатель не мог отличить лёгкую пробежку
от длинной, а длинный бег с отрезками от лёгкого без отрезков.

Правило: название собирается из **состава** сессии — из того, что в ней
есть:

  - основа (лёгкий бег / длинный бег / темповая работа / тест),
  - отрезки, если они есть,
  - ОФП, если оно есть.

Что в сессии есть — видно по шагам: отрезки несут `daniels_zone`,
ОФП — `ofp: true`. Поэтому название выводится из шагов, а не из
фокуса: так оно не может разойтись с содержимым.

Правило темпа: лёгкий темп — **5:30**, а не 5:13.

Почему 5:30. Темп 5:13 — это «E» по таблице Дэниэлса для VDOT 51, то
есть верх лёгкой зоны: 313 секунд на километр. Бег в этом темпе на
длинной дистанции — это уже работа на верхней границе зоны, а не
лёгкий бег. По этому темпу «лёгкий бег» 40 минут набирает 6.5 км и
упирается в верх Z2 (HR 135) уже на 10-м километре.

5:30 — это 330 секунд на километр: середина лёгкой зоны для этого
VDOT. Лёгкий бег в этом темпе держит HR ниже 135 на всей дистанции,
и объём недели в километрах становится честным: 56 км недельного
объёма — это 56 км именно лёгкого бега.

Темп лёгкой зоны в приложении — 5:30 во всех местах, где речь о
лёгком беге. Темпы для отрезков и тестов не трогаем: там темп и есть
содержание работы.
"""
from __future__ import annotations

from app.domain.entities import Step
from app.domain.enums import Sport
from app.domain.methodology import EASY_PACE_MIN_PER_KM, EASY_PACE_SEC_PER_KM

__all__ = [
    "EASY_PACE_MIN_PER_KM",
    "EASY_PACE_SEC_PER_KM",
    "easy_pace_sec_per_km",
    "session_name",
    "step_description",
]

# Темп лёгкого бега — 5:30 на километр.
#
# Не 5:13: «E» по таблице Дэниэлса для VDOT 51 — это верх лёгкой
# зоны: 313 секунд на километр. Бег в этом темпе на длинной дистанции
# — это уже работа на верхней границе зоны, а не лёгкий бег. По этому
# темпу «лёгкий бег» 40 минут набирает 6.5 км и упирается в верх Z2
# (HR 135) уже на 10-м километре.
#
# 5:30 — это 330 секунд на километр: середина лёгкой зоны для этого
# VDOT. Лёгкий бег в этом темпе держит HR ниже 135 на всей дистанции,
# и объём недели в километрах становится честным: 56 км недельного
# объёма — это 56 км именно лёгкого бега.
#
# Константа живёт в `methodology.py`: там же, где зоны и таблица
# темпов, иначе домен разваливается на два слоя с общей константой.


def easy_pace_sec_per_km(pace_by_zone: dict[str, float]) -> float | None:
    """Темп лёгкого бега — 5:30, а не «E» из таблицы Дэниэлса.

    «E» для VDOT 51 — это 5:13, то есть верх лёгкой зоны. Бег в этом
    темпе на длинной дистанции держит HR у верхней границы Z2 и
    перестаёт быть лёгким.

    Здесь не таблица Дэниэлса, а решение по этому спортсмену: 5:30 —
    середина его лёгкой зоны. Темпы для отрезков и тестов не трогаем.
    """
    if not pace_by_zone:
        return None
    return EASY_PACE_SEC_PER_KM

# Названия основы сессии — по виду работы.
BASE_BY_KIND = {
    "easy": "Лёгкий бег",
    "long": "Длинный бег",
    "quality": "Качественная работа",
    "tempo": "Темповая работа",
    "race_pace": "Гонка-темп",
    "progression": "Прогрессия темпа",
    "intervals": "Интервалы",
    "bike": "Велосипед",
    "swim": "Плавание",
    "ofp": "ОФП",
    "strength": "Силовая",
}

# Названия по виду спорта — когда вид работы изнутри не читается.
BASE_BY_SPORT = {
    Sport.BIKE: "Велосипед",
    Sport.SWIM: "Плавание",
    Sport.OFP: "ОФП",
    Sport.STRENGTH: "Силовая",
    Sport.MOBILITY: "Растяжка",
}


def _has_strides(steps: list[Step]) -> bool:
    """Есть ли в сессии отрезки.

    Отрезок — шаг с зоной Дэниэлса `R` (интенсивный) или `I`: обычный
    лёгкий шаг помечен `E`.
    """
    for step in steps:
        fv = step.focus_value or {}
        zone = fv.get("daniels_zone")
        if zone in ("R", "I"):
            return True
        if fv.get("set_reps") and fv.get("pace_min_per_km"):
            return True
    return False


def _has_ofp(steps: list[Step]) -> bool:
    """Есть ли в сессии ОФП."""
    return any(bool((s.focus_value or {}).get("ofp")) for s in steps)


def _base_name(kind: str | None, sport: Sport | None,
               steps: list[Step]) -> str:
    """Основа названия: что за работа."""
    name = BASE_BY_KIND.get((kind or "").lower())
    if name:
        return name
    if sport is not None:
        name = BASE_BY_SPORT.get(sport)
        if name:
            return name
    # Ничего не знаем — показываем то, что есть: шаги.
    if steps:
        return "Тренировка"
    return "Тренировка"


def session_name(kind: str | None,
                 sport: Sport | None,
                 steps: list[Step],
                 base: str | None = None) -> str:
    """Название тренировки — из её состава.

    `base` — основа, если она уже известна (например, «Лёгкий бег»
    для длинного пробега в форме фазы). Дополняется отрезками и ОФП.
    """
    name = base or _base_name(kind, sport, steps)
    parts = [name]
    if _has_strides(steps) and "отрезки" not in name.lower():
        parts.append("отрезки")
    if _has_ofp(steps) and "офп" not in name.lower():
        parts.append("ОФП")
    return " + ".join(parts)


def step_description(step: Step) -> str:
    """Человеческое описание шага — из его сути.

    Шаг с дистанцией описывается расстоянием, шаг со временем —
    временем. Раньше описание бралось из `notes`, а у шагов планировщика
    `notes` пустой, и в карточке тренировки вместо содержимого стояло
    пустое место.
    """
    fv = step.focus_value or {}
    if fv.get("ofp"):
        reps = fv.get("reps")
        return f"ОФП · {reps}" if reps else "ОФП"
    if fv.get("reps") and step.target_type.value == "reps":
        return f"ОФП · {fv['reps']}"
    pace = fv.get("pace_min_per_km")
    zone = fv.get("zone")
    if step.target_type.value == "distance":
        km = step.target_value / 1000.0
        base = f"{km:.1f} км"
    else:
        base = f"{round(step.duration_min)} мин"
    bits = [base]
    if zone:
        bits.append(str(zone))
    if pace:
        bits.append(f"@{pace}/км")
    if fv.get("hr_target"):
        bits.append(f"HR {fv['hr_target']}")
    return " · ".join(bits)
