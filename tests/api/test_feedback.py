"""Субъективная оценка тренировки через API.

Сценарий Кирилла (26.11.2026): оценка снимается в момент привязки факта
к плановой тренировке, а потом её можно открыть и отредактировать.

Здесь проверяется целиком, через настоящий HTTP-маршрут:
- оценка сохраняется на тренировке и переживает перезагрузку;
- привязка факта может нести оценку сразу;
- форма по виду работы: лёгкой — «общее ощущение», качественной —
  динамика; лишние поля отбрасываются;
- пустая оценка — тоже оценка (человек сознательно пропустил форму);
- оценка переживает пересборку недели.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.storage.files import FileStorage
from app.domain.entities import (
    ActualSession,
    Assignment,
    Goal,
    MacroWeek,
    Phase,
    Plan,
    Request,
    Season,
    Slot,
    Step,
    Week,
    Workout,
)
from app.domain.enums import (
    FactSource,
    PlanStatus,
    Sport,
    StepRole,
    TargetType,
    WeekStatus,
)


def _step(daniels_zone: str = "E") -> Step:
    return Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0,
                focus_value={"daniels_zone": daniels_zone}, duration_min=60.0)


def _seed(root: Path) -> int:
    """Неделя 7: лёгкая, пороговая и одна не-беговая тренировка."""
    storage = FileStorage(root)
    goal = Goal(id="g1", discipline="run_10k", race_date=date(2027, 4, 18),
                metric_type="time_sec", metric_target=2400.0,
                target_friendly="40:00", venue="S25 Berlin 10K")
    plan = Plan(
        id="g1", status=PlanStatus.ACTIVE, goal=goal,
        period_start=date(2026, 10, 11), period_end=date(2027, 9, 12),
        phases=[Phase(id="run_base", objective="Поднимаем базовый объём",
                      load_range=(4.96, 9.74), volume_range=(27.0, 50.0))],
        macro_weeks=[
            MacroWeek(season_week=7, phase_id="run_base",
                      focus="progression", goal_text="Развиваем базу",
                      run_km=57.0, total_h=7.71, sessions_target=3,
                      minutes_by_sport={"run": 462.0},
                      long_min=81, quality_min=120, easy_min=261,
                      easy_runs=3, sessions_by_sport={}),
        ],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49,
               plans=[plan],
               slots=[Slot(id="win-ВС-1", day=0, start="11:00", end="13:00",
                           capacity_min=120),
                      Slot(id="win-ЧТ-1", day=4, start="18:30", end="19:45",
                           capacity_min=75)]),
        expected_version=0,
    )

    requests = [
        Request(id="r-easy", sport=Sport.RUN, kind="easy", focus="Лёгкий бег",
                duration_min=28),
        Request(id="r-t", sport=Sport.RUN, kind="t",
                focus="Работа в пороговом темпе", duration_min=63),
        Request(id="r-bike", sport=Sport.BIKE, kind="bike", focus="Велосипед",
                duration_min=60),
    ]
    assignments = [
        Assignment(request_id="r-easy", slot_id="win-ВС-1", start="11:00",
                   duration_min=28),
        Assignment(request_id="r-t", slot_id="win-ЧТ-1", start="18:30",
                   duration_min=63),
        Assignment(request_id="r-bike", slot_id="win-ЧТ-1", start="18:30",
                   duration_min=60),
    ]

    workouts = [
        Workout(id="w-easy", request_id="r-easy", sport=Sport.RUN,
                kind="easy", focus="Лёгкий бег",
                objective={"name": "Лёгкий бег", "day": 0,
                           "slot_id": "win-ВС-1"},
                steps=[_step("E")], duration_min=28.0, time="11:00"),
        Workout(id="w-t", request_id="r-t", sport=Sport.RUN,
                kind="t", focus="Работа в пороговом темпе",
                objective={"name": "Работа в пороговом темпе", "day": 4,
                           "slot_id": "win-ЧТ-1"},
                steps=[_step("T")], duration_min=63.0, time="18:30"),
        Workout(id="w-bike", request_id="r-bike", sport=Sport.BIKE,
                kind="bike", focus="Велосипед",
                objective={"name": "Велосипед", "day": 4,
                           "slot_id": "win-ЧТ-1"},
                steps=[Step(id="s2", role=StepRole.WORK, sport=Sport.BIKE,
                            target_type=TargetType.TIME, target_value=60.0,
                            duration_min=60.0)],
                duration_min=60.0, time="18:30"),
    ]

    week = Week(
        id="W7", plan_id="p1", season_week=7,
        start=date(2026, 11, 22), end=date(2026, 11, 28),
        status=WeekStatus.ACTIVE,
        requests=requests, assignments=assignments, workouts=workouts,
        load_target={"hours": 7.71, "sessions": 3, "distance_m": 57000.0},
    )
    version = storage.put_week(week, expected_version=1)
    storage.upsert(ActualSession(
        id="a1", date=date(2026, 11, 22), sport=Sport.RUN,
        source=FactSource.GARMIN, duration_min=27, distance_m=5000.0,
        external_id="ext-1",
    ))
    return version


def _set_feedback(client: TestClient, version: int, workout_id: str,
                  feedback: dict, cid: str = "fb-1"):
    return client.post("/api/v1/commands", json={
        "id": cid, "type": "set_feedback",
        "args": {"season_week": 7, "workout_id": workout_id,
                 "feedback": feedback},
        "reason": "оценка тренировки",
        "expected_version": version,
    })


def _week(client: TestClient) -> dict:
    response = client.get("/api/v1/week/7")
    assert response.status_code == 200
    return response.json()["data"]


def _workout(week: dict, workout_id: str) -> dict:
    for item in week["workouts"]:
        if item["id"] == workout_id:
            return item
    raise AssertionError(f"тренировки {workout_id} нет в ответе")


# ------------------------------------------------------------------ сохранение


def test_feedback_is_saved_on_workout(client: TestClient, data_root: Path):
    """Оценка сохраняется на тренировке и не теряется при перезагрузке."""
    version = _seed(data_root)
    response = _set_feedback(client, version, "w-easy",
                             {"body_status": -1, "easy_feel": 1,
                              "comment": "ветер в спину"})
    assert response.status_code == 200

    week = _week(client)
    saved = _workout(week, "w-easy")["feedback"]
    assert saved["body_status"] == -1
    assert saved["easy_feel"] == 1
    assert saved["comment"] == "ветер в спину"


def test_feedback_survives_reload_from_disk(client: TestClient,
                                             data_root: Path):
    """Оценка лежит в хранилище, а не в памяти сервера."""
    version = _seed(data_root)
    _set_feedback(client, version, "w-easy", {"body_status": -2})

    storage = FileStorage(data_root)
    week = storage.week(7)
    assert week is not None
    saved = next(w for w in week.workouts if w.id == "w-easy")
    assert saved.feedback["body_status"] == -2


# ------------------------------------------------------------------ по виду работы


def test_easy_workout_keeps_easy_feel_and_drops_dynamic_fields(
    client: TestClient, data_root: Path):
    """У лёгкой работы спрашивается ощущение, а не динамика отрезков."""
    version = _seed(data_root)
    _set_feedback(client, version, "w-easy", {
        "body_status": 0, "easy_feel": 1,
        "rep1_mental": "fresh", "rep2_physical": "opened_up",
        "want_one_more": "yes",
    })

    saved = _workout(_week(client), "w-easy")["feedback"]
    assert saved["easy_feel"] == 1
    assert saved["body_status"] == 0
    assert saved["rep1_mental"] is None
    assert saved["rep2_physical"] is None
    assert saved["want_one_more"] is None


def test_quality_workout_keeps_dynamic_fields_and_drops_easy_feel(
    client: TestClient, data_root: Path):
    """У качественной работы — динамика внутри работы."""
    version = _seed(data_root)
    _set_feedback(client, version, "w-t", {
        "body_status": -1, "easy_feel": 1,
        "rep1_mental": "heavy", "rep2_physical": "wooden",
        "want_one_more": "enough",
    })

    saved = _workout(_week(client), "w-t")["feedback"]
    assert saved["rep1_mental"] == "heavy"
    assert saved["rep2_physical"] == "wooden"
    assert saved["want_one_more"] == "enough"
    assert saved["body_status"] == -1
    assert saved["easy_feel"] is None


def test_api_tells_client_which_form_to_show(client: TestClient,
                                             data_root: Path):
    """Вид работы отдаётся сервером: клиент не разбирает `kind` сам.

    По `kind` интервальную тренировку, собранную из текста, не отличить
    от лёгкой (`composed`), а форма должна переключаться правильно.
    """
    _seed(data_root)
    week = _week(client)
    assert _workout(week, "w-easy")["feedback_kind"] == "easy"
    assert _workout(week, "w-t")["feedback_kind"] == "quality"
    assert _workout(week, "w-bike")["feedback_kind"] == "other"


# ------------------------------------------------------------------ пустая оценка


def test_empty_feedback_is_saved_as_empty(client: TestClient, data_root: Path):
    """Пропуск формы — осознанное действие, и оно сохраняется.

    Иначе «пропустил» и «ещё не оценивал» выглядели бы одинаково, и
    нельзя было бы отличить одно от другого.
    """
    version = _seed(data_root)
    response = _set_feedback(client, version, "w-easy", {})
    assert response.status_code == 200

    saved = _workout(_week(client), "w-easy")["feedback"]
    assert saved == {
        "body_status": None, "easy_feel": None, "rep1_mental": None,
        "rep2_physical": None, "want_one_more": None, "comment": "",
    }


def test_garbage_values_are_dropped(client: TestClient, data_root: Path):
    """Мусор отбрасывается, а не падает и не сохраняется."""
    version = _seed(data_root)
    response = _set_feedback(client, version, "w-easy", {
        "body_status": "пять", "easy_feel": 99, "rep1_mental": "нету",
    })
    assert response.status_code == 200

    saved = _workout(_week(client), "w-easy")["feedback"]
    assert saved["body_status"] is None
    assert saved["easy_feel"] is None
    assert saved["rep1_mental"] is None


# ------------------------------------------------------------------ ошибки


def test_feedback_for_unknown_workout_is_refused(client: TestClient,
                                                 data_root: Path):
    """Оценки несуществующей тренировки — понятный отказ, не 500."""
    version = _seed(data_root)
    response = _set_feedback(client, version, "w-нет-такой",
                             {"body_status": 0})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_command"
    assert "w-нет-такой" in payload["error"]["message"]


# ------------------------------------------------------------------ привязка


def test_link_actual_can_carry_feedback(client: TestClient, data_root: Path):
    """Оценка ставится вместе с привязкой факта.

    Сценарий ТЗ: оценка снимается в момент привязки, а не отдельным
    шагом после неё.
    """
    version = _seed(data_root)
    response = client.post("/api/v1/commands", json={
        "id": "link-1", "type": "link_actual",
        "args": {"season_week": 7, "actual_id": "a1", "workout_id": "w-easy",
                 "feedback": {"body_status": -1, "easy_feel": 0}},
        "reason": "привязать факт с оценкой",
        "expected_version": version,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "applied"

    saved = _workout(_week(client), "w-easy")["feedback"]
    assert saved["body_status"] == -1
    assert saved["easy_feel"] == 0


# ------------------------------------------------------------------ переживание


def test_feedback_survives_week_rebuild(client: TestClient, data_root: Path):
    """Оценка переезжает вместе с выполненной тренировкой.

    Пересборка недели возвращает выполненное на место (`_keep_done_workouts`).
    Без переноса оценки она молча пропадала бы при переплане, и человек
    зрядил бы работу второй раз.
    """
    version = _seed(data_root)
    client.post("/api/v1/commands", json={
        "id": "link-1", "type": "link_actual",
        "args": {"season_week": 7, "actual_id": "a1", "workout_id": "w-easy",
                 "feedback": {"body_status": -2, "easy_feel": 1}},
        "reason": "привязать факт с оценкой",
        "expected_version": version,
    })
    # Версия — в ответе команды: команда сдвинула состояние.
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "replan-1", "type": "replan_remainder",
        "args": {"season_week": 7}, "reason": "перепланировать остаток",
        "expected_version": version,
    })
    assert response.status_code == 200

    week = _week(client)
    saved = _workout(week, "w-easy")
    assert saved["feedback"]["body_status"] == -2
    assert saved["feedback"]["easy_feel"] == 1
