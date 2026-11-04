"""Общие фикстуры для тестов API.

Клиент с чистым хранилищем и без Garmin: Garmin в тестах не нужен —
адаптер ходит в сеть. Источник активностей подменяется заглушкой, и
проверка деградации остаётся быстрой и без внешних зависимостей.

Фикстуры живут здесь, а не в одном из модулей: ими пользуются все
тесты маршрутов, и импорт из модуля приводил к конфликту имён с
параметрами тестов.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    shutil.rmtree(root, ignore_errors=True)
    return root


@pytest.fixture
def client(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Клиент с чистым хранилищем и без Garmin."""
    monkeypatch.setenv("COACH_APP_DATA", str(data_root))

    # Контейнер собирается в lifespan — подмена класса до старта.
    from app.api import dependencies
    from app.main import create_app

    monkeypatch.setattr(dependencies, "GarminActivityPort",
                        dependencies.UnavailableActivityPort)

    with TestClient(create_app()) as test_client:
        yield test_client
