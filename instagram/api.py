import logging
import re
from fastapi import APIRouter, BackgroundTasks, Request, Response, HTTPException
import aiohttp

from common.core.config import settings
from common.database.crud import add_user, get_user_by_telegram_id, log_message
from common.database.session import async_session_factory
from common.services.bot_logic import process_ai_query

logger = logging.getLogger(__name__)

instagram_router = APIRouter(prefix="/api/instagram", tags=["instagram"])

# In-memory хранилище состояний для пользователей Instagram.
# Структура: { user_id: {"history": [...], "sent_photos": set()} }
_user_states: dict[int, dict] = {}

# Глобальная сессия aiohttp для переиспользования
_http_session: aiohttp.ClientSession | None = None

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


@instagram_router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Эндпоинт для верификации Webhook от Meta.
    Meta отправляет GET-запрос с параметрами hub.mode, hub.verify_token и hub.challenge.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == settings.instagram_verify_token:
            logger.info("Instagram Webhook verified!")
            return Response(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Forbidden")
    return Response(content="Hello", status_code=200)


async def send_instagram_message(recipient_id: str, text: str):
    """
    Отправка сообщения обратно пользователю через Graph API.
    """
    if not settings.instagram_access_token:
        logger.error("INSTAGRAM_ACCESS_TOKEN не установлен! Ответ не будет отправлен.")
        return
        
    url = f"https://graph.facebook.com/v22.0/me/messages?access_token={settings.instagram_access_token.get_secret_value()}"
    
    # Форматирование текста (Instagram не поддерживает HTML теги)
    ig_text = text
    ig_text = re.sub(r'<[^>]+>', '', ig_text) # удаляем HTML теги
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": ig_text}
    }
    
    try:
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка при отправке сообщения в Instagram: %s", error_data)
            else:
                logger.info("Ответ успешно отправлен в Instagram пользователю %s", recipient_id)
    except Exception as e:
        logger.error("Не удалось подключиться к Meta API: %s", e)


async def get_instagram_profile(sender_id: str) -> str | None:
    """Получает username пользователя Instagram по его ID через Graph API."""
    if not settings.instagram_access_token:
        return None
    url = f"https://graph.facebook.com/v22.0/{sender_id}?fields=username,name&access_token={settings.instagram_access_token.get_secret_value()}"
    try:
        session = await get_http_session()
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                username = data.get("username")
                if not username:
                    username = data.get("name")
                return username
            else:
                error_data = await resp.text()
                logger.error("Ошибка получения профиля Instagram для %s: %s", sender_id, error_data)
    except Exception as e:
        logger.error("Исключение при получении профиля Instagram для %s: %s", sender_id, e)
    return None


async def _handle_instagram_message(sender_id: str, text: str):
    """Фоновая задача обработки сообщения Instagram."""
    # Для Instagram ID (PSID/IGSID) — это большая строка из цифр.
    # Преобразуем ее в int, чтобы она поместилась в telegram_id (BigInt в базе).
    try:
        user_id = int(sender_id)
    except ValueError:
        logger.warning("Некорректный sender_id: %s", sender_id)
        return
        
    # Сохраняем пользователя в БД
    user_pk = None
    try:
        async with async_session_factory() as session:
            # Сначала проверим, есть ли уже пользователь с нормальным юзернеймом
            user = await get_user_by_telegram_id(session, user_id)
            default_ig_name = f"ig_{sender_id}"
            
            if not user or user.username == default_ig_name or not user.username:
                profile_name = await get_instagram_profile(sender_id)
                username_str = profile_name if profile_name else default_ig_name
            else:
                username_str = user.username
                
            user = await add_user(session, telegram_id=user_id, username=username_str)
            await session.commit()
            user_pk = user.id
    except Exception as e:
        logger.error("Ошибка сохранения пользователя Instagram: %s", e)

    # Загружаем состояние
    state = _user_states.get(user_id, {"history": [], "sent_photos": set()})
    
    # Вызываем AI логику
    ai_response, updated_history, updated_photos = await process_ai_query(
        user_query=text,
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
            async with async_session_factory() as session:
                await log_message(session, user_id=user_pk, telegram_id=user_id, question=text, answer=ai_response.text)
                await session.commit()
        except Exception as e:
            logger.error("Ошибка логирования сообщения Instagram: %s", e)
    
    # Отправляем ответ
    await send_instagram_message(sender_id, ai_response.text)


@instagram_router.post("/webhook")
async def instagram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Прием входящих сообщений от Meta (Instagram)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
        
    # Проверяем, что это запрос от Instagram
    if body.get("object") == "instagram":
        for entry in body.get("entry", []):
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                message = messaging_event.get("message", {})
                
                # Игнорируем эхо-сообщения
                if message.get("is_echo"):
                    continue
                    
                text = message.get("text")
                
                if sender_id and text:
                    background_tasks.add_task(_handle_instagram_message, sender_id, text)
                    
        return Response(content="EVENT_RECEIVED", status_code=200)
    else:
        raise HTTPException(status_code=404, detail="Not Found")
