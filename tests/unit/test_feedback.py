"""Субъективная оценка тренировки: домен.

ТЗ (Кирилл, 26.11.2026): оценка снимается в момент привязки факта к
плановой тренировке. Форма зависит от вида работы: лёгкая и длинная
спрашивают общее ощущение, интервальная и пороговая — динамику внутри
работы. Состояние тела (икры/поясница) спрашивается всегда.
"""
from __future__ import annotations

from app.domain.entities import Sport, Step, StepRole, TargetType, Workout
from app.domain.feedback import (
    Feedback,
    feedback_for_workout,
    normalise_feedback,
    workout_kind_of,
)


def _step(focus_value: dict, role: StepRole = StepRole.WORK) -> Step:
    return Step(
        id="s1", role=role, sport=Sport.RUN,
        target_type=TargetType.DISTANCE, target_value=1000.0,
        focus_value=focus_value,
    )


def _workout(kind: str = "easy", sport: Sport = Sport.RUN,
             steps: list[Step] | None = None) -> Workout:
    return Workout(
        id="w-1", request_id="r-1", sport=sport, kind=kind, focus="Z2",
        steps=steps or [],
    )


# ------------------------------------------------------------------ вид работы


def test_lighty_workout_kind_is_easy():
    """Лёгкий бег — блок «общее ощущение»."""
    assert workout_kind_of(_workout("easy")) == "easy"


def test_long_workout_kind_is_easy():
    """Длинный бег — тоже блок «общее ощущение»."""
    assert workout_kind_of(_workout("long")) == "easy"


def test_long_z2_kind_is_easy():
    """`long_Z2` из пайплайна — длинная работа, не качественная."""
    assert workout_kind_of(_workout("long_Z2")) == "easy"


def test_threshold_workout_kind_is_quality():
    """Пороговая работа — блок динамики."""
    assert workout_kind_of(_workout("t")) == "quality"


def test_repetition_workout_kind_is_quality():
    """Повторный темп — блок динамики."""
    assert workout_kind_of(_workout("r")) == "quality"


def test_daniels_zone_in_steps_makes_quality():
    """Зона работы в шагах важнее `kind`.

    Интервальная тренировка, собранная из текста, приходит с
    `kind = composed` — по нему её не отличить от лёгкой. Но в шагах
    видно зону работы: `I` — интервалы.
    """
    workout = _workout("composed", steps=[
        _step({"daniels_zone": "E"}),
        _step({"daniels_zone": "I"}),
    ])
    assert workout_kind_of(workout) == "quality"


def test_intent_in_steps_makes_quality():
    """Тренировка из разбора текста: намерение `interval` — качественная."""
    workout = _workout("composed", steps=[
        _step({"intent": "easy"}),
        _step({"intent": "interval"}),
    ])
    assert workout_kind_of(workout) == "quality"


def test_non_run_sport_has_no_feedback_form():
    """Велосипед, плавание, ОФП — форма оценки не показывается."""
    assert workout_kind_of(_workout("bike", sport=Sport.BIKE)) == "other"
    assert workout_kind_of(_workout("swim", sport=Sport.SWIM)) == "other"
    assert workout_kind_of(_workout("ofp", sport=Sport.OFP)) == "other"


def test_unknown_kind_without_markers_is_other():
    """Неизвестная работа без шагов — форма не показывается.

    Лучше не спросить, чем спросить не о том: у велосипеда «тело» и
    «2-й отрезок» — вопросы не о том, что человек делал.
    """
    assert workout_kind_of(_workout("что-то новое")) == "other"


# ------------------------------------------------------------------ значения


def test_normalise_drops_unknown_values():
    """Мусор отбрасывается, а не падает.

    Клиент может прислать что угодно: строку вместо числа, несуществующий
    код. Непроставленное поле — `None`, а не значение по умолчанию.
    """
    feedback = normalise_feedback({
        "body_status": "5",
        "easy_feel": 7,
        "rep1_mental": "нету",
        "rep2_physical": None,
        "want_one_more": "yes",
        "comment": 42,
    })
    assert feedback.body_status is None
    assert feedback.easy_feel is None
    assert feedback.rep1_mental is None
    assert feedback.rep2_physical is None
    assert feedback.want_one_more == "yes"
    assert feedback.comment == ""


