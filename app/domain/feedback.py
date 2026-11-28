"""
feedback.py — субъективная оценка тренировки.

Оценка снимается **в момент привязки факта к плановой тренировке** и
потом живёт на самой тренировке: вид работы известен там же, где
оценка, и привязка факта (двусторонняя, I44) не теряется при
перезаписи факта из Garmin.

**Почему оценка живёт на тренировке, а не на факте.** Факт перезаписывается
выкачкой: `upsert` пишет сессию целиком, и всё, чего в новой выкачке нет,
пропадает. Оценку пользователь ставит один раз и потом правит — она
должна переживать выкачку. Тренировка живёт дольше факта: она остаётся
в неделе, пока неделя не пересобрана, а при пересборке выполненные
тренировки возвращаются на место (`_keep_done_workouts`).

**Вид работы — по шагам, а не по `kind`.** `kind` в данных разный у
разных источников: `easy`, `long`, `long_Z2`, `quality`, `composed`,
а программа Дэниэлса даёт `r`, `t`, `i`. Интервальная тренировка,
собранная из текста, приходит как `composed`, и по `kind` её не отличить
от лёгкой. Поэтому вид работы определяется по **зоне работы в шагах**
(`daniels_zone`, `intent`) — там, где видно, что за работа на самом
деле: `R` (повторный темп), `T` (порог), `I` (интервалы) против `E`
(лёгкая).

**Два блока оценки.** Лёгкая и длинная работа спрашивает одно: как
чувствовались ноги. Интервальная и пороговая — три: как зашёл, как
разогрелся, хотел бы ещё. Разница не в оформлении, а в том, что
спрашивается: на длинной пробежке важно «дотянул ли», а на отрезках
важна динамика внутри работы.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.entities import Workout
from app.domain.enums import Sport

__all__ = [
    "BODY_STATUS_VALUES",
    "EASY_FEEL_VALUES",
    "REP1_MENTAL_VALUES",
    "REP2_PHYSICAL_VALUES",
    "WANT_ONE_MORE_VALUES",
    "Feedback",
    "feedback_for_workout",
    "normalise_feedback",
    "workout_kind_of",
]


# ------------------------------------------------------------------ значения


# Тело (икры / поясница). Ноль — «фон», обычное состояние.
#
# Значение по умолчанию — ноль: в обычный день человек ничего не
# выбирает, и лишний тап не должен быть ценой заполнения формы.
BODY_STATUS_VALUES: dict[int, str] = {
    0: "Фон",
    -1: "Тянет",
    -2: "Ломает",
}

# Общее ощущение на лёгкой и длинной работе.
EASY_FEEL_VALUES: dict[int, str] = {
    1: "Ноги свежие",
    0: "Устали, но нормально",
    -1: "Еле вышел",
}

# 1-й отрезок: психология, общий фон.
REP1_MENTAL_VALUES: dict[str, str] = {
    "fresh": "Свежо",
    "heavy": "Тяжело заходить",
}

# 2-й отрезок: физика, разогрев.
REP2_PHYSICAL_VALUES: dict[str, str] = {
    "opened_up": "Раскрылся",
    "wooden": "Деревянный",
}

# Финиш: хотел бы сделать ещё один.
WANT_ONE_MORE_VALUES: dict[str, str] = {
    "yes": "Да",
    "enough": "Хватило",
    "definitely_no": "Точно нет",
}


# ------------------------------------------------------------------ вид работы


# Виды работы, из которых выбирается вид формы.
#
# `easy` — лёгкая и длинная: блок «общее ощущение».
# `quality` — интервальная, пороговая, повторная: три поля динамики.
KIND_EASY = "easy"
KIND_QUALITY = "quality"
KIND_OTHER = "other"

# Зоны программы Дэниэлса: повторный темп, порог, интервалы.
_DANIELS_QUALITY_ZONES = {"R", "T", "I"}

# Намерения из разбора текста: работа с отрезками.
_INTENT_QUALITY = {"interval", "vo2max", "repetition", "stride",
                   "threshold", "tempo", "fartlek"}

# `kind` — по названию вида работы. Используется как запасной признак,
# когда по шагам вид работы не читается (шагов нет или зоны не проставлены).
_KIND_EASY = {"easy", "long", "long_z2", "recovery", "l"}
_KIND_QUALITY = {"r", "t", "i", "quality", "tempo", "intervals",
                 "repetition", "race_pace", "progression"}


def _step_quality_markers(workout: Workout) -> tuple[bool, bool]:
    """Есть ли в тренировке признаки качественной работы.

    Возвращает пару `(видно по зонам, видно по намерениям)`: домен
    работает и с программой Дэниэлса (`daniels_zone`), и с тренировкой,
    разобранной из текста (`intent`).
    """
    by_zone = False
    by_intent = False
    for step in workout.steps:
        focus_value = step.focus_value or {}
        zone = str(focus_value.get("daniels_zone") or "").upper()
        if zone in _DANIELS_QUALITY_ZONES:
            by_zone = True
        intent = str(focus_value.get("intent") or "").lower()
        if intent in _INTENT_QUALITY:
            by_intent = True
    return by_zone, by_intent


def workout_kind_of(workout: Workout) -> str:
    """Вид работы тренировки: лёгкая, качественная или прочая.

    `easy` — лёгкая и длинная работа: у неё спрашивают общее ощущение.
    `quality` — интервальная, пороговая, повторная: у неё спрашивают
    динамику внутри работы.
    `other` — всё остальное (велосипед, плавание, ОФП): для такой работы
    форма оценки не показывается вовсе.

    Порядок признаков: сначала шаги (там видно, что за работа), потом
    `kind` (имя вида). Шаги — точнее: у интервальной тренировки, собранной
    из текста, `kind` = `composed`, а по шагам видно отрезки.
    """
    if workout.sport is not Sport.RUN:
        return KIND_OTHER

    by_zone, by_intent = _step_quality_markers(workout)
    if by_zone or by_intent:
        return KIND_QUALITY

    kind = (workout.kind or "").strip().lower()
    if kind in _KIND_QUALITY:
        return KIND_QUALITY
    if kind in _KIND_EASY:
        return KIND_EASY

    # Шагов нет или зоны не проставлены: судим по тому, что тренировка
    # вообще про бег. Неизвестное — «прочее», форма не показывается.
    return KIND_OTHER


# ------------------------------------------------------------------ оценка


@dataclass
class Feedback:
    """Субъективная оценка тренировки.

    Поля заполняются по одному — «значение, которого нет, — `None`, а не
    ноль»: непроставленное поле и заполненное «фон» — разные вещи.
    """

    # Тело (икры / поясница): 0 — фон, -1 — тянет, -2 — ломает.
    body_status: int | None = None
    # Общее ощущение на лёгкой и длинной работе: 1 · 0 · -1.
    easy_feel: int | None = None
    # 1-й отрезок: fresh · heavy.
    rep1_mental: str | None = None
    # 2-й отрезок: opened_up · wooden.
    rep2_physical: str | None = None
    # Финиш: yes · enough · definitely_no.
    want_one_more: str | None = None
    # Заметка: нестандартные факторы.
    comment: str = ""

    def is_empty(self) -> bool:
        """Оценки нет — только пустые значения."""
        return (
            self.body_status is None
            and self.easy_feel is None
            and self.rep1_mental is None
            and self.rep2_physical is None
            and self.want_one_more is None
            and not self.comment
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "body_status": self.body_status,
            "easy_feel": self.easy_feel,
            "rep1_mental": self.rep1_mental,
            "rep2_physical": self.rep2_physical,
            "want_one_more": self.want_one_more,
            "comment": self.comment,
        }


def normalise_feedback(raw: Any) -> Feedback:
    """Привести присланные значения к допустимым.

    Клиент может прислать что угодно: строку вместо числа, неизвестный
    код. Мусор отбрасывается, а не падает: непроставленное поле —
    `None`.
    """
    if not isinstance(raw, dict):
        return Feedback()

    body = raw.get("body_status")
    if body not in BODY_STATUS_VALUES:
        body = None

    feel = raw.get("easy_feel")
    if feel not in EASY_FEEL_VALUES:
        feel = None

    rep1 = raw.get("rep1_mental")
    if rep1 not in REP1_MENTAL_VALUES:
        rep1 = None

    rep2 = raw.get("rep2_physical")
    if rep2 not in REP2_PHYSICAL_VALUES:
        rep2 = None

    want = raw.get("want_one_more")
    if want not in WANT_ONE_MORE_VALUES:
        want = None

    comment = raw.get("comment")
    if not isinstance(comment, str):
        comment = ""
    comment = comment.strip()

    return Feedback(
        body_status=body,
        easy_feel=feel,
        rep1_mental=rep1,
        rep2_physical=rep2,
        want_one_more=want,
        comment=comment,
    )


def feedback_for_workout(
    workout: Workout,
    raw: Any,
) -> Feedback:
    """Оценка, применимая к этой тренировке.

    Поля, которые к виду работы не относятся, отбрасываются: у лёгкой
    работы нет «2-го отрезка», а у качественной — «общего ощущения».
    Иначе в форме появляются вопросы не о том, что человек делал.
    """
    feedback = normalise_feedback(raw)
    kind = workout_kind_of(workout)
    if kind == KIND_EASY:
        feedback.rep1_mental = None
        feedback.rep2_physical = None
        feedback.want_one_more = None
    elif kind == KIND_QUALITY:
        feedback.easy_feel = None
    return feedback
