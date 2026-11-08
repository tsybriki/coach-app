"""Метрики формы и нагрузки.

Считаются из разбора FIT-файла (зоны пульса, темп, мощность, каденция)
и из факта Garmin (`vo2max`, `aerobic_te`).

**Что здесь, а что нет.** Метрики 1–8 требуют разбора FIT: пульсовые зоны
и темп в них считаются по секундным записям. Без FIT считаются только
те, что Garmin отдаёт сам (`vo2max`, TE) — они приходят с фактом.

**Правило TSS (TrainingPeaks).**
`TSS = (часы × NP × IF) / FTP × 100`, где `IF = NP / FTP`.
Считается от **мощности**, а не от пульса: FTP — это порог мощности,
и пульсовые зоны его не заменяют.

Без FTP TSS не считается: подставлять выдуманное значение нельзя,
метрика просто не появляется. FTP живёт в профиле атлета (`Athlete.ftp_w`).

**Скорость в пульсовых зонах.** Темп в зоне — средний темп секунд, в
которых пульс лежал в этой зоне. Это ответ на вопрос «какой темп я
выдерживаю на пульсе 130»: не «средний темп тренировки», а темп именно
в той зоне, где пульс был.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.entities import ActualSession, WorkoutDetail

# Зоны пульса, которые считаем «интенсивными» (пульс выше порога).
# Границы — из профиля атлета; здесь только имена зон по умолчанию.
INTENSIVE_ZONES = ("Z5", "Z6", "Z7")

# Зоны мощности Coggan (доля от FTP) — для TSS по зонам.
POWER_ZONES = (
    ("Z1", 0.0, 0.55),
    ("Z2", 0.55, 0.75),
    ("Z3", 0.75, 0.90),
    ("Z4", 0.90, 1.05),
    ("Z5", 1.05, 1.20),
    ("Z6", 1.20, 1.50),
    ("Z7", 1.50, 10.0),
)


@dataclass
class WorkoutMetrics:
    """Метрики одной выполненной тренировки.

    Всё, что не удалось посчитать, — `None`. Метрика без данных не
    выдумывается: пустое значение честнее нуля.
    """

    actual_id: str
    # Дата факта — «воскресенье 13 км» на экране «Факт». Без неё
    # список тренировок нельзя ни прочитать, ни отсортировать.
    date: str | None = None
    # 1–3: объём в зонах пульса, минуты
    z2_min: float | None = None
    z3_min: float | None = None
    z4_min: float | None = None
    hi_min: float | None = None
    # 5: темп в Z2, секунды на километр
    pace_z2_sec_per_km: float | None = None
    # 8: нагрузка по TrainingPeaks
    tss: float | None = None
    intensity_factor: float | None = None
    normalized_power_w: int | None = None
    # 11: форма по Garmin
    vo2max: float | None = None
    # 12: эффективность — VDOT-темп против фактического
    efficiency: float | None = None
    # Темп по форме и отставание от него: «темп по форме 4:11, факт 5:52»
    # понятнее голого отношения 0,68.
    form_pace_sec_per_km: float | None = None
    pace_gap_sec_per_km: float | None = None
    # 14: каденция
    cadence_avg: int | None = None
    cadence_work: int | None = None
    # справочные величины
    duration_min: float = 0.0
    distance_m: float = 0.0
    avg_hr: int | None = None
    zones: dict[str, float] = field(default_factory=dict)
    # Считалcя ли разбор: метрики без FIT считать не из чего.
    workout_counted: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Метрики — в словарь ответа API."""
        return {
            "actual_id": self.actual_id,
            "date": self.date,
            "z2_min": _round(self.z2_min, 1),
            "z3_min": _round(self.z3_min, 1),
            "z4_min": _round(self.z4_min, 1),
            "hi_min": _round(self.hi_min, 1),
            "pace_z2_sec_per_km": _round(self.pace_z2_sec_per_km, 1),
            "pace_z2": _format_pace(self.pace_z2_sec_per_km),
            "tss": _round(self.tss, 1),
            "intensity_factor": _round(self.intensity_factor, 2),
            "normalized_power_w": self.normalized_power_w,
            "vo2max": self.vo2max,
            "efficiency": _round(self.efficiency, 3),
            "form_pace_sec_per_km": _round(self.form_pace_sec_per_km, 1),
            "form_pace": _format_pace(self.form_pace_sec_per_km),
            "pace_gap_sec_per_km": _round(self.pace_gap_sec_per_km, 1),
            "cadence_avg": self.cadence_avg,
            "cadence_work": self.cadence_work,
            "workout_counted": self.workout_counted,
            "duration_min": _round(self.duration_min, 1),
            "distance_m": _round(self.distance_m, 1),
            "avg_hr": self.avg_hr,
            "zones": {k: _round(v, 1) for k, v in self.zones.items()},
        }


