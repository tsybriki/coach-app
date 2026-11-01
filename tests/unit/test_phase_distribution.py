"""Распределение недель программы Дэниэлса по фазам — по длине сезона.

Правило (Кирилл):

- **срок меньше 24 недель** — берётся таблица базового горизонта, недели
  программы сверх срока отпадают;
- **срок 24 недели** — та же таблица целиком (эталон);
- **срок больше 24 недель** — фазы собираются из **своих недель программы
  подряд** (I — 1-6, II — 7-12, III — 13-18, IV — 19-24), а лишние недели
  программы идут по кругу через фазы 2, 3, 4: по очереди, II → III → IV →
  II → … Фаза I не растёт;
- **в фазах 2 и 3** лишняя неделя встаёт в **конец** фазы, а её план —
  две **последние** недели фазы по кругу: II — 11, 12; III — 17, 18;
- **в фазе 4** лишняя неделя встает в **начало** фазы, а её план — две
  **первые** недели фазы по кругу: 19, 20.

Отдельный случай **одной** лишней недели не существует: план всегда берётся
по кругу из двух недель края, поэтому одна лишняя неделя фазы 2 берёт план
11-й, фазы 3 — 17-й, фазы 4 — 19-й.

Тесты проверяют распределение **по фазам** — от раскладки недель до плана
каждой лишней недели. Проверка того, что из раскладки следует (рецепты
недели), живёт в `tools/verify_phase_four_plans.py` и в
`tests/unit/test_macro_planner_agreement.py`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.daniels import load_plan
from app.domain.methodology import MethodPlan, WeekSchedule

REPO = Path(__file__).resolve().parent.parent.parent
REFERENCE = REPO / "reference" / "daniels"

# Базовый горизонт: 24 недели до старта (эталон Кирилла).
BASE_WEEKS = 24

# Таблица базового горизонта: перечисление недель программы по фазам
# с перестановкой. Одна и та же неделя программы в разных сроках попадает
# в разные фазы.
BASE = {
    1: (1, 2, 3, 13, 21, 23),
    2: (10, 11, 12, 18, 19, 20),
    3: (7, 8, 9, 14, 15, 16),
    4: (4, 5, 6, 17, 22, 24),
}

# Недели программы каждой фазы подряд — для срока больше базового.
PROGRAM = {
    1: (1, 2, 3, 4, 5, 6),
    2: (7, 8, 9, 10, 11, 12),
    3: (13, 14, 15, 16, 17, 18),
    4: (19, 20, 21, 22, 23, 24),
}

# Фазы, по кругу через которые идут лишние недели программы.
EXTRA_CYCLE = (2, 3, 4)

# Фаза, которая растёт в начало: лишняя неделя встаёт в начало фазы.
FRONT_PHASE = 4

# План лишней недели — край фазы: фазы 2 и 3 растут в конец (хвост),
# фаза 4 — в начало (первые две недели).
EDGE_PLANS = {
    2: (11, 12),
    3: (17, 18),
    4: (19, 20),
}


@pytest.fixture(scope="module")
def plan() -> MethodPlan:
    return load_plan(REFERENCE)


def season_weeks(schedule: WeekSchedule) -> dict[int, list[tuple[int, int]]]:
    """Недели сезона по фазам: список (программная неделя, её план).

    Номер недели сезона считается накоплением по фазам — **не руками**:
    длина фаз меняется с горизонтом, и выдуманный offset попадает не в ту
    неделю.
    """
    result: dict[int, list[tuple[int, int]]] = {}
    season_week = 0
    for phase in sorted(schedule.phases):
        rows: list[tuple[int, int]] = []
        for program_week in schedule.weeks_for(phase):
            season_week += 1
            rows.append((program_week, schedule.plan_for(program_week)))
        result[phase] = rows
    return result


# ------------------------------------------------------------------ срок меньше базы


@pytest.mark.parametrize("weeks", [10, 15, 19, 20, 23])
def test_shorter_term_uses_base_table(plan: MethodPlan, weeks: int):
    """Короче 24: та же таблица, недели программы сверх срока отпадают."""
    schedule = plan.schedule_for(weeks)
    assert schedule is not None

    for phase, program_weeks in BASE.items():
        expected = tuple(w for w in program_weeks if w <= weeks)
        assert schedule.weeks_for(phase) == expected, \
            f"срок {weeks}: фаза {phase} — {schedule.weeks_for(phase)}, " \
            f"ожидалось {expected}"


def test_shorter_term_keeps_total(plan: MethodPlan):
    """Сумма недель в фазах равна сроку — при любом сроке."""
    for weeks in range(1, BASE_WEEKS + 1):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        assert schedule.total() == weeks, f"срок {weeks}: сумма не сходится"


def test_nineteen_weeks_layout(plan: MethodPlan):
    """Срок 19 недель — разобранный пример Кирилла."""
    schedule = plan.schedule_for(19)
    assert schedule is not None
    assert schedule.weeks_for(1) == (1, 2, 3, 13)
    assert schedule.weeks_for(2) == (10, 11, 12, 18, 19)
    assert schedule.weeks_for(3) == (7, 8, 9, 14, 15, 16)
    assert schedule.weeks_for(4) == (4, 5, 6, 17)
    assert schedule.total() == 19


# ------------------------------------------------------------------ базовый горизонт


def test_base_horizon_is_the_etable(plan: MethodPlan):
    """24 недели — эталон, воспроизводится бит-в-бит."""
    schedule = plan.schedule_for(BASE_WEEKS)
    assert schedule is not None
    for phase, program_weeks in BASE.items():
        assert schedule.weeks_for(phase) == program_weeks, \
            f"фаза {phase}: {schedule.weeks_for(phase)} ≠ {program_weeks}"


def test_base_horizon_plans_are_own_weeks(plan: MethodPlan):
    """На базовом горизонте план недели — она сама."""
    schedule = plan.schedule_for(BASE_WEEKS)
    assert schedule is not None
    for phase in BASE:
        for program_week in schedule.weeks_for(phase):
            assert schedule.plan_for(program_week) == program_week


# ------------------------------------------------------------------ срок больше базы


def test_longer_term_phases_use_own_program_weeks(plan: MethodPlan):
    """Длиннее 24: фазы собираются из своих недель программы подряд.

    Перестановка базовой таблицы описывает только базовый горизонт: на
    длинном сроке неделя 11 программы обязана быть одиннадцатой неделей
    фазы II, а не «неделей фазы II» из перетасованной таблицы.
    """
    schedule = plan.schedule_for(30)
    assert schedule is not None
    for phase, program_weeks in PROGRAM.items():
        own = tuple(w for w in schedule.weeks_for(phase) if w <= BASE_WEEKS)
        assert own == program_weeks, \
            f"фаза {phase}: свои недели {own} ≠ {program_weeks}"


def test_extra_weeks_go_to_phases_two_three_four_in_turn(plan: MethodPlan):
    """Лишние недели идут по очереди: II → III → IV → II → …

    Одна лишняя неделя достаётся только первой фазе цикла, а не всем
    трём сразу.
    """
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        extras = [
            w for w in range(BASE_WEEKS + 1, weeks + 1)
        ]
        for index, program_week in enumerate(extras):
            expected_phase = EXTRA_CYCLE[index % len(EXTRA_CYCLE)]
            assert schedule.phase_of(program_week) == expected_phase, \
                f"срок {weeks}: неделя {program_week} должна быть в фазе " \
                f"{expected_phase}"


def test_phase_one_never_grows(plan: MethodPlan):
    """Фаза I не растёт: это база, а не тренировка."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 16):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        assert schedule.weeks_for(1) == PROGRAM[1]


