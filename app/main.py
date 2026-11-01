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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.staticfiles import PathLike
from starlette.types import Scope

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

    # Сжатие: без него клиент тянет 53 КБ JS и 24 КБ CSS открытым текстом.
    # На мобильном канале это заметная задержка первого открытия.
    # Минимальный порог — 1 КБ, чтобы не сжимать мелкие ответы.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

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
        # Статика — с запретом кэширования.
        #
        # Без этого заголовка телефон по обычному HTTP (service worker
        # работает только на HTTPS) держит браузерный кэш и показывает
        # старую версию клиента: правка в коде есть, а на экране её нет.
        # Версию кэша оболочки service worker'а это не чинит — он на телефоне
        # не регистрируется.
        #
        # `no-cache` — не «не хранить», а «уточни у сервера перед
        # использованием»: ETag и Last-Modified остаются, трафик не растёт.
        class NoCacheStaticFiles(StaticFiles):
            def file_response(
                self,
                full_path: PathLike,
                stat_result: os.stat_result,
                scope: Scope,
                status_code: int = 200,
            ) -> Response:
                response = super().file_response(
                    full_path, stat_result, scope, status_code)
                response.headers["Cache-Control"] = "no-cache"
                return response

        app.mount("/", NoCacheStaticFiles(directory=client_path, html=True),
                  name="client")

    return app


app = create_app()