@dataclass
class WeekMetrics:
    """Метрики недели: сумма по тренировкам + производные."""

    week_id: str
    z2_min: float = 0.0
    z3_min: float = 0.0
    z4_min: float = 0.0
    hi_min: float = 0.0
    tss: float = 0.0
    pace_z2_sec_per_km: float | None = None
    vo2max: float | None = None
    efficiency: float | None = None
    # Темп по форме и отставание от него (секунды на км).
    form_pace_sec_per_km: float | None = None
    pace_gap_sec_per_km: float | None = None
    cadence_avg: int | None = None
    cadence_work: int | None = None
    workouts_counted: int = 0
    per_workout: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "week_id": self.week_id,
            "z2_min": _round(self.z2_min, 1),
            "z3_min": _round(self.z3_min, 1),
            "z4_min": _round(self.z4_min, 1),
            "hi_min": _round(self.hi_min, 1),
            "tss": _round(self.tss, 1),
            "pace_z2_sec_per_km": _round(self.pace_z2_sec_per_km, 1),
            "pace_z2": _format_pace(self.pace_z2_sec_per_km),
            "vo2max": _round(self.vo2max, 1),
            "efficiency": _round(self.efficiency, 3),
            "form_pace_sec_per_km": _round(self.form_pace_sec_per_km, 1),
            "form_pace": _format_pace(self.form_pace_sec_per_km),
            "pace_gap_sec_per_km": _round(self.pace_gap_sec_per_km, 1),
            "cadence_avg": self.cadence_avg,
            "cadence_work": self.cadence_work,
            "workouts_counted": self.workouts_counted,
            "per_workout": self.per_workout,
        }


