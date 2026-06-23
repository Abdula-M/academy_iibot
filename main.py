"""
Точка входа — FastAPI-приложение + Telegram-бот.

Поддерживает два режима:
  • USE_WEBHOOK=true  → FastAPI + Webhook (продакшен)
  • USE_WEBHOOK=false → Polling (локальное тестирование)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from telegram.create import bot, dp
from telegram.handlers.user import router as user_router
from whatsapp.api import whatsapp_router
from instagram.api import instagram_router
from max_messenger.api import max_router
from common.core.config import settings
from common.database.crud import (
    get_dashboard_stats,
    get_messages_by_user,
    get_recent_messages,
    get_users_list,
    get_vacancy_applications,
    mark_messages_read,
    mark_vacancy_application_read,
    get_unread_applications_count,
)
from common.database.models import Base
from common.database.session import async_engine, async_session_factory

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ── Регистрация роутеров ─────────────────────────────────────
dp.include_router(user_router)


# ── Создание таблиц в БД ────────────────────────────────────
async def _create_tables() -> None:
    """Создать таблицы, если они не существуют."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Таблицы БД проверены / созданы.")


# ── Lifespan (startup / shutdown) ────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения."""

    # Создание таблиц при старте
    await _create_tables()

    if settings.use_webhook:
        # ── Webhook mode ─────────────────────────────────────
        webhook_full_url = f"{settings.webhook_url}{settings.webhook_path}"
        await bot.set_webhook(
            url=webhook_full_url,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
        )
        logger.info("Webhook установлен: %s", webhook_full_url)

        yield

        await bot.delete_webhook()
        logger.info("Webhook удалён.")
    else:
        # ── Polling mode ─────────────────────────────────────
        await bot.delete_webhook(drop_pending_updates=True)
        polling_task = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False),
        )
        logger.info("Polling запущен.")

        yield

        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        logger.info("Polling остановлен.")

    await bot.session.close()
    logger.info("Сессия бота закрыта.")


# ── FastAPI-приложение ───────────────────────────────────────
app = FastAPI(title="AI Bot + Dashboard API", lifespan=lifespan)

# CORS для локальной разработки фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(whatsapp_router)
app.include_router(instagram_router)
app.include_router(max_router)


# ── Webhook endpoint (работает только в webhook-режиме) ──────
@app.post(settings.webhook_path)
async def webhook_handler(request: Request) -> dict[str, bool]:
    """Приём Update от Telegram и передача в aiogram Dispatcher."""
    update_data = await request.json()
    update = Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)
    return {"ok": True}


# ── Health-check ─────────────────────────────────────────────
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Простая проверка работоспособности сервера."""
    return {"status": "healthy"}


# ── API Endpoints ──────────────────────────────────────────────


@app.get("/api/stats")
async def api_stats() -> dict[str, int]:
    """JSON-статистика: total_users, today_users, today_messages, unread_applications."""
    async with async_session_factory() as session:
        stats = await get_dashboard_stats(session)
        unread_apps = await get_unread_applications_count(session)
        stats["unread_applications"] = unread_apps
        return stats


@app.get("/api/messages")
async def api_messages() -> list[dict[str, str]]:
    """Список последних диалогов."""
    async with async_session_factory() as session:
        return await get_recent_messages(session, limit=100)


@app.get("/api/users")
async def api_users(
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Список пользователей с пагинацией для сайдбара."""
    async with async_session_factory() as session:
        return await get_users_list(session, offset=offset, limit=limit)


@app.get("/api/messages/{telegram_id}")
async def api_messages_user(
    telegram_id: int,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """История переписки с конкретным пользователем (с пагинацией)."""
    async with async_session_factory() as session:
        # Помечаем сообщения как прочитанные при открытии диалога
        if offset == 0:
            await mark_messages_read(session, telegram_id)
        return await get_messages_by_user(session, telegram_id=telegram_id, offset=offset, limit=limit)


@app.get("/api/vacancy-applications")
async def api_vacancy_applications(
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Получить список заявок на вакансии с пагинацией."""
    async with async_session_factory() as session:
        return await get_vacancy_applications(session, offset=offset, limit=limit)


@app.post("/api/vacancy-applications/{application_id}/read")
async def api_vacancy_read(application_id: int) -> dict[str, bool]:
    """Пометить заявку на вакансию как прочитанную."""
    async with async_session_factory() as session:
        await mark_vacancy_application_read(session, application_id)
        return {"ok": True}
