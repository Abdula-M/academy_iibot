"""
API для интеграции с микросервисом WhatsApp.

Принимает вебхуки от Node.js сервиса, вызывает логику ИИ
и отправляет ответ обратно в Node.js сервис.
"""

import base64
import logging
import re

import aiohttp
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from common.core.config import settings
from common.database.crud import add_user
from common.database.session import async_session_factory
from common.services.bot_logic import process_ai_query
from common.services.speech import transcribe_audio

logger = logging.getLogger(__name__)

whatsapp_router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# In-memory хранилище состояний для пользователей WhatsApp.
# В продакшене лучше использовать Redis.
# Структура: { 79929000054: {"history": [...], "sent_photos": set()} }
_user_states: dict[int, dict] = {}

# Глобальная сессия aiohttp для переиспользования
_http_session: aiohttp.ClientSession | None = None

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session

# URL Node.js сервиса
WHATSAPP_SERVICE_URL = settings.whatsapp_service_url


class WhatsAppMessage(BaseModel):
    chat_id: str   # Например, "79929000054@c.us"
    text: str
    sender_name: str | None = None
    audio_base64: str | None = None


async def _handle_whatsapp_message(msg: WhatsAppMessage):
    """Фоновая задача обработки сообщения WhatsApp."""
    # Извлекаем номер телефона как integer
    phone_str = msg.chat_id.split("@")[0]
    if not phone_str.isdigit():
        logger.warning("Некорректный chat_id: %s", msg.chat_id)
        return
        
    user_id = int(phone_str)
    
    # Сохраняем/обновляем пользователя в БД (используем номер как telegram_id)
    username = msg.sender_name or f"wa_{phone_str}"
    user_pk = None
    try:
        async with async_session_factory() as session:
            user = await add_user(session, telegram_id=user_id, username=username, platform="whatsapp")
            await session.commit()
            user_pk = user.id
    except Exception as e:
        logger.error("Ошибка сохранения пользователя WhatsApp: %s", e)

    # Загружаем состояние
    state = _user_states.get(user_id, {"history": [], "sent_photos": set()})
    
    user_query = msg.text
    
    # Обработка аудио
    if msg.audio_base64:
        try:
            audio_bytes = base64.b64decode(msg.audio_base64)
            transcribed_text = await transcribe_audio(audio_bytes)
            if transcribed_text:
                user_query = transcribed_text
            else:
                user_query = "Извините, я не смог разобрать ваше голосовое сообщение."
        except Exception as e:
            logger.error("Ошибка при обработке аудиосообщения в WhatsApp: %s", e)
            user_query = "Извините, произошла ошибка при обработке вашего голосового сообщения."
            
    if not user_query:
        return
    
    # Вызываем AI логику
    ai_response, updated_history, updated_photos = await process_ai_query(
        user_query=user_query,
        user_id=user_id,
        history=state["history"],
        sent_photos=state["sent_photos"],
    )
    
    # Сохраняем состояние
    _user_states[user_id] = {
        "history": updated_history,
        "sent_photos": updated_photos
    }
    
    # Логируем сообщение
    if user_pk is not None:
        try:
            from common.database.crud import log_message, save_vacancy_application
            async with async_session_factory() as session:
                await log_message(session, user_id=user_pk, telegram_id=user_id, question=user_query, answer=ai_response.text)
                if ai_response.vacancy_application_text:
                    await save_vacancy_application(
                        session,
                        user_id=user_pk,
                        platform_user_id=user_id,
                        platform="whatsapp",
                        application_text=ai_response.vacancy_application_text,
                    )
                    logger.info("Заявка на вакансию сохранена (WhatsApp, user=%d)", user_id)
                await session.commit()
        except Exception as e:
            logger.error("Ошибка логирования сообщения: %s", e)
    
    # Отправляем ответ в Node.js микросервис
    try:
        session = await get_http_session()
        # Преобразуем HTML теги из ответа ИИ в формат WhatsApp
        wa_text = ai_response.text
        wa_text = wa_text.replace('<b>', '*').replace('</b>', '*')
        wa_text = wa_text.replace('<strong>', '*').replace('</strong>', '*')
        wa_text = wa_text.replace('<i>', '_').replace('</i>', '_')
        wa_text = wa_text.replace('<em>', '_').replace('</em>', '_')
        wa_text = wa_text.replace('<br>', '\n').replace('</br>', '\n')
        wa_text = re.sub(r'<[^>]+>', '', wa_text)  # Удаляем остальные теги

        payload = {
            "chat_id": msg.chat_id,
            "text": wa_text,
        }
        # Передаем абсолютный путь к медиа (Node.js прочитает и отправит)
        if ai_response.photo_path:
            payload["media_path"] = ai_response.photo_path
        elif getattr(ai_response, "document_path", None):
            payload["media_path"] = ai_response.document_path

        # Добавляем таймаут
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(WHATSAPP_SERVICE_URL, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error("Ошибка при отправке в WhatsApp сервис: %s", error_text)
    except Exception as e:
        logger.error("Не удалось подключиться к WhatsApp сервису: %s", e)


@whatsapp_router.post("/webhook")
async def whatsapp_webhook(msg: WhatsAppMessage, background_tasks: BackgroundTasks):
    """Эндпоинт для входящих сообщений из WhatsApp."""
    background_tasks.add_task(_handle_whatsapp_message, msg)
    return {"status": "ok"}


@whatsapp_router.get("/status")
async def get_whatsapp_status():
    """Проксирует запрос статуса к Node.js микросервису."""
    try:
        status_url = WHATSAPP_SERVICE_URL.replace("/send", "/status")
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=3)
        async with session.get(status_url, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
            return {"status": "ERROR", "qr": ""}
    except Exception as e:
        logger.error("Ошибка при получении статуса WhatsApp: %s", e)
        return {"status": "OFFLINE", "qr": ""}

@whatsapp_router.post("/logout")
async def logout_whatsapp() -> dict[str, bool]:
    """Проксирует запрос на отвязку (разлогин) к микросервису WhatsApp."""
    try:
        logout_url = WHATSAPP_SERVICE_URL.replace("/send", "/logout")
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.post(logout_url, timeout=timeout) as resp:
            return await resp.json()
    except Exception as e:
        logger.warning("WhatsApp service logout недоступен: %s", e)
        return {"success": False}
