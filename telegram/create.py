"""
Фабрика экземпляров Bot и Dispatcher.

Вынесена отдельно, чтобы main.py и хендлеры не зависели друг от друга
и могли импортировать готовые объекты без циклических зависимостей.
"""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from common.core.config import settings

# ── FSM-хранилище в Redis ────────────────────────────────────
storage = RedisStorage.from_url(settings.redis_url)

# ── Настройка сессии и прокси ────────────────────────────────
session = None
if settings.telegram_api_server or settings.telegram_proxy:
    api_server = (
        TelegramAPIServer.from_base(settings.telegram_api_server)
        if settings.telegram_api_server
        else TelegramAPIServer.from_base("https://api.telegram.org")
    )
    session = AiohttpSession(
        api=api_server,
        proxy=settings.telegram_proxy or None,
    )

# ── Экземпляр бота ───────────────────────────────────────────
bot = Bot(
    token=settings.bot_token.get_secret_value(),
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

# ── Диспетчер ────────────────────────────────────────────────
dp = Dispatcher(storage=storage)
