"""Разбор ответа модели в намерения.

Модель возвращает JSON. Она может:
  - завернуть его в блок кода;
  - добавить текст вокруг;
  - назвать неизвестное намерение;
  - вернуть ерунду.

Всё это не должно ронять приложение: понятная ошибка вместо
падения. И важное: модель не придумывает числа — она возвращает объём,
который назвал человек, и намерение, а зоны и темпы считает домен.
"""
from __future__ import annotations

import pytest

from app.adapters.composer import MiniMaxComposer
from app.domain.enums import Sport, StepRole, TargetType
from app.ports.storage import ComposeContext, ExternalSourceError

CONTEXT = ComposeContext(vdot=50.0, hr_max=182)


def composer() -> MiniMaxComposer:
    return MiniMaxComposer(api_key="test-key")


def test_parses_plain_json():
    raw = """{
      "name": "Фартлек",
      "sport": "run",
      "steps": [
        {"role": "warmup", "target_type": "distance", "target_value": 3000,
         "intent": "easy", "label": "Разминка", "reps": 1},
        {"role": "work", "target_type": "distance", "target_value": 8000,
         "intent": "threshold", "label": "Фартлек", "reps": 1}
      ],
      "assumptions": ["объём фартлека не указан — 8 км"]
    }"""

    plan = composer()._parse(raw)

    assert plan.name == "Фартлек"
    assert plan.sport is Sport.RUN
    assert len(plan.intents) == 2
    assert plan.intents[0].role is StepRole.WARMUP
    assert plan.intents[0].target_type is TargetType.DISTANCE
    assert plan.intents[0].target_value == 3000.0
    assert plan.intents[1].intent == "threshold"
    assert plan.assumptions == ["объём фартлека не указан — 8 км"]


def test_parses_json_in_code_block():
    """Модель часто оборачивает JSON в блок кода."""
    raw = """Вот тренировка:
```json
{"name": "Лёгкая", "sport": "run", "steps": [
  {"role": "work", "target_type": "time", "target_value": 50, "intent": "easy"}
]}
```
"""

    plan = composer()._parse(raw)

    assert plan.name == "Лёгкая"
    assert len(plan.intents) == 1


def test_parses_json_with_surrounding_text():
    """Текст вокруг JSON — тоже обычное дело."""
    raw = """Конечно! Вот разбор:
{"name": "Темповая", "sport": "run", "steps": [
  {"role": "work", "target_type": "time", "target_value": 40, "intent": "threshold"}
]}
Надеюсь, помогло."""

    plan = composer()._parse(raw)

    assert plan.name == "Темповая"
    assert plan.intents[0].intent == "threshold"


def test_unknown_intent_falls_back_to_easy():
    """Неизвестное намерение не ломает разбор: работа считается лёгкой."""
    raw = """{"name": "Что-то", "sport": "run", "steps": [
      {"role": "work", "target_type": "distance", "target_value": 5000,
       "intent": "какая-то ерунда"}
    ]}"""

    plan = composer()._parse(raw)

    assert plan.intents[0].intent == "easy"


def test_unknown_role_skips_the_step():
    """Незнакомая роль — шаг пропускается, а не ломает разбор."""
    raw = """{"name": "Что-то", "sport": "run", "steps": [
      {"role": "ерунда", "target_type": "distance", "target_value": 5000},
      {"role": "work", "target_type": "distance", "target_value": 3000,
       "intent": "easy"}
    ]}"""

    plan = composer()._parse(raw)

    assert len(plan.intents) == 1
    assert plan.intents[0].target_value == 3000.0


def test_zero_target_skips_the_step():
    """Шаг без объёма бессмысленен — пропускаем."""
    raw = """{"name": "Что-то", "sport": "run", "steps": [
      {"role": "work", "target_type": "distance", "target_value": 0,
       "intent": "easy"}
    ]}"""

    with pytest.raises(ExternalSourceError):
        composer()._parse(raw)


def test_reps_and_rest_are_kept():
    """«8 по 400 с отдыхом 90 секунд» — повторы и отдых."""
    raw = """{"name": "8 по 400", "sport": "run", "steps": [
      {"role": "work", "target_type": "distance", "target_value": 400,
       "intent": "interval", "reps": 8, "rest_type": "time",
       "rest_value": 90}
    ]}"""

    plan = composer()._parse(raw)

    assert plan.intents[0].reps == 8
    assert plan.intents[0].rest_type is TargetType.TIME
    assert plan.intents[0].rest_value == 90.0


def test_garbage_raises_external_source_error():
    """Мусор вместо JSON — понятная ошибка, а не падение."""
    with pytest.raises(ExternalSourceError) as error:
        composer()._parse("не знаю, что такое тренировка")

    assert "minimax" in str(error.value)


def test_no_steps_raises_external_source_error():
    """Нет шагов — разбор не удался."""
    with pytest.raises(ExternalSourceError):
        composer()._parse('{"name": "Пусто", "steps": []}')


def test_compose_without_key_raises():
    """Без ключа модели — понятная ошибка, приложение не ломается."""
    without_key = MiniMaxComposer(api_key="")

    with pytest.raises(ExternalSourceError):
        without_key.compose("любой текст", CONTEXT)


def test_available_reflects_key_presence():
    """Без ключа кнопку предложения лучше не показывать."""
    assert MiniMaxComposer(api_key="key").available
    assert not MiniMaxComposer(api_key="").available