def workout_metrics(
    detail: WorkoutDetail | None,
    session: ActualSession | None = None,
    ftp_w: float | None = None,
    vdot: float | None = None,
    vdot_pace_sec_per_km: float | None = None,
) -> WorkoutMetrics:
    """Метрики тренировки — из разбора FIT и факта.

    `detail` может быть `None`: FIT не разобран. Тогда доступны только
    величины из факта (`vo2max`).
    """
    actual_id = ""
    if detail is not None:
        actual_id = detail.actual_id
    elif session is not None:
        actual_id = session.id

    metrics = WorkoutMetrics(actual_id=actual_id)

    if session is not None:
        metrics.vo2max = session.vo2max
        metrics.duration_min = float(session.duration_min)
        metrics.distance_m = float(session.distance_m)
        metrics.avg_hr = session.hr_avg
        metrics.date = session.date.isoformat()

    if detail is None:
        return metrics

    metrics.workout_counted = True
    zones = {k: float(v) for k, v in (detail.hr_zone_minutes or {}).items()}
    metrics.zones = zones
    metrics.z2_min = zones.get("Z2")
    metrics.z3_min = zones.get("Z3")
    metrics.z4_min = zones.get("Z4")
    hi = sum(zones.get(zone, 0.0) for zone in INTENSIVE_ZONES)
    metrics.hi_min = hi or None

    metrics.duration_min = detail.duration_s / 60.0 if detail.duration_s else metrics.duration_min
    metrics.distance_m = detail.distance_m or metrics.distance_m
    metrics.avg_hr = detail.avg_hr if detail.avg_hr is not None else metrics.avg_hr

    # 5: темп в Z2 — по секундным рядам, с отсевом отдыха.
    metrics.pace_z2_sec_per_km = pace_in_zone(detail, "Z2", zones)

    # 8: TSS по TrainingPeaks — от мощности.
    if ftp_w:
        np_w = _normalized_power(detail)
        metrics.normalized_power_w = np_w
        if np_w:
            metrics.intensity_factor = np_w / ftp_w
            metrics.tss = tss_from_power(
                elapsed_s=detail.elapsed_s or detail.duration_s,
                normalized_power_w=np_w,
                ftp_w=ftp_w,
            )

    # 12: эффективность — VDOT-темп против фактического.
    metrics.efficiency = efficiency(
        actual_pace_sec_per_km=_pace_of(detail),
        vdot_pace_sec_per_km=vdot_pace_sec_per_km,
    )
    # Темп по форме и отставание от него — читаемое представление
    # эффективности: «темп по форме 4:11, факт 5:52» понятнее, чем
    # отношение 0,68 без пояснений.
    metrics.form_pace_sec_per_km = vdot_pace_sec_per_km
    actual_pace = _pace_of(detail)
    if actual_pace and vdot_pace_sec_per_km:
        metrics.pace_gap_sec_per_km = actual_pace - vdot_pace_sec_per_km

    # 14: каденция — средняя и в рабочей части (пульс выше Z1).
    metrics.cadence_avg = detail.avg_cadence
    metrics.cadence_work = cadence_in_work(detail)

    return metrics


# Каденция ниже этого — человек стоял, а не бежал. В трубке пульс
# низкий, и без такой отсечки «темп в зоне» считает темп отдыха.
REST_CADENCE = 65


def pace_in_zone(
    detail: WorkoutDetail,
    zone: str,
    zones: dict[str, float],
) -> float | None:
    """Темп в зоне пульса — секунды на километр.

    Считается по **секундным рядам**, а не по сплитам Garmin. Сплиты
    Garmin — это лапы, и в интервальной тренировке их границы не
    совпадают с работой: в лапу попадает и отдых. По рядам видно,
    где человек стоял, а где бежал.

    **Отдых внутри зоны не считается.** В трубке пульс низкий, и отдых
    при пульсе 120 попадает в Z2. Считая его, получаем «6:43 на км на
    пульсе 130» — то есть темп отдыха, а не темп бега в зоне.

    Отдых отсекается по каденции: на бегу она держится около 80, а
    стоя на месте падает ниже 65.

    `zones` — минуты в зонах: нужна, чтобы понять, что зона вообще
    была в тренировке (пустая зона → `None`, а не деление на ноль).
    """
    if not zones.get(zone):
        return None
    bounds = _zone_bounds_from_minutes(zone)
    if bounds is None:
        return None
    low, high = bounds

    distance_by_t = dict(detail.series_distance)
    cadence_by_t = dict(detail.series_cadence)
    series = detail.series_hr
    if len(series) < 2:
        return None

    seconds = 0.0
    meters = 0.0
    for index in range(1, len(series)):
        t0, hr0 = series[index - 1]
        t1, hr1 = series[index]
        if not (low <= hr1 < high):
            continue
        d0 = distance_by_t.get(t0)
        d1 = distance_by_t.get(t1)
        if d0 is None or d1 is None:
            continue
        moved = d1 - d0
        if moved <= 0:
            continue
        cadence = cadence_by_t.get(t1)
        if cadence is not None and cadence < REST_CADENCE:
            continue  # стоял, а не бежал
        seconds += t1 - t0
        meters += moved

    if seconds <= 0 or meters <= 0:
        return None
    return seconds / (meters / 1000.0)


