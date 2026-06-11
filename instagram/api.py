import logging
import re
from pathlib import Path
import urllib.parse

from fastapi import APIRouter, BackgroundTasks, Request, Response, HTTPException
from fastapi.responses import FileResponse
import aiohttp

from common.core.config import settings
from common.database.crud import add_user, get_user_by_telegram_id, log_message
from common.database.session import async_session_factory
from common.services.bot_logic import process_ai_query
from common.services.speech import transcribe_audio

logger = logging.getLogger(__name__)

instagram_router = APIRouter(prefix="/api/instagram", tags=["instagram"])

# In-memory хранилище состояний для пользователей Instagram.
# Структура: { user_id: {"history": [...], "sent_photos": set()} }
_user_states: dict[int, dict] = {}

# Глобальная сессия aiohttp для переиспользования
_http_session: aiohttp.ClientSession | None = None

# Базовая директория с данными (фото, документы)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


def _get_graph_base_url() -> str:
    """Определяет базовый URL Graph API в зависимости от типа токена.

    IGAA-токены (Instagram Login) → graph.instagram.com
    EAA-токены (Page Access Token) → graph.facebook.com
    """
    if not settings.instagram_access_token:
        return "https://graph.facebook.com"
    token = settings.instagram_access_token.get_secret_value()
    if token.startswith("IGAA"):
        return "https://graph.instagram.com"
    return "https://graph.facebook.com"


def _get_public_file_url(file_path: str) -> str:
    """Формирует публичный URL для файла, доступный из интернета.

    Файлы раздаются через эндпоинт /api/instagram/media/<filename>.
    """
    filename = Path(file_path).name
    # Кодируем имя файла для URL (пробелы -> %20, кириллица -> %D0...)
    encoded_filename = urllib.parse.quote(filename)
    
    # Определяем поддиректорию (photos или корень data)
    path_obj = Path(file_path)
    if "photos" in path_obj.parts:
        return f"https://academy-skfo.online/api/instagram/media/photos/{encoded_filename}"
    return f"https://academy-skfo.online/api/instagram/media/{encoded_filename}"


# ── Эндпоинт для раздачи медиафайлов ────────────────────────────
@instagram_router.get("/media/photos/{filename}")
async def serve_photo(filename: str):
    """Раздача фотографий для Instagram API."""
    file_path = _DATA_DIR / "photos" / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@instagram_router.get("/media/{filename}")
async def serve_media(filename: str):
    """Раздача документов (PDF и др.) для Instagram API."""
    file_path = _DATA_DIR / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


# ── Верификация Webhook ──────────────────────────────────────────
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


# ── Отправка текстового сообщения ────────────────────────────────
async def send_instagram_message(recipient_id: str, text: str):
    """Отправка текстового сообщения пользователю через Graph API."""
    if not settings.instagram_access_token:
        logger.error("INSTAGRAM_ACCESS_TOKEN не установлен! Ответ не будет отправлен.")
        return

    base_url = _get_graph_base_url()
    token = settings.instagram_access_token.get_secret_value()
    url = f"{base_url}/v25.0/me/messages?access_token={token}"
    
    # Форматирование текста (Instagram не поддерживает HTML теги)
    ig_text = text
    ig_text = re.sub(r'<[^>]+>', '', ig_text)  # удаляем HTML теги
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": ig_text}
    }
    
    logger.info("Отправка сообщения в Instagram через %s (токен: %s...)", base_url, token[:10])

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


# ── Отправка изображения ─────────────────────────────────────────
async def send_instagram_image(recipient_id: str, image_path: str):
    """Отправка изображения пользователю через Graph API по публичному URL."""
    if not settings.instagram_access_token:
        return

    base_url = _get_graph_base_url()
    token = settings.instagram_access_token.get_secret_value()
    url = f"{base_url}/v25.0/me/messages?access_token={token}"

    image_url = _get_public_file_url(image_path)

    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {
                    "url": image_url
                }
            }
        }
    }

    logger.info("Отправка фото в Instagram: %s", image_url)

    try:
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка при отправке фото в Instagram: %s", error_data)
            else:
                logger.info("Фото успешно отправлено в Instagram пользователю %s", recipient_id)
    except Exception as e:
        logger.error("Не удалось отправить фото в Instagram: %s", e)


