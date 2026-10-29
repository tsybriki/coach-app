"""Точка входа.

Запуск:
    uvicorn app.main:app --host 0.0.0.0 --port 8080

BFF слушает локальную сеть: приложение доступно с телефона в домашнем Wi-Fi.
Авторизации в базе нет (решение от 26.10.2026) — добавим позже.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.dependencies import build_container
from app.api.routes import router

CLIENT_DIR = "client"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Собрать зависимости один раз на процесс."""
    app.state.container = build_container()
    yield


def create_app() -> FastAPI:
    """Собрать приложение."""
    app = FastAPI(
        title="Coach App",
        description="Приложение-тренер: неделя, сезон, план против факта",
        version="0.1.0",
        lifespan=lifespan,
    )

    # PWA живёт на том же порту — один процесс, один адрес
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, object]:
        """Liveness + версия. Без данных."""
        container = app.state.container
        try:
            version = container.season_repo.load().version
        except (ValueError, OSError):
            version = -1
        return {"status": "ok" if version >= 0 else "unhealthy",
                "version": version, "app": "0.1.0"}

    import os

    client_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), CLIENT_DIR)
    if os.path.isdir(client_path):
        app.mount("/", StaticFiles(directory=client_path, html=True), name="client")

    return app


app = create_app()