def test_normalise_keeps_valid_values():
    feedback = normalise_feedback({
        "body_status": -1,
        "easy_feel": 1,
        "rep1_mental": "fresh",
        "rep2_physical": "wooden",
        "want_one_more": "definitely_no",
        "comment": "ветер",
    })
    assert feedback.body_status == -1
    assert feedback.easy_feel == 1
    assert feedback.rep1_mental == "fresh"
    assert feedback.rep2_physical == "wooden"
    assert feedback.want_one_more == "definitely_no"
    assert feedback.comment == "ветер"


def test_normalise_of_garbage_is_empty():
    """Не словарь — пустая оценка, а не исключение."""
    assert normalise_feedback(None).is_empty()
    assert normalise_feedback("мусор").is_empty()
    assert normalise_feedback([1, 2]).is_empty()


def test_body_status_zero_is_a_value_not_absence():
    """«Фон» — заполненное значение, а не «не заполнено».

    Иначе «фон» и «не отметил» были бы неразличимы, и в бейджах
    «фон» выглядел бы как отсутствие оценки.
    """
    feedback = normalise_feedback({"body_status": 0})
    assert feedback.body_status == 0
    assert not feedback.is_empty()
    assert normalise_feedback({}).body_status is None


# ------------------------------------------------------------------ по виду работы


def test_easy_workout_drops_quality_fields():
    """У лёгкой работы нет полей динамики — их значения отбрасываются."""
    feedback = feedback_for_workout(_workout("easy"), {
        "body_status": 0,
        "easy_feel": 1,
        "rep1_mental": "fresh",
        "rep2_physical": "opened_up",
        "want_one_more": "yes",
    })
    assert feedback.easy_feel == 1
    assert feedback.rep1_mental is None
    assert feedback.rep2_physical is None
    assert feedback.want_one_more is None
    assert feedback.body_status == 0


def test_quality_workout_drops_easy_feel():
    """У качественной работы нет «общего ощущения»."""
    feedback = feedback_for_workout(_workout("t"), {
        "body_status": -2,
        "easy_feel": 1,
        "rep1_mental": "heavy",
        "rep2_physical": "wooden",
        "want_one_more": "enough",
    })
    assert feedback.easy_feel is None
    assert feedback.rep1_mental == "heavy"
    assert feedback.rep2_physical == "wooden"
    assert feedback.want_one_more == "enough"
    assert feedback.body_status == -2


def test_feedback_switches_when_kind_changes():
    """Смена вида работы переключает форму.

    Тренировка переехала из «лёгкой» в «пороговую» — сохранённое
    «общее ощущение» больше не относится к ней и не должно всплыть.
    """
    workout = _workout("easy")
    saved = feedback_for_workout(workout, {"easy_feel": 1, "body_status": 0})
    assert saved.easy_feel == 1

    workout.kind = "t"
    switched = feedback_for_workout(workout, saved.as_dict())
    assert switched.easy_feel is None
    assert switched.body_status == 0


def test_feedback_is_empty_helper():
    """Пустая оценка — пустая; заполненное поле — не пусто.

    «Фон» (0) — заполненное значение, поэтому пустой оценкой оно не
    является.
    """
    assert Feedback().is_empty()
    assert not Feedback(body_status=0).is_empty()
    assert not Feedback(comment="ветер").is_empty()


def test_i53_feedback_lives_on_workout_not_on_fact():
    """I53: оценка живёт на тренировке, а не на факте.

    Факт перезаписывается выкачкой (`upsert` пишет сессию целиком),
    и всё, чего в новой выкачке нет, пропадает. Оценку человек ставит
    один раз и потом правит — значит она должна переживать выкачку.
    """
    from app.domain.entities import ActualSession, Workout

    # У факта поля оценки нет вовсе.
    assert "feedback" not in ActualSession.__dataclass_fields__

    # У тренировки — есть, и по умолчанию пустое.
    assert "feedback" in Workout.__dataclass_fields__
    assert Workout(id="w", request_id="r", sport=Sport.RUN, kind="easy",
                   focus="Z2").feedback == {}
