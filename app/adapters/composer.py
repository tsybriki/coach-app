"""Разбор текста пожеланий в тренировку — через модель.

Модель возвращает **намерения**, а не готовые шаги: «разминка → работа →
заминка», «фартлек», «8 км». Зоны, темпы и длительности считает домен —
по профилю атлета и таблице Дэниэлса. Если бы модель придумывала числа,
ошибки шли бы оттуда, где их быть не должно, и их нельзя было бы
отличить от ошибок домена.

**Детерминированного парсинга нет.** Текст живой: «12 км, 3 км разминка,
дальше фартлек» и «сделай часовую с фартлеком внутри» — это одно и то же
намерение, и разбирать это должна модель, а не набор правил.

Формат ответа — JSON. Модель может ошибиться в формате: тогда разбор
считается неудачным, и вызывающий покажет это пользователю понятным
сообщением, а не упадёт.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.composition import WorkoutIntent
from app.domain.enums import Sport, StepRole, TargetType
from app.ports.storage import ComposeContext, ExternalSourceError

# Модель и адрес — те же, что у Hermes: minimax через Anthropic-совместимый
# API. Ключ — в окружении сервиса.
DEFAULT_BASE_URL = "https://api.minimax.io/anthropic"
DEFAULT_MODEL = "MiniMax-M3"

# Словарь намерений, который модель обязана использовать. Не список для
# выбора: модель возвращает намерение, а домен знает, что оно значит.
INTENT_HELP = {
    "easy": "лёгкий бег, разминка, заминка, восстановительный",
    "long": "длинный бег",
    "marathon": "марафонский темп",
    "steady": "ровный, без ускорений",
    "threshold": "порог, фартлек, темповая работа",
    "interval": "интервалы, работа на VO2max",
    "repetition": "повторный темп, ускорения, отрезки",
}


@dataclass
class ModelPlan:
    """Намерения, разобранные моделью."""

    name: str
    sport: Sport
    intents: list[WorkoutIntent] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sport": self.sport.value,
            "intents": [i.as_dict() for i in self.intents],
            "assumptions": list(self.assumptions),
        }


SYSTEM_PROMPT = """\
Ты — помощник бегуна. По тексту пожеланий собираешь структуру тренировки.

ТВОЯ ЗАДАЧА: вернуть JSON со списком шагов тренировки. Не текст, а JSON.

ФОРМАТ ОТВЕТА (строго):
{
  "name": "Название тренировки",
  "sport": "run",
  "steps": [
    {
      "role": "warmup",
      "target_type": "distance",
      "target_value": 3000,
      "intent": "easy",
      "label": "Лёгкий бег",
      "reps": 1,
      "rest_type": "distance",
      "rest_value": 0,
      "notes": ""
    }
  ],
  "assumptions": ["что ты додумал"]
}

ПОЛЯ ШАГА:
- role: warmup | work | rest | cooldown | transition
- target_type: distance (метры!) | time (минуты)
- target_value: число. Для distance — МЕТРЫ (8000 = 8 км). Для time — минуты.
- intent: одно из easy, long, marathon, steady, threshold, interval, repetition.
  Это единственное, что определяет интенсивность. Пульс, темп и минуты
  считаются отдельно — тебе их указывать НЕ нужно.
- label: короткое название шага по-русски. Для рабочих шагов это будет
  название тренировки.
- reps: сколько повторов. Для «8×400» — reps: 8, target_value: 400.
- rest_type/rest_value: отдых между повторами (distance — метры, time — минуты).
  Если отдыха нет — 0.
- notes: пояснение по-русски, если шаг требует пояснения.

ЧТО ТЫ ДЕЛАЕШЬ:
- Читаешь текст и выделяешь шаги в порядке выполнения.
- Считаешь объём: «12 км» → 12000 метров, «8 по 400» → reps 8, 400 метров.
- **Шаги — это ЧАСТИ тренировки, и их сумма равна всей тренировке.**
  Если человек говорит «часовая, из них 20 минут в пороге» — это два
  шага: лёгкая часть (40 минут) И пороговая часть (20 минут). НЕ три
  шага «часовая + 20 минут порога»: получится 80 минут вместо часа.
  Если общий объём и части названы вместе — разбей общий на части.
- Разминку и заминку добавляешь, если их нет в тексте: разминка — 2-3 км
  лёгкого, заминка — 1 км лёгкого. Это твоё решение — запиши его в
  assumptions.
- Если объём не указан, а есть только характер работы («пороговая
  работа») — предложи разумный объём сам (например, 20 минут) и запиши
  это в assumptions.
- Если в тексте не сказано, какой объём у разминки или заминки — ставишь
  разумный и записываешь в assumptions.

ЧЕГО ТЫ НЕ ДЕЛАЕШЬ:
- Не указываешь пульс, темп или минуты в focus. У тебя нет таких полей.
- Не выдумываешь зоны атлета: «порог» — это intent threshold, остальное
  система посчитает сама.
- Не добавляешь общий объём отдельным шагом, если он уже разложен на
  части.
- Не отказываешься. Если текст непонятен — собери то, что понятно, и
  запиши в assumptions, что именно додумал.