def test_extra_weeks_split_evenly_by_turn(plan: MethodPlan):
    """29 недель: 5 лишних → 2 в фазу II, 2 в фазу III, 1 в фазу IV."""
    schedule = plan.schedule_for(29)
    assert schedule is not None
    base = plan.schedule_for(BASE_WEEKS)
    assert base is not None
    extras = {
        phase: len(schedule.weeks_for(phase)) - len(base.weeks_for(phase))
        for phase in sorted(schedule.phases)
    }
    assert extras == {1: 0, 2: 2, 3: 2, 4: 1}
    assert schedule.total() == 29


# ------------------------------------------------------------------ где стоит лишняя неделя


def test_extra_weeks_of_phases_two_and_three_stand_at_the_end(plan: MethodPlan):
    """Фазы 2 и 3 растут в конец: лишние недели — после своих."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        for phase in (2, 3):
            program_weeks = schedule.weeks_for(phase)
            extras = [w for w in program_weeks if w > BASE_WEEKS]
            if not extras:
                continue
            assert program_weeks[-len(extras):] == tuple(extras), \
                f"срок {weeks}: лишние недели фазы {phase} не в конце"
            own = tuple(w for w in program_weeks if w <= BASE_WEEKS)
            assert program_weeks[:len(own)] == own


def test_extra_weeks_of_phase_four_stand_at_the_front(plan: MethodPlan):
    """Фаза 4 растёт в начало: лишние недели — перед своими.

    Фаза IV растёт вперёд, чтобы соревновательные недели программы
    (23, 24) не отодвигались от гонки.
    """
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        program_weeks = schedule.weeks_for(FRONT_PHASE)
        extras = [w for w in program_weeks if w > BASE_WEEKS]
        if not extras:
            continue
        assert program_weeks[:len(extras)] == tuple(extras), \
            f"срок {weeks}: лишние недели фазы IV не в начале"
        own = tuple(w for w in program_weeks if w <= BASE_WEEKS)
        assert program_weeks[len(extras):] == own


# ------------------------------------------------------------------ план лишней недели


def test_extra_week_plan_of_phase_two_is_last_two_weeks(plan: MethodPlan):
    """Фаза 2: план лишней недели — две последние недели фазы (11, 12)."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        extras = [w for w in schedule.weeks_for(2) if w > BASE_WEEKS]
        for position, program_week in enumerate(extras):
            expected = EDGE_PLANS[2][position % len(EDGE_PLANS[2])]
            assert schedule.plan_for(program_week) == expected, \
                f"срок {weeks}: неделя {program_week} фазы 2 — план " \
                f"{schedule.plan_for(program_week)}, ожидалось {expected}"


