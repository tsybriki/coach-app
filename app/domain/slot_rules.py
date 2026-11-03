"""
slot_rules.py — что можно делать в окне.

Окно — это не только время. У окна есть **место**: асфальт, стадион,
бассейн, велотренажёр. Велотренажёра в асфальтовом окне нет, и вел
в такое окно встать не может.

Раньше это правило не было выражено в данных: окно хранило только
`note` со строкой места, а планировщик смотрел на время и вместимость.
В итоге вел вставал во вторник, где велосипеда нет.

Здесь — правило «место → чего там нет». Запреты, а не разрешения: всё,
что не запрещено, в этом месте возможно. Так правило не ломается от
появления нового вида спорта.

Как это используется:
  - окно получает `forbidden_sports` при импорте (см. `import_pipeline`);
  - приложение показывает пользователю, что можно положить в окно.

Смысл мест (из `coach/state/constraints.json`):

| место | чего там нет |
|---|---|
| `asphalt_commuter` | велосипеда, бассейна |
| `stadium` | велосипеда, бассейна |
| `stadium_or_pool` | велосипеда |
| `pool_or_asphalt` | велосипеда |
| `home_stationary_bike` | бассейна |
| `long_ride_or_station` | бассейна |
| `home` | велосипеда, бассейна |
| пусто (улица) | велосипеда, бассейна |
| неизвестное | ничего не запрещено |

Про велосипед: он есть в двух окнах — `long_ride_or_station` (поездка
или станка) и `home_stationary_bike` (домашний станок). В остальных
окнах велосипеда нет: на дорогу его не берут, а станок стоит там, где
стоит.

Про бассейн: он есть в `stadium_or_pool` и `pool_or_asphalt`.
"""
from __future__ import annotations

from app.domain.enums import Sport

# Место → чего в этом месте нет.
LOCATION_FORBIDDEN: dict[str, frozenset[Sport]] = {
    "asphalt_commuter": frozenset({Sport.BIKE, Sport.SWIM}),
    "stadium": frozenset({Sport.BIKE, Sport.SWIM}),
    "stadium_or_pool": frozenset({Sport.BIKE}),
    "pool_or_asphalt": frozenset({Sport.BIKE}),
    "home_stationary_bike": frozenset({Sport.SWIM}),
    "long_ride_or_station": frozenset({Sport.SWIM}),
    "home": frozenset({Sport.BIKE, Sport.SWIM}),
}

# Пустое место — «улица»: ни велосипеда, ни бассейна.
_STREET = frozenset({Sport.BIKE, Sport.SWIM})


def forbidden_sports_for_location(location: str | None) -> frozenset[Sport]:
    """Виды спорта, запрещённые в этом месте.

    Неизвестное место не запрещает ничего: лучше показать лишнее
    окно, чем спрятать существующее.
    """
    if not location:
        return _STREET
    return LOCATION_FORBIDDEN.get(location, frozenset())


def location_suits_sport(location: str | None, sport: Sport) -> bool:
    """Можно ли в этом месте заниматься этим видом спорта."""
    return sport not in forbidden_sports_for_location(location)
