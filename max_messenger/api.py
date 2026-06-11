"""
API для интеграции с мессенджером MAX.

Принимает вебхуки (Update-объекты) от MAX, вызывает логику ИИ
и отправляет ответ обратно через MAX Bot API.

Документация: https://dev.max.ru/docs-api
"""

import logging
import re
from fastapi import APIRouter, BackgroundTasks, Request, Response, HTTPException
import aiohttp

from common.core.config import settings
from common.database.crud import add_user, log_message
from common.database.session import async_session_factory
from common.services.bot_logic import process_ai_query

logger = logging.getLogger(__name__)

max_router = APIRouter(prefix="/api/max", tags=["max"])

# In-memory хранилище состояний для пользователей MAX.
# Структура: { user_id: {"history": [...], "sent_photos": set()} }
_user_states: dict[int, dict] = {}

# Глобальная сессия aiohttp для переиспользования
_http_session: aiohttp.ClientSession | None = None

# ── Базовый URL MAX Bot API ──────────────────────────────────
_MAX_API_BASE = "https://platform-api.max.ru"


async def _get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


def _get_auth_headers() -> dict[str, str]:
    """Заголовки авторизации для MAX Bot API.

    Формат: Authorization: <token> (без Bearer).
    """
    if not settings.max_bot_token:
        return {}
    return {
        "Authorization": settings.max_bot_token.get_secret_value(),
        "Content-Type": "application/json",
    }


async def send_max_message(user_id: int, text: str) -> None:
    """Отправка текстового сообщения пользователю через MAX Bot API.

    POST https://platform-api.max.ru/messages?user_id={user_id}
    Body: {"text": "...", "attachments": []}
    """
    if not settings.max_bot_token:
        logger.error("MAX_BOT_TOKEN не установлен! Ответ не будет отправлен.")
        return

    url = f"{_MAX_API_BASE}/messages"
    headers = _get_auth_headers()

    # MAX не поддерживает HTML-теги — убираем
    clean_text = re.sub(r"<[^>]+>", "", text)

    # Обрезаем до лимита MAX (4000 символов)
    if len(clean_text) > 4000:
        clean_text = clean_text[:3970] + "\n\n⚠️ Ответ обрезан."

    payload = {
        "text": clean_text,
        "attachments": [],
    }

    try:
        session = await _get_http_session()
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(
            url,
            json=payload,
            headers=headers,
            params={"user_id": user_id},
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка при отправке сообщения в MAX: %s", error_data)
            else:
                logger.info("Ответ успешно отправлен в MAX пользователю %d", user_id)
    except Exception as e:
        logger.error("Не удалось подключиться к MAX API: %s", e)


async def _handle_max_message(sender_user_id: int, text: str) -> None:
    """Фоновая задача обработки сообщения MAX."""

    # Сохраняем пользователя в БД
    user_pk = None
    try:
        async with async_session_factory() as session:
            user = await add_user(
                session,
                telegram_id=sender_user_id,
                username=f"max_{sender_user_id}",
            )
            await session.commit()
            user_pk = user.id
    except Exception as e:
        logger.error("Ошибка сохранения пользователя MAX: %s", e)

    # Загружаем состояние
    state = _user_states.get(sender_user_id, {"history": [], "sent_photos": set()})

    # Вызываем AI логику
    ai_response, updated_history, updated_photos = await process_ai_query(
        user_query=text,
        user_id=sender_user_id,
        history=state["history"],
        sent_photos=state["sent_photos"],
    )

    # Сохраняем состояние
    _user_states[sender_user_id] = {
        "history": updated_history,
        "sent_photos": updated_photos,
    }

    # Логируем сообщение
    if user_pk is not None:
        try:
            async with async_session_factory() as session:
                await log_message(
                    session,
                    user_id=user_pk,
                    telegram_id=sender_user_id,
                    question=text,
                    answer=ai_response.text,
                )
                await session.commit()
        except Exception as e:
            logger.error("Ошибка логирования сообщения MAX: %s", e)

    # Отправляем ответ
    await send_max_message(sender_user_id, ai_response.text)


@max_router.post("/webhook")
async def max_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    """Прием входящих Update-объектов от мессенджера MAX.

    MAX отправляет POST-запросы с объектом Update на указанный webhook URL.
    Формат Update:
      {
        "update_type": "message_created",
        "timestamp": 1234567890,
        "message": {
          "sender": {"user_id": 123, "name": "Имя"},
          "body": {"text": "Привет"},
          "recipient": {"chat_id": 456}
        }
      }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    update_type = body.get("update_type")

    # Обрабатываем только событие создания сообщения
    if update_type == "message_created":
        message = body.get("message", {})
        sender = message.get("sender", {})
        sender_user_id = sender.get("user_id")
        message_body = message.get("body", {})
        text = message_body.get("text")

        if sender_user_id and text:
            background_tasks.add_task(
                _handle_max_message,
                int(sender_user_id),
                text,
            )

    # MAX требует HTTP 200 в течение 30 секунд
    return Response(content="OK", status_code=200)