def test_extra_week_plan_of_phase_three_is_last_two_weeks(plan: MethodPlan):
    """Фаза 3: план лишней недели — две последние недели фазы (17, 18)."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        extras = [w for w in schedule.weeks_for(3) if w > BASE_WEEKS]
        for position, program_week in enumerate(extras):
            expected = EDGE_PLANS[3][position % len(EDGE_PLANS[3])]
            assert schedule.plan_for(program_week) == expected, \
                f"срок {weeks}: неделя {program_week} фазы 3 — план " \
                f"{schedule.plan_for(program_week)}, ожидалось {expected}"


def test_extra_week_plan_of_phase_four_is_first_two_weeks(plan: MethodPlan):
    """Фаза 4: план лишней недели — две первые недели фазы (19, 20)."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 13):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        extras = [w for w in schedule.weeks_for(FRONT_PHASE) if w > BASE_WEEKS]
        for position, program_week in enumerate(extras):
            expected = EDGE_PLANS[4][position % len(EDGE_PLANS[4])]
            assert schedule.plan_for(program_week) == expected, \
                f"срок {weeks}: неделя {program_week} фазы 4 — план " \
                f"{schedule.plan_for(program_week)}, ожидалось {expected}"


def test_single_extra_week_takes_first_week_of_the_cycle(plan: MethodPlan):
    """Одна лишняя неделя — план из круга, а не из отдельного правила.

    Отдельного правила «одна лишняя неделя» нет: план всегда идёт по
    кругу из двух недель края, поэтому первая лишняя неделя фазы 2 берёт
    11-ю, фазы 3 — 17-ю, фазы 4 — 19-ю.
    """
    single_ii = plan.schedule_for(25)
    assert single_ii is not None
    assert single_ii.plan_for(25) == 11

    single_iii = plan.schedule_for(26)
    assert single_iii is not None
    assert single_iii.plan_for(26) == 17

    single_iv = plan.schedule_for(27)
    assert single_iv is not None
    assert single_iv.plan_for(27) == 19


