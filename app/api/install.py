"""Публичные маршруты установки на телефон.

Отдельный роутер без префикса `/api/v1`: ссылка на сертификат должна быть
короткой и запоминающейся — её телефон открывает руками.

Маршрут `/ca.crt` отдаёт корневой CA локального сертификата. Телефон
скачивает его по HTTP (обычный HTTP для скачивания и годится) и ставит
как «сертификат CA пользователя». После этого Chrome доверяет
HTTPS-адресу приложения и предлагает «Установить приложение».

Сам сертификат лежит в каталоге данных, а не в репозитории: приватный
ключ CA в git попадать не должен. Файл читает адаптер хранилища — прямой
доступ к диску из BFF нарушал бы слои.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.dependencies import AppContainer, get_container

router = APIRouter()


@router.get("/ca.crt")
def ca_certificate(
    container: AppContainer = Depends(get_container),
) -> Response:
    """Корневой CA для установки на телефоне."""
    content = container.storage.ca_certificate()
    if content is None:
        return Response(
            content="сертификат CA не найден",
            status_code=404,
            media_type="text/plain; charset=utf-8",
        )
    return Response(
        content=content,
        media_type="application/x-x509-ca-cert",
        headers={
            # Имя файла при скачивании — чтобы Android сохранил его как
            # сертификат, а не как текст.
            "Content-Disposition": 'attachment; filename="coach-app-ca.crt"',
            "Cache-Control": "no-cache",
        },
    )
