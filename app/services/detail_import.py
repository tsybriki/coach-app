"""Импорт разбора FIT — по одной тренировке и по пачке.

**Разбор — часть выкачки факта.** Пользователь жмёт «Загрузить факт из
Garmin» и получает не только факт, но и разбор: без разбора нет
метрик формы (зоны пульса, темп в зоне, нагрузка, каденция).

Разбор дорогой — несколько секунд на файл, — поэтому он делается
один раз: результат лежит в `DetailRepo`, а метрики считаются из него.

Разбор не может сорвать выкачку: если FIT-файла нет или он не
разобрался, тренировка просто остаётся без метрик. Факт важнее
разбора.
"""
from __future__ import annotations

from app.domain.entities import ActualSession
from app.ports.storage import AthleteRepo, DetailRepo, FactRepo, FitPort


class DetailImporter:
    """Разбор FIT-файлов активностей Garmin."""

    def __init__(
        self,
        fit_port: FitPort,
        detail_repo: DetailRepo,
        fact_repo: FactRepo,
        athlete_repo: AthleteRepo,
    ) -> None:
        self._fit_port = fit_port
        self._detail_repo = detail_repo
        self._fact_repo = fact_repo
        self._athlete_repo = athlete_repo

    def import_one(self, actual_id: str) -> bool:
        """Разобрать FIT по факту. True — разбор есть.

        False — разбора нет (файла нет, не разобрался). Это не ошибка:
        тренировка остаётся в факте, просто без метрик.
        """
        from app.adapters.fit import parse_fit

        existing = self._detail_repo.detail(actual_id)
        if existing is not None:
            return True

        session = self._fact(actual_id)
        if session is None or not session.external_id:
            return False

        fit_path = self._fit_port.fit_path_for(session.external_id)
        if fit_path is None:
            return False

        athlete = self._athlete_repo.get()
        try:
            detail = parse_fit(
                fit_path,
                hr_max=athlete.hr_max or 182,
                zones=athlete.hr_zones or None,
            )
        except Exception:  # noqa: BLE001 — разбор не должен сорвать выкачку
            return False

        detail.actual_id = actual_id
        self._detail_repo.save_detail(detail)
        return True

    def import_many(self, sessions: list[ActualSession]) -> dict[str, int]:
        """Разобрать все тренировки пачки.

        Возвращает счётчики: сколько разобрано, сколько пропущено.
        """
        imported = 0
        skipped = 0
        for session in sessions:
            if self.import_one(session.id):
                imported += 1
            else:
                skipped += 1
        return {"imported": imported, "skipped": skipped}

    def _fact(self, actual_id: str) -> ActualSession | None:
        """Факт по id — порт факта передаётся снаружи."""
        return self._fact_repo.get(actual_id) if self._fact_repo else None


__all__ = ["DetailImporter"]