# ── Отправка документа (PDF) ──────────────────────────────────────
async def send_instagram_document(recipient_id: str, document_path: str):
    """Отправка документа пользователю через Graph API.

    Instagram поддерживает файлы как attachment типа 'file'.
    """
    if not settings.instagram_access_token:
        return

    base_url = _get_graph_base_url()
    token = settings.instagram_access_token.get_secret_value()
    url = f"{base_url}/v25.0/me/messages?access_token={token}"

    file_url = _get_public_file_url(document_path)

    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "file",
                "payload": {
                    "url": file_url
                }
            }
        }
    }

    logger.info("Отправка документа в Instagram: %s", file_url)

    try:
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка при отправке документа в Instagram: %s", error_data)
            else:
                logger.info("Документ успешно отправлен в Instagram пользователю %s", recipient_id)
    except Exception as e:
        logger.error("Не удалось отправить документ в Instagram: %s", e)


# ── Получение профиля пользователя ────────────────────────────────
async def get_instagram_profile(sender_id: str) -> str | None:
    """Получает username пользователя Instagram по его ID через Graph API."""
    if not settings.instagram_access_token:
        return None
    base_url = _get_graph_base_url()
    token = settings.instagram_access_token.get_secret_value()
    url = f"{base_url}/v25.0/{sender_id}?fields=username,name&access_token={token}"
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


# ── Обработка входящего сообщения ─────────────────────────────────
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
    
    # Отправляем текстовый ответ
    await send_instagram_message(sender_id, ai_response.text)

    # Отправляем фото, если есть
    if ai_response.photo_path is not None:
        await send_instagram_image(sender_id, ai_response.photo_path)

    # Отправляем документ (PDF), если есть
    if ai_response.document_path is not None:
        await send_instagram_document(sender_id, ai_response.document_path)


async def _download_instagram_audio(audio_url: str) -> bytes | None:
    """Скачивает аудиофайл по URL из вебхука Instagram."""
    try:
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(audio_url, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.error("Не удалось скачать аудио из Instagram: HTTP %s", resp.status)
    except Exception as e:
        logger.error("Ошибка при скачивании аудио из Instagram: %s", e)
    return None


async def _handle_instagram_voice(sender_id: str, audio_url: str):
    """Обработка голосового сообщения Instagram: скачивание → STT → AI → ответ."""
    # Скачиваем аудио
    audio_bytes = await _download_instagram_audio(audio_url)
    if audio_bytes is None:
        await send_instagram_message(sender_id, "⚠️ Не удалось обработать голосовое сообщение.")
        return

    # Распознаём речь через Groq Whisper
    transcribed_text = await transcribe_audio(audio_bytes)
    if not transcribed_text:
        await send_instagram_message(sender_id, "⚠️ Не удалось распознать голосовое сообщение. Попробуйте написать текстом.")
        return

    logger.info("Instagram голосовое распознано: '%s'", transcribed_text[:80])

    # Обрабатываем как обычное текстовое сообщение
    await _handle_instagram_message(sender_id, transcribed_text)


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

                if not sender_id:
                    continue

                # Текстовое сообщение
                text = message.get("text")
                if text:
                    background_tasks.add_task(_handle_instagram_message, sender_id, text)
                    continue

                # Голосовое / аудио сообщение
                attachments = message.get("attachments", [])
                for att in attachments:
                    if att.get("type") == "audio":
                        audio_url = att.get("payload", {}).get("url")
                        if audio_url:
                            background_tasks.add_task(_handle_instagram_voice, sender_id, audio_url)
                            break
                    
        return Response(content="EVENT_RECEIVED", status_code=200)
    else:
        raise HTTPException(status_code=404, detail="Not Found")

