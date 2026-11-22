"""Перепланирование остатка недели через API: план не пересобирается.

Сценарий Кирилла (22.11.2026): неделя активна, две тренировки выполнены
(к ним привязан факт). Команда `replan_remainder` должна отвязать от
слотов только тренировки без факта и вернуть неделю в `proposed`.

Сейчас команда пересобирает неделю по правилам методики. Из-за этого:

- в неделю попадают новые тренировки с теми же id, что у выполненных
  (`r7-1…r7-6`, `r7-other-*`) — id задваиваются;
- число тренировок растёт (10 вместо 8), и на экране две одинаковые
  карточки;
- удаление дубликата по `request_id` сносит и выполненную тренировку.

Здесь проверяется команда целиком — через настоящий HTTP-маршрут, с
настоящей пересборкой плана и настоящими инвариантами.
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
    WorkoutStatus,
)


def _seed(root: Path) -> int:
    """Неделя 7: две тренировки выполнены, восемь — нет.

    Идентификаторы — настоящие, из боевой недели: беговые тренировки
    `r7-1…r7-6`, не беговые — `r7-other-1…r7-other-4`. Дубликаты
    воспроизводятся именно с такими id.
    """
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
                      run_km=57.0, total_h=7.71, sessions_target=8,
                      minutes_by_sport={"run": 462.0, "bike": 60.0,
                                        "swim": 45.0, "ofp": 60.0},
                      long_min=81, quality_min=120, easy_min=261,
                      easy_runs=3,
                      sessions_by_sport={"bike": [60], "swim": [45],
                                        "ofp": [30, 30]}),
        ],
    )
    storage.save(
        Season(id="S1", horizon_start=date(2026, 10, 11),
               horizon_end=date(2027, 9, 12), season_week_count=49,
               plans=[plan],
               slots=[Slot(id="win-ВС-1", day=0, start="11:00", end="13:00",
                           capacity_min=120),
                      Slot(id="win-ПН-1", day=1, start="18:45", end="20:15",
                           capacity_min=90),
                      Slot(id="win-ВТ-1", day=2, start="09:00", end="09:30",
                           capacity_min=30),
                      Slot(id="win-СР-1", day=3, start="17:00", end="19:00",
                           capacity_min=120),
                      Slot(id="win-ЧТ-1", day=4, start="18:30", end="19:45",
                           capacity_min=75),
                      Slot(id="win-ПТ-1", day=5, start="18:00", end="19:00",
                           capacity_min=60),
                      Slot(id="win-СБ-1", day=6, start="10:00", end="11:00",
                           capacity_min=60)]),
        expected_version=0,
    )

    step = Step(id="s1", role=StepRole.WORK, sport=Sport.RUN,
                target_type=TargetType.TIME, target_value=60.0,
                duration_min=60.0)

    # Запросы: два выполненных (r7-4, r7-other-3) и восемь остальных.
    done_run = Request(id="r7-4", sport=Sport.RUN, kind="long", focus="long",
                        duration_min=81)
    done_ofp = Request(id="r7-other-3", sport=Sport.OFP, kind="ofp",
                        focus="ОФП", duration_min=30)
    rest_specs = [
        ("r7-1", Sport.RUN, "r", "Работа в повторном темпе", 52),
        ("r7-2", Sport.RUN, "t", "Работа в пороговом темпе", 63),
        ("r7-3", Sport.RUN, "i", "Работа в интервальном темпе", 50),
        ("r7-5", Sport.RUN, "easy", "Лёгкий бег", 28),
        ("r7-6", Sport.RUN, "easy", "Лёгкий бег", 28),
        ("r7-other-1", Sport.BIKE, "bike", "Велосипед", 60),
        ("r7-other-2", Sport.SWIM, "swim", "Плавание", 45),
        ("r7-other-4", Sport.OFP, "ofp", "ОФП", 30),
    ]
    rest = [Request(id=rid, sport=sport, kind=kind, focus=focus,
                    duration_min=minutes)
            for rid, sport, kind, focus, minutes in rest_specs]

    slot_by_request = {
        "r7-4": "win-ВС-1", "r7-other-3": "win-ВС-1",
        "r7-1": "win-ПН-1", "r7-2": "win-ЧТ-1", "r7-3": "win-СР-1",
        "r7-5": "win-ВТ-1", "r7-6": "win-СБ-1",
        "r7-other-1": "win-ЧТ-1", "r7-other-2": "win-ПТ-1",
        "r7-other-4": "win-СР-1",
    }
    day_by_slot = {
        "win-ВС-1": 0, "win-ПН-1": 1, "win-ВТ-1": 2, "win-СР-1": 3,
        "win-ЧТ-1": 4, "win-ПТ-1": 5, "win-СБ-1": 6,
    }
    start_by_slot = {
        "win-ВС-1": "11:00", "win-ПН-1": "18:45", "win-ВТ-1": "09:00",
        "win-СР-1": "17:00", "win-ЧТ-1": "18:30", "win-ПТ-1": "18:00",
        "win-СБ-1": "10:00",
    }

    assignments = [
        Assignment(request_id=rid, slot_id=slot, start=start_by_slot[slot],
                   duration_min=60)
        for rid, slot in slot_by_request.items()
    ]

    def workout(wid: str, rid: str, sport: Sport, kind: str, focus: str,
                minutes: int, actual_id: str | None = None) -> Workout:
        slot = slot_by_request[rid]
        return Workout(
            id=wid, request_id=rid, sport=sport,
            kind=kind, focus=focus,
            objective={"name": focus, "day": day_by_slot[slot],
                       "slot_id": slot},
            steps=[step], duration_min=float(minutes),
            time=start_by_slot[slot],
            actual_id=actual_id,
            status=WorkoutStatus.DONE if actual_id else WorkoutStatus.PLANNED,
        )

    workouts = [
        workout("w-r7-4", "r7-4", Sport.RUN, "long", "Длинный бег", 81, "a1"),
        workout("w-ofp-1", "r7-other-3", Sport.OFP, "ofp", "ОФП", 30, "a2"),
        workout("w-r7-1", "r7-1", Sport.RUN, "r", "Работа в повторном темпе", 52),
        workout("w-r7-2", "r7-2", Sport.RUN, "t", "Работа в пороговом темпе", 63),
        workout("w-r7-3", "r7-3", Sport.RUN, "i", "Работа в интервальном темпе", 50),
        workout("w-r7-5", "r7-5", Sport.RUN, "easy", "Лёгкий бег", 28),
        workout("w-r7-6", "r7-6", Sport.RUN, "easy", "Лёгкий бег", 28),
        workout("w-bike-1", "r7-other-1", Sport.BIKE, "bike", "Велосипед", 60),
        workout("w-swim-1", "r7-other-2", Sport.SWIM, "swim", "Плавание", 45),
        workout("w-ofp-2", "r7-other-4", Sport.OFP, "ofp", "ОФП", 30),
    ]

    week = Week(
        id="W7", plan_id="p1", season_week=7,
        start=date(2026, 11, 22), end=date(2026, 11, 28),
        status=WeekStatus.ACTIVE,
        requests=[done_run, done_ofp] + rest,
        assignments=assignments,
        workouts=workouts,
        load_target={"hours": 7.71, "sessions": 10, "distance_m": 57618.0},
    )
    version = storage.put_week(week, expected_version=1)

    storage.upsert(ActualSession(
        id="a1", date=date(2026, 11, 22), sport=Sport.RUN,
        source=FactSource.GARMIN, duration_min=80, distance_m=14534.0,
        external_id="ext-1", linked_workout_id="w-r7-4",
    ))
    storage.upsert(ActualSession(
        id="a2", date=date(2026, 11, 22), sport=Sport.OFP,
        source=FactSource.GARMIN, duration_min=15, distance_m=0.0,
        external_id="ext-2", linked_workout_id="w-ofp-1",
    ))
    return version


def _replan(client: TestClient, version: int, cid: str = "replan-1"):
    return client.post("/api/v1/commands", json={
        "id": cid, "type": "replan_remainder",
        "args": {"season_week": 7}, "reason": "перепланировать остаток",
        "expected_version": version,
    })


def test_replan_does_not_change_number_of_workouts(
    client: TestClient, data_root: Path
):
    """После переплана тренировок столько же, сколько было.

    Репорт: «общее количество тренировок в неделю стало 10, а не 8».
    Пересборка плана добавляла тренировки к уже выполненным.
    """
    version = _seed(data_root)
    before = client.get("/api/v1/week/7").json()["data"]
    count_before = len(before["workouts"])

    response = _replan(client, version)
    assert response.status_code == 200, response.text

    after = client.get("/api/v1/week/7").json()["data"]
    assert len(after["workouts"]) == count_before, (
        f"переплан изменил число тренировок: {count_before} → "
        f"{len(after['workouts'])}"
    )


def test_replan_leaves_no_duplicate_workout_ids(
    client: TestClient, data_root: Path
):
    """В неделе нет двух тренировок с одним id.

    Именно дубликат был виден на экране: две одинаковые карточки.
    """
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    ids = [w["id"] for w in week["workouts"]]
    assert len(ids) == len(set(ids)), f"дубликаты id тренировок: {ids}"


def test_replan_leaves_no_duplicate_request_ids(
    client: TestClient, data_root: Path
):
    """У тренировок не может быть одного request_id.

    Дубликат request_id — причина того, что удаление дубликата убивало
    выполненную тренировку.
    """
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    request_ids = [w["request_id"] for w in week["workouts"]]
    assert len(request_ids) == len(set(request_ids)), (
        f"дубликаты request_id: {request_ids}"
    )


def test_replan_keeps_both_done_workouts_with_their_facts(
    client: TestClient, data_root: Path
):
    """Обе выполненные тренировки остаются на месте и со своим фактом.

    Репорт: «две уроки были сделаны и к ним был привязан факт», а
    после переплана выполненные тренировки снова можно было привязать.
    """
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    by_actual = {w["actual_id"]: w for w in week["workouts"] if w["actual_id"]}
    assert "a1" in by_actual, "факт бега потерялся"
    assert "a2" in by_actual, "факт ОФП потерялся"
    assert by_actual["a1"]["id"] == "w-r7-4"
    assert by_actual["a2"]["id"] == "w-ofp-1"


def test_replan_keeps_done_workouts_placed(
    client: TestClient, data_root: Path
):
    """Выполненные тренировки остаются привязанными к своим окнам.

    «При нажатии на перепланировать неделю я хочу сбрасывать только те
    тренировки, у которых не привязан факт».
    """
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    placed = {a["request_id"] for a in week["assignments"]}
    assert "r7-4" in placed, "выполненный бег отвязался от окна"
    assert "r7-other-3" in placed, "выполненное ОФП отвязалось от окна"
    assert len(placed) == 2, f"отвязалось лишнее: {placed}"


def test_replan_unplaces_only_workouts_without_fact(
    client: TestClient, data_root: Path
):
    """Отвязанные тренировки уходят в висяки — их можно двигать."""
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    unplaced = {u["id"] for u in week["unplaced"]}
    assert "r7-1" in unplaced
    assert "r7-4" not in unplaced
    assert "r7-other-3" not in unplaced


def test_replan_returns_week_to_proposed(
    client: TestClient, data_root: Path
):
    """Неделя после переплана снова proposed — её можно править."""
    version = _seed(data_root)

    _replan(client, version)

    week = client.get("/api/v1/week/7").json()["data"]
    assert week["status"] == "proposed"


def test_replan_result_can_be_activated(
    client: TestClient, data_root: Path
):
    """После переплана неделю можно активировать — обычный режим."""
    version = _seed(data_root)
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "act-1", "type": "activate_week",
        "args": {"season_week": 7}, "reason": "активировать",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text

    week = client.get("/api/v1/week/7").json()["data"]
    assert week["status"] == "active"


def test_removing_done_workout_is_rejected(
    client: TestClient, data_root: Path
):
    """Выполненную тренировку удалить нельзя.

    Репорт: «Когда я попробовал удалить дубликат из списка планирования,
    он удалил ещё и сделанную тренировку». Удаление идёт по запросу, а
    у дубликата и у выполненной запрос один. Значит, удаление выполненной
    запрещено — иначе факт теряется.
    """
    version = _seed(data_root)
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "rm-1", "type": "remove_workout",
        "args": {"season_week": 7, "workout_id": "w-r7-4"},
        "reason": "удаление дубликата",
        "expected_version": version,
    })
    assert response.status_code == 400, response.text
    assert "факт" in response.json()["error"]["message"]

    week = client.get("/api/v1/week/7").json()["data"]
    done = [w for w in week["workouts"] if w["actual_id"] == "a1"]
    assert len(done) == 1, "выполненную тренировку удалили"


def test_replan_on_closed_week_is_rejected(
    client: TestClient, data_root: Path
):
    """Закрытая неделя не перепланируется."""
    version = _seed(data_root)
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]
    client.post("/api/v1/commands", json={
        "id": "act-1", "type": "activate_week",
        "args": {"season_week": 7}, "reason": "активировать",
        "expected_version": version,
    })
    version = client.get("/api/v1/snapshot").json()["version"]
    client.post("/api/v1/commands", json={
        "id": "close-1", "type": "close_week",
        "args": {"season_week": 7}, "reason": "закрыть",
        "expected_version": version,
    })
    version = client.get("/api/v1/snapshot").json()["version"]

    response = _replan(client, version, "replan-2")
    assert response.status_code == 400
    assert "закрыт" in response.json()["error"]["message"]


def test_removing_workout_remembered_by_fact_is_rejected(
    client: TestClient, data_root: Path
):
    """Тренировку, которую помнит факт, удалить нельзя.

    Связь хранится с обеих сторон (I44), и они могут разъехаться: факт
    помнит тренировку, а у неё `actual_id` пуст. Проверка только по
    `actual_id` такую тренировку пропускала — а удаление роняло связь
    окончательно, и факт оставался висеть со ссылкой в пустоту.
    """
    version = _seed(data_root)

    response = client.post("/api/v1/commands", json={
        "id": "rm-broken", "type": "remove_workout",
        "args": {"season_week": 7, "workout_id": "w-r7-4"},
        "reason": "удаление дубликата",
        "expected_version": version,
    })
    assert response.status_code == 400, response.text
    assert "факт" in response.json()["error"]["message"]

    week = client.get("/api/v1/week/7").json()["data"]
    done = [w for w in week["workouts"] if w["id"] == "w-r7-4"]
    assert len(done) == 1, "тренировку, которую помнит факт, удалили"


def test_removing_workout_with_fact_is_rejected_even_if_link_is_broken(
    client: TestClient, data_root: Path
):
    """Запрет работает и когда связь разъехалась.

    В боевых данных неделя 7 была именно в таком состоянии: факт помнил
    `w-r7-4`, а у тренировки `actual_id` был пуст.
    """
    version = _seed(data_root)
    # Рвём связь с одной стороны — как в боевых данных: факт помнит
    # тренировку, а у тренировки `actual_id` пуст.
    storage = FileStorage(data_root)
    week = storage.week(7)
    for workout in week.workouts:
        if workout.id == "w-ofp-1":
            workout.actual_id = None
            workout.status = WorkoutStatus.PLANNED
    storage.put_week(week, expected_version=storage.version())

    response = client.post("/api/v1/commands", json={
        "id": "rm-ofp", "type": "remove_workout",
        "args": {"season_week": 7, "workout_id": "w-ofp-1"},
        "reason": "удаление дубликата",
        "expected_version": version,
    })
    assert response.status_code == 400, response.text
    assert "факт" in response.json()["error"]["message"]


# --------------- последовательность действий: replan → привязка → propose (I7)


def test_replan_after_propose_and_relink_does_not_break_invariants(
    client: TestClient, data_root: Path
):
    """Переплан после «Предложить заново» не ломает инварианты.

    Сценарий Кирилла (22.11.2026): неделя активна, две тренировки
    выполнены. Дальше: перепланировать остаток → привязать висяков к
    окнам → «Предложить заново» → активировать → привязать оставшихся
    → перепланировать снова. Последний шаг падал:

        I7: неделя W7: запрос r7-other-3 без размещения не в unplaced

    Причина — не в переплане, а в том, что было до него.

    «Предложить заново» пересобирает неделю и **сбрасывает привязки
    факта**: тренировки становятся невыполненными. Но факты помнят
    свои тренировки — обратная ссылка остаётся. Дальше пользователь
    привязывает висяков к окнам, и выполненный запрос оказывается
    без размещения и без unplaced: инвариант I7 нарушен, и переплан
    на нём падает.

    Правильное поведение: «Предложить заново» не должен терять связь
    с фактом. Факт — это сделанная работа, и перепредложение плана её
    не отменяет.
    """
    version = _seed(data_root)

    # 1. Перепланировать остаток.
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    # 2. Привязать висяков к окнам (часть).
    for request_id, slot_id in (("r7-1", "win-ПН-1"), ("r7-2", "win-ЧТ-1")):
        response = client.post("/api/v1/commands", json={
            "id": f"place-{request_id}", "type": "place_unplaced",
            "args": {"season_week": 7, "request_id": request_id,
                     "slot_id": slot_id},
            "reason": "ручная привязка тренировки к окну",
            "expected_version": version,
        })
        assert response.status_code == 200, response.text
        version = client.get("/api/v1/snapshot").json()["version"]

    # 3. «Предложить заново».
    response = client.post("/api/v1/commands", json={
        "id": "propose-1", "type": "propose_week",
        "args": {"season_week": 7}, "reason": "предложить заново",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text
    version = client.get("/api/v1/snapshot").json()["version"]

    # 4. Активировать.
    response = client.post("/api/v1/commands", json={
        "id": "act-1", "type": "activate_week",
        "args": {"season_week": 7}, "reason": "активировать",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text
    version = client.get("/api/v1/snapshot").json()["version"]

    # 5. Привязать оставшихся. Выполненные (`r7-4`, `r7-other-3`)
    # после propose остаются размещёнными — их привязывать заново не
    # нужно и нельзя.
    for request_id, slot_id in (("r7-other-2", "win-ПТ-1"),):
        response = client.post("/api/v1/commands", json={
            "id": f"place2-{request_id}", "type": "place_unplaced",
            "args": {"season_week": 7, "request_id": request_id,
                     "slot_id": slot_id},
            "reason": "ручная привязка тренировки к окну",
            "expected_version": version,
        })
        assert response.status_code == 200, response.text
        version = client.get("/api/v1/snapshot").json()["version"]

    # 6. Перепланировать снова — вот тут и падало.
    response = _replan(client, version, "replan-2")
    assert response.status_code == 200, (
        f"переплан после «Предложить заново» упал: {response.text}"
    )

    week = client.get("/api/v1/week/7").json()["data"]
    # Инвариант I7: каждый запрос либо размещён, либо висит.
    placed = {a["request_id"] for a in week["assignments"]}
    unplaced = {u["id"] for u in week["unplaced"]}
    requests = {r["id"] for r in week["requests"]}
    assert not (requests - placed - unplaced), (
        f"запросы без размещения и не в unplaced: {requests - placed - unplaced}"
    )


def test_propose_keeps_fact_link_of_done_workout(
    client: TestClient, data_root: Path
):
    """«Предложить заново» не теряет связь с фактом.

    Факт — это сделанная работа. Перепредложение плана её не
    отменяет: выполненная тренировка остаётся выполненной, а её
    факт — связанным.

    Раньше propose сбрасывал `actual_id` у всех тренировок, и
    выполненное начинало выглядеть невыполненным — а факты при этом
    продолжали помнить свои тренировки. Связь разъезжалась (I44), и
    следующий переплан падал на инварианте I7.
    """
    version = _seed(data_root)

    # «Предложить заново» — только у proposed-недели (I23). Поэтому
    # сначала переплан возвращает неделю в proposed.
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "propose-1", "type": "propose_week",
        "args": {"season_week": 7}, "reason": "предложить заново",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text

    week = client.get("/api/v1/week/7").json()["data"]
    done = {w["actual_id"]: w["id"] for w in week["workouts"] if w["actual_id"]}
    assert "a1" in done, "факт бега потерялся при «Предложить заново»"
    assert "a2" in done, "факт ОФП потерялся при «Предложить заново»"


def test_propose_leaves_no_duplicate_workout_ids(
    client: TestClient, data_root: Path
):
    """После «Предложить заново» нет двух тренировок с одним id.

    Выполненные тренировки возвращаются в пересобранную неделю — а
    пересборка даёт свои тренировки с теми же id (`w-r7-1…`,
    `w-ofp-1`). Если их не развести, в неделе снова окажутся
    дубликаты — ровно то, из-за чего неделя выглядела «10 тренировок
    вместо 8».
    """
    version = _seed(data_root)
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "propose-1", "type": "propose_week",
        "args": {"season_week": 7}, "reason": "предложить заново",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text

    week = client.get("/api/v1/week/7").json()["data"]
    ids = [w["id"] for w in week["workouts"]]
    assert len(ids) == len(set(ids)), f"дубликаты id тренировок: {ids}"
    request_ids = [w["request_id"] for w in week["workouts"]]
    assert len(request_ids) == len(set(request_ids)), (
        f"дубликаты request_id: {request_ids}"
    )


def test_propose_keeps_invariants(
    client: TestClient, data_root: Path
):
    """После «Предложить заново» инварианты недели целы.

    I7: каждый запрос либо размещён, либо висит.
    """
    version = _seed(data_root)
    _replan(client, version)
    version = client.get("/api/v1/snapshot").json()["version"]

    response = client.post("/api/v1/commands", json={
        "id": "propose-1", "type": "propose_week",
        "args": {"season_week": 7}, "reason": "предложить заново",
        "expected_version": version,
    })
    assert response.status_code == 200, response.text

    week = client.get("/api/v1/week/7").json()["data"]
    placed = {a["request_id"] for a in week["assignments"]}
    unplaced = {u["id"] for u in week["unplaced"]}
    requests = {r["id"] for r in week["requests"]}
    assert not (requests - placed - unplaced), (
        f"запросы без размещения и не в unplaced: {requests - placed - unplaced}"
    )