def _zone_bounds_from_minutes(zone: str) -> tuple[int, int] | None:
    """Границы зоны — по её имени, в стандартной разбивке атлета.

    Разбивка та же, что в профиле: Z1 100–118, Z2 118–135, Z3 135–150,
    Z4 150–160, Z5 160–168, Z6 168–172, Z7 172–182.
    """
    bounds = {
        "Z1": (100, 118),
        "Z2": (118, 135),
        "Z3": (135, 150),
        "Z4": (150, 160),
        "Z5": (160, 168),
        "Z6": (168, 172),
        "Z7": (172, 182),
    }
    return bounds.get(zone)


def tss_from_power(
    elapsed_s: float,
    normalized_power_w: float,
    ftp_w: float,
) -> float | None:
    """TSS по TrainingPeaks: `(часы × NP × IF) / FTP × 100`.

    `IF = NP / FTP`. Без FTP нагрузку не посчитать — `None`.
    """
    if not ftp_w or normalized_power_w <= 0 or elapsed_s <= 0:
        return None
    intensity_factor = normalized_power_w / ftp_w
    hours = elapsed_s / 3600.0
    return hours * normalized_power_w * intensity_factor / ftp_w * 100.0


def _normalized_power(detail: WorkoutDetail) -> int | None:
    """Нормализованная мощность.

    Garmin в FIT её не отдаёт для бега (только для велосипеда), поэтому
    считаем сами по секундному ряду мощности: среднее четвёртой степени
    за 30-секундные скользящие окна.
    """
    if detail.normalized_power_w:
        return detail.normalized_power_w

    series = detail.series_power
    if not series:
        return None
    # Ряд прорежен шагом 15 секунд — для NP этого мало, но другого нет.
    # Считаем по доступным точкам: среднее четвёртой степени.
    values = [float(v) for _, v in series if v is not None]
    if len(values) < 4:
        return None
    mean_fourth = sum(v ** 4 for v in values) / len(values)
    if mean_fourth <= 0:
        return None
    return int(round(mean_fourth ** 0.25))


def efficiency(
    actual_pace_sec_per_km: float | None,
    vdot_pace_sec_per_km: float | None,
) -> float | None:
    """Эффективность формы: VDOT-темп против фактического.

    Больше 1 — фактический темп лучше расчётного по форме.
    """
    if not actual_pace_sec_per_km or not vdot_pace_sec_per_km:
        return None
    return vdot_pace_sec_per_km / actual_pace_sec_per_km


def cadence_in_work(detail: WorkoutDetail) -> int | None:
    """Каденция в рабочей части — по сплитам с пульсом выше Z1.

    Разминка и заминка её занижают, а каденция в рабочей части —
    то, что радикально измеряется.
    """
    values = [
        split.avg_cadence
        for split in detail.splits
        if split.avg_cadence and split.avg_hr and split.avg_hr >= 118
    ]
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def _pace_of(detail: WorkoutDetail) -> float | None:
    """Средний темп тренировки — секунды на километр."""
    if detail.distance_m <= 0 or detail.duration_s <= 0:
        return None
    return detail.duration_s / (detail.distance_m / 1000.0)


