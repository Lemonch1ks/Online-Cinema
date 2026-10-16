"""Точка входа приложения.

Запуск:  poetry run fastapi dev app/main.py
Документация (Swagger): http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from app.config import settings
from app.routers import movies

app = FastAPI(title=settings.app_name)

app.include_router(movies.router)


@app.get("/health", tags=["service"])
def health():
    """Простая проверка, что сервер запущен."""
    return {"status": "ok"}