def test_extra_week_plans_repeat_cyclically(plan: MethodPlan):
    """Планы лишних недель повторяются по кругу.

    Три лишние недели фазы 2 берут 11, 12, 11; четыре — 11, 12, 11, 12.
    """
    three = plan.schedule_for(32)
    assert three is not None
    assert [
        three.plan_for(w) for w in three.weeks_for(2) if w > BASE_WEEKS
    ] == [11, 12, 11]

    four = plan.schedule_for(34)
    assert four is not None
    assert [
        four.plan_for(w) for w in four.weeks_for(2) if w > BASE_WEEKS
    ] == [11, 12, 11, 12]


def test_extra_week_plan_comes_from_its_own_phase(plan: MethodPlan):
    """План лишней недели — с края именно её фазы."""
    for weeks in range(BASE_WEEKS + 1, BASE_WEEKS + 16):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        for phase, program_weeks in schedule.phases.items():
            extras = [w for w in program_weeks if w > BASE_WEEKS]
            for program_week in extras:
                assert schedule.plan_for(program_week) in EDGE_PLANS[phase], \
                    f"срок {weeks}: неделя {program_week} фазы {phase} — " \
                    f"план не с края фазы"


# ------------------------------------------------------------------ инварианты срока


def test_every_term_keeps_total_and_order(plan: MethodPlan):
    """Любой срок: сумма равна сроку, фазы идут по порядку, недели уникальны.

    Прыжок фазы (1, 2, 3, 1) означал бы, что неделя из третьей фазы
    оказалась раньше второй.
    """
    for weeks in range(1, BASE_WEEKS + 16):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        assert schedule.total() == weeks, f"срок {weeks}: сумма не сходится"

        flat = [
            phase
            for phase in sorted(schedule.phases)
            for _ in schedule.weeks_for(phase)
        ]
        assert flat == sorted(flat), f"срок {weeks}: фазы идут не по порядку"

        all_weeks = [
            w for phase in schedule.phases for w in schedule.weeks_for(phase)
        ]
        assert len(set(all_weeks)) == weeks, f"срок {weeks}: недели повторяются"


def test_plan_week_matches_schedule(plan: MethodPlan):
    """`plan_week` — тот же расклад, что и расписание.

    Номер недели сезона считается накоплением по фазам — руками его брать
    нельзя: длина фаз меняется с горизонтом.
    """
    for weeks in (19, 24, 27, 29, 30, 33):
        schedule = plan.schedule_for(weeks)
        assert schedule is not None
        rows = season_weeks(schedule)
        offset = 0
        for phase in sorted(rows):
            for program_week, plan_week in rows[phase]:
                mapped = plan.plan_week(weeks, offset)
                assert mapped == (phase, program_week, plan_week), \
                    f"срок {weeks}, неделя сезона {offset + 1}: " \
                    f"{mapped} ≠ {(phase, program_week, plan_week)}"
                offset += 1


def test_nine_week_layout_by_season_week(plan: MethodPlan):
    """29 недель — разобранная раскладка Кирилла, по неделям сезона."""
    schedule = plan.schedule_for(29)
    assert schedule is not None
    rows = season_weeks(schedule)

    assert rows[1] == [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6)]
    assert rows[2] == [
        (7, 7), (8, 8), (9, 9), (10, 10), (11, 11), (12, 12),
        (25, 11), (28, 12),
    ]
    assert rows[3] == [
        (13, 13), (14, 14), (15, 15), (16, 16), (17, 17), (18, 18),
        (26, 17), (29, 18),
    ]
    assert rows[4] == [
        (27, 19), (19, 19), (20, 20), (21, 21), (22, 22), (23, 23), (24, 24),
    ]