def week_metrics(
    week_id: str,
    per_workout: list[WorkoutMetrics],
    vo2max_values: list[float] | None = None,
) -> WeekMetrics:
    """Метрики недели — сумма по тренировкам.

    Темп в Z2 на уровне недели — средневзвешенный по расстоянию:
    «65 км лёгких» и «65 км в пороге» дают разный ответ, и сумма
    минут в Z2 это различие не показывает.
    """
    result = WeekMetrics(week_id=week_id)

    z2_distance = 0.0
    z2_seconds = 0.0
    cadence_sum = 0.0
    cadence_count = 0
    cadence_work_sum = 0.0
    cadence_work_count = 0
    efficiency_sum = 0.0
    efficiency_count = 0
    gap_sum = 0.0
    gap_count = 0
    form_pace_sum = 0.0
    form_pace_count = 0

    # Тренировки в неделе — по дате, от самой старой к самой новой.
    #
    # Порядок задаёт сервер: клиент не знает, что «раньше» в неделе, и
    # не должен решать это своей арифметикой. Даты ISO сортируются
    # лексикографически — «2026-11-08» < «2026-11-09». Тренировка без
    # даты идёт в конец: она не «раньше всех», она неизвестна.
    ordered = sorted(
        per_workout,
        key=lambda m: (m.date is None, m.date or "", m.actual_id),
    )

    for metrics in ordered:
        result.per_workout.append(metrics.as_dict())
        result.z2_min += metrics.z2_min or 0.0
        result.z3_min += metrics.z3_min or 0.0
        result.z4_min += metrics.z4_min or 0.0
        result.hi_min += metrics.hi_min or 0.0
        result.tss += metrics.tss or 0.0
        if metrics.workout_counted:
            result.workouts_counted += 1
        if metrics.pace_z2_sec_per_km and metrics.distance_m:
            z2_seconds += metrics.pace_z2_sec_per_km * (metrics.distance_m / 1000.0)
            z2_distance += metrics.distance_m / 1000.0
        if metrics.cadence_avg:
            cadence_sum += metrics.cadence_avg
            cadence_count += 1
        if metrics.cadence_work:
            cadence_work_sum += metrics.cadence_work
            cadence_work_count += 1
        if metrics.efficiency:
            efficiency_sum += metrics.efficiency
            efficiency_count += 1
        if metrics.pace_gap_sec_per_km is not None:
            gap_sum += metrics.pace_gap_sec_per_km
            gap_count += 1
        if metrics.form_pace_sec_per_km:
            form_pace_sum += metrics.form_pace_sec_per_km
            form_pace_count += 1

    if z2_distance > 0 and z2_seconds > 0:
        result.pace_z2_sec_per_km = z2_seconds / z2_distance
    if cadence_count:
        result.cadence_avg = int(round(cadence_sum / cadence_count))
    if cadence_work_count:
        result.cadence_work = int(round(cadence_work_sum / cadence_work_count))
    if efficiency_count:
        result.efficiency = efficiency_sum / efficiency_count
    # Отставание от темпа по форме: насколько фактический темп медленнее
    # того, что позволяет форма. Знак читается: минус — быстрее формы.
    if gap_count:
        result.pace_gap_sec_per_km = gap_sum / gap_count
    if form_pace_count:
        result.form_pace_sec_per_km = form_pace_sum / form_pace_count

    if vo2max_values:
        result.vo2max = sum(vo2max_values) / len(vo2max_values)

    return result


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _format_pace(sec_per_km: float | None) -> str | None:
    """Темп — «4:38 на километр»."""
    if not sec_per_km or sec_per_km <= 0:
        return None
    total = int(round(sec_per_km))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d} на км"


def estimate_ftp(
    details: list[WorkoutDetail],
) -> float | None:
    """Оценка FTP по фактическим тренировкам.

    FTP — пороговая мощность, а её Garmin не знает: ни в FIT, ни в
    профиле. Её можно **оценить** по данным: у интервальной тренировки
    95-й перцентиль мощности близок к порогу.

    Это оценка, а не измерение, поэтому она **не записывается в
    профиль сама**: пока пользователь не подтвердит значение, нагрузка
    (TSS) не считается. Подставлять выдуманный порог — значит
    показывать правдоподобную цифру, которой никто не мерил.

    Берутся только тренировки с достаточной мощностью: иначе оценка
    уползает вниз на лёгких пробежках.
    """
    values: list[float] = []
    for detail in details:
        power = [float(v) for _, v in detail.series_power if v is not None]
        if len(power) < 100:
            continue
        values.extend(power)
    if not values:
        return None
    values.sort()
    # 95-й перцентиль: максимум занижен пиками, а среднее занижено
    # тем, что в тренировке много лёгкого.
    index = int(len(values) * 0.95)
    return float(values[min(index, len(values) - 1)])


__all__ = [
    "INTENSIVE_ZONES",
    "POWER_ZONES",
    "WeekMetrics",
    "WorkoutMetrics",
    "cadence_in_work",
    "efficiency",
    "estimate_ftp",
    "pace_in_zone",
    "tss_from_power",
    "week_metrics",
    "workout_metrics",
]