ПРИМЕР. Текст: «12 км, 3 км разминка, дальше фартлек»
{
  "name": "Фартлек",
  "sport": "run",
  "steps": [
    {"role": "warmup", "target_type": "distance", "target_value": 3000,
     "intent": "easy", "label": "Разминка", "reps": 1, "rest_type": "distance",
     "rest_value": 0, "notes": ""},
    {"role": "work", "target_type": "distance", "target_value": 8000,
     "intent": "threshold", "label": "Фартлек", "reps": 1, "rest_type": "distance",
     "rest_value": 0, "notes": ""},
    {"role": "cooldown", "target_type": "distance", "target_value": 1000,
     "intent": "easy", "label": "Заминка", "reps": 1, "rest_type": "distance",
     "rest_value": 0, "notes": ""}
  ],
  "assumptions": ["объём фартлека — 8 км: в тексте не указан"]
}
"""


class MiniMaxComposer:
    """Разбор текста через модель minimax.

    Ключ берётся из окружения (`MINIMAX_API_KEY`). Если ключа нет или
    модель недоступна — `ExternalSourceError`: приложение не ломается,
    кнопка «Предложить тренировку» просто недоступна.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.base_url = base_url or os.environ.get(
            "MINIMAX_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        """Есть ли ключ. Без ключа кнопку предложения лучше не показывать."""
        return bool(self.api_key)

    def compose(self, text: str, context: ComposeContext) -> ModelPlan:
        """Текст пожеланий → намерения по шагам."""
        if not self.api_key:
            raise ExternalSourceError("minimax", "нет ключа модели")

        payload = {
            "model": self.model,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": self._user_message(text, context)}],
        }
        raw = self._post(payload)
        return self._parse(raw)

    def _user_message(self, text: str, context: ComposeContext) -> str:
        """Текст пожеланий плюс контекст спортсмена."""
        zones = context.as_dict()
        lines = [
            f"Контекст спортсмена: {json.dumps(zones, ensure_ascii=False)}",
            "",
            "Пожелания:",
            text.strip(),
        ]
        return "\n".join(lines)

    def _post(self, payload: dict[str, Any]) -> str:
        """POST к Anthropic-совместимому API minimax."""
        import urllib.error
        import urllib.request

        url = f"{self.base_url.rstrip('/')}/v1/messages"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", "replace")
            raise ExternalSourceError(
                "minimax", f"модель ответила ошибкой {error.code}: {detail}") from error
        except Exception as error:  # noqa: BLE001 — внешний источник
            raise ExternalSourceError(
                "minimax", f"модель недоступна: {error}") from error

        content = body.get("content") or []
        text = "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict)
        ).strip()
        if not text:
            raise ExternalSourceError("minimax", "модель вернула пустой ответ")
        return text

    def _parse(self, raw: str) -> ModelPlan:
        """Ответ модели → намерения.

        Модель может обернуть JSON в блок кода или добавить текст вокруг —
        берём самый внутренний объект.
        """
        data = self._extract_json(raw)
        if not isinstance(data, dict):
            raise ExternalSourceError("minimax", "ответ модели не разобран")

        steps_raw = data.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ExternalSourceError("minimax", "в ответе модели нет шагов")

        intents: list[WorkoutIntent] = []
        for item in steps_raw:
            if not isinstance(item, dict):
                continue
            intent = self._intent(item)
            if intent is not None:
                intents.append(intent)
        if not intents:
            raise ExternalSourceError("minimax", "шаги модели не разобрались")

        assumptions = [
            str(a) for a in (data.get("assumptions") or []) if str(a).strip()
        ]
        return ModelPlan(
            name=str(data.get("name") or "").strip(),
            sport=_sport(data.get("sport")),
            intents=intents,
            assumptions=assumptions,
        )

    def _intent(self, item: dict[str, Any]) -> WorkoutIntent | None:
        """Один шаг ответа модели → намерение."""
        role = _role(item.get("role"))
        if role is None:
            return None
        target_type = _target_type(item.get("target_type")) or TargetType.DISTANCE
        try:
            target_value = float(item.get("target_value") or 0.0)
        except (TypeError, ValueError):
            return None
        if target_value <= 0:
            return None

        intent = str(item.get("intent") or "").strip().lower()
        if intent not in INTENT_HELP:
            intent = "easy"

        reps = _positive_int(item.get("reps"), 1)
        rest_type = _target_type(item.get("rest_type")) or TargetType.DISTANCE
        try:
            rest_value = float(item.get("rest_value") or 0.0)
        except (TypeError, ValueError):
            rest_value = 0.0

        return WorkoutIntent(
            role=role,
            sport=_sport(item.get("sport")),
            target_type=target_type,
            target_value=target_value,
            intent=intent,
            label=str(item.get("label") or "").strip(),
            reps=reps,
            notes=str(item.get("notes") or "").strip(),
            rest_type=rest_type,
            rest_value=max(0.0, rest_value),
        )

    def _extract_json(self, raw: str) -> Any:
        """JSON из ответа: сначала целиком, потом из блока кода."""
        candidate = raw.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Объект внутри произвольного текста: с первой «{» до последней «}».
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None


def _role(value: Any) -> StepRole | None:
    try:
        return StepRole(str(value or "").strip().lower())
    except ValueError:
        return None


def _target_type(value: Any) -> TargetType | None:
    try:
        return TargetType(str(value or "").strip().lower())
    except ValueError:
        return None


def _sport(value: Any) -> Sport:
    text = str(value or "run").strip().lower()
    aliases = {
        "running": Sport.RUN,
        "run": Sport.RUN,
        "cycling": Sport.BIKE,
        "bike": Sport.BIKE,
        "swimming": Sport.SWIM,
        "swim": Sport.SWIM,
    }
    if text in aliases:
        return aliases[text]
    try:
        return Sport(text)
    except ValueError:
        return Sport.RUN


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, number)


__all__ = ["INTENT_HELP", "MiniMaxComposer", "ModelPlan", "SYSTEM_PROMPT"]
