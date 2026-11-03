"""
Что можно делать в окне: место определяет доступные виды спорта.

Дефект, который это ловит: вел вставал во вторник, где велосипеда нет.
Окно хранило только строку места (`note`), а планировщик смотрел на
время и вместимость — и клал вел в любое окно, которое влезло по
длительности.

Правило: у окна есть место, и место определяет, чего там нет.
Станок стоит дома, на асфальте велосипеда нет.
"""
from __future__ import annotations

from app.domain.enums import Sport
from app.domain.slot_rules import (
    forbidden_sports_for_location,
    location_suits_sport,
)


def test_asphalt_window_has_no_bike():
    """Асфальт — бег, но не велосипед."""
    assert Sport.BIKE in forbidden_sports_for_location("asphalt_commuter")
    assert Sport.RUN not in forbidden_sports_for_location("asphalt_commuter")


def test_home_stationary_bike_window_allows_bike():
    """Дома со станком — велосипед есть."""
    assert Sport.BIKE not in forbidden_sports_for_location("home_stationary_bike")
    assert Sport.SWIM in forbidden_sports_for_location("home_stationary_bike")


def test_long_ride_window_allows_bike():
    """Длинная поездка или станция — велосипед есть."""
    assert Sport.BIKE not in forbidden_sports_for_location("long_ride_or_station")


def test_pool_window_allows_swim():
    """Окно «бассейн или асфальт» — плавать можно."""
    assert Sport.SWIM not in forbidden_sports_for_location("pool_or_asphalt")
    assert Sport.SWIM not in forbidden_sports_for_location("stadium_or_pool")


def test_empty_location_has_no_bike():
    """Пустое место — «улица»: станка там нет."""
    assert Sport.BIKE in forbidden_sports_for_location(None)
    assert Sport.BIKE in forbidden_sports_for_location("")


def test_unknown_location_forbids_nothing():
    """Неизвестное место не запрещает ничего.

    Лучше показать лишнее окно, чем спрятать существующее.
    """
    assert not forbidden_sports_for_location("somewhere_new")


def test_location_suits_sport():
    """Прямая проверка «подходит ли вид спорта этому месту»."""
    assert location_suits_sport("home_stationary_bike", Sport.BIKE)
    assert not location_suits_sport("asphalt_commuter", Sport.BIKE)
    assert location_suits_sport("asphalt_commuter", Sport.RUN)


def test_tuesday_window_forbids_bike():
    """Конкретный баг: во вторник окно на асфальте.

    Окно `asphalt_commuter` — это бег по дороге. Велотренажёра там нет.
    """
    forbidden = forbidden_sports_for_location("asphalt_commuter")
    assert Sport.BIKE in forbidden, \
        "в асфальтовом окне нельзя ездить на велосипеде"
    assert Sport.SWIM in forbidden, \
        "в асфальтовом окне нельзя плавать"


def test_only_two_windows_allow_bike():
    """Велосипед доступен ровно в двух окнах недели.

    Проверка на реальных окнах: «длинная поездка или станция» в
    воскресенье и станок дома в четверг. В остальных шести окна
    велосипеда нет.
    """
    windows = {
        "ВС 11:00": "long_ride_or_station",
        "ПН 18:45": "stadium",
        "ВТ 09:00": "asphalt_commuter",
        "ВТ 18:30": "asphalt_commuter",
        "СР 17:00": "stadium_or_pool",
        "ЧТ 10:30": "home_stationary_bike",
        "ПТ 18:00": "pool_or_asphalt",
        "СБ 10:00": "home",
    }
    with_bike = [name for name, place in windows.items()
                 if location_suits_sport(place, Sport.BIKE)]
    assert with_bike == ["ВС 11:00", "ЧТ 10:30"], \
        f"велосипед доступен не в тех окнах: {with_bike}"
