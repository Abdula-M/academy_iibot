"""
API для интеграции с мессенджером MAX.

Принимает вебхуки (Update-объекты) от MAX, вызывает логику ИИ
и отправляет ответ обратно через MAX Bot API.

Документация: https://dev.max.ru/docs-api
"""

import logging
import re
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Request, Response, HTTPException
import aiohttp

from common.core.config import settings
from common.database.crud import add_user, log_message, save_vacancy_application
from common.database.session import async_session_factory
from common.services.bot_logic import process_ai_query
from common.services.speech import transcribe_audio

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


def _clean_text_for_max(text: str) -> str:
    """Очистить текст от HTML-тегов и обрезать до лимита MAX."""
    clean_text = re.sub(r"<[^>]+>", "", text)
    if len(clean_text) > 4000:
        clean_text = clean_text[:3970] + "\n\n⚠️ Ответ обрезан."
    return clean_text


# ── Загрузка и отправка фото ─────────────────────────────────

async def _upload_photo_to_max(photo_path: str) -> str | None:
    """Загрузить фото на сервер MAX и получить токен вложения.

    Процесс:
      1. POST /uploads?type=image → получаем upload URL
      2. POST на upload URL с файлом → получаем token
      3. Возвращаем token для использования в attachments

    Returns:
        Токен загруженного изображения или None при ошибке.
    """
    if not settings.max_bot_token:
        logger.error("MAX_BOT_TOKEN не установлен!")
        return None

    session = await _get_http_session()
    token_value = settings.max_bot_token.get_secret_value()
    timeout = aiohttp.ClientTimeout(total=60)

    try:
        # Шаг 1: Получаем URL для загрузки
        async with session.post(
            f"{_MAX_API_BASE}/uploads",
            params={"type": "image"},
            headers={
                "Authorization": token_value,
            },
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка получения upload URL от MAX: %s", error_data)
                return None
            upload_data = await resp.json()
            upload_url = upload_data.get("url")
            if not upload_url:
                logger.error("MAX не вернул upload URL: %s", upload_data)
                return None

        logger.info("Получен upload URL от MAX: %s", upload_url[:80])

        # Шаг 2: Загружаем файл
        file_path = Path(photo_path)
        if not file_path.is_file():
            logger.error("Файл фото не найден: %s", photo_path)
            return None

        data = aiohttp.FormData()
        data.add_field(
            "data",
            open(file_path, "rb"),
            filename=file_path.name,
            content_type="image/jpeg",
        )

        async with session.post(
            upload_url,
            data=data,
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка загрузки фото на MAX: %s", error_data)
                return None
            result = await resp.json()

        # Извлекаем token из ответа
        # MAX возвращает: {"photos": {"<hash>": {"token": "..."}}}
        photo_token = None
        if "token" in result:
            photo_token = result["token"]
        elif "photos" in result and result["photos"]:
            photos = result["photos"]
            if isinstance(photos, dict):
                # Берём token из первого значения словаря
                for _key, value in photos.items():
                    if isinstance(value, dict) and "token" in value:
                        photo_token = value["token"]
                        break
                    elif _key == "token":
                        photo_token = value
                        break

        if not photo_token:
            logger.error("Не удалось извлечь token из ответа MAX: %s", result)
            return None

        logger.info("Фото успешно загружено в MAX, token: %s", photo_token[:30])
        return photo_token

    except Exception as e:
        logger.error("Ошибка при загрузке фото в MAX: %s", e)
        return None


async def send_max_photo(
    user_id: int,
    photo_path: str,
    caption: str | None = None,
) -> bool:
    """Отправить фото пользователю через MAX Bot API.

    Returns:
        True если фото отправлено успешно, False иначе.
    """
    photo_token = await _upload_photo_to_max(photo_path)
    if not photo_token:
        return False

    session = await _get_http_session()
    token_value = settings.max_bot_token.get_secret_value()
    timeout = aiohttp.ClientTimeout(total=30)

    payload: dict = {
        "text": _clean_text_for_max(caption) if caption else None,
        "attachments": [
            {
                "type": "image",
                "payload": {
                    "token": photo_token,
                },
            }
        ],
    }

    try:
        async with session.post(
            f"{_MAX_API_BASE}/messages",
            json=payload,
            headers={
                "Authorization": token_value,
                "Content-Type": "application/json",
            },
            params={"user_id": user_id},
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                error_data = await resp.text()
                logger.error("Ошибка отправки фото в MAX: %s", error_data)
                return False
            logger.info("Фото успешно отправлено в MAX пользователю %d", user_id)
            return True
    except Exception as e:
        logger.error("Не удалось отправить фото в MAX: %s", e)
        return False


# ── Отправка текстового сообщения ────────────────────────────

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
    clean_text = _clean_text_for_max(text)

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


# ── Скачивание голосового сообщения ──────────────────────────

async def _download_max_audio(url: str) -> bytes | None:
    """Скачать аудиофайл по URL от MAX.

    Returns:
        Байты аудиофайла или None при ошибке.
    """
    try:
        session = await _get_http_session()
        timeout = aiohttp.ClientTimeout(total=60)
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                logger.error("Ошибка скачивания аудио из MAX: status=%d", resp.status)
                return None
            return await resp.read()
    except Exception as e:
        logger.error("Не удалось скачать аудио из MAX: %s", e)
        return None


# ── Обработка входящего сообщения ─────────────────────────────

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
                platform="max",
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
                if ai_response.vacancy_application_text:
                    await save_vacancy_application(
                        session,
                        user_id=user_pk,
                        platform_user_id=sender_user_id,
                        platform="max",
                        application_text=ai_response.vacancy_application_text,
                    )
                    logger.info("Заявка на вакансию сохранена (MAX, user=%d)", sender_user_id)
                await session.commit()
        except Exception as e:
            logger.error("Ошибка логирования сообщения MAX: %s", e)

    # Отправляем ответ с фото или без
    if ai_response.photo_path is not None:
        # Пробуем отправить фото с подписью
        photo_sent = await send_max_photo(
            sender_user_id,
            ai_response.photo_path,
            caption=ai_response.text,
        )
        if not photo_sent:
            # Если фото не удалось отправить — отправляем просто текст
            logger.warning("Фото не удалось отправить, отправляем только текст")
            await send_max_message(sender_user_id, ai_response.text)
    else:
        # Обычный текстовый ответ
        await send_max_message(sender_user_id, ai_response.text)


async def _handle_max_voice(sender_user_id: int, audio_url: str) -> None:
    """Фоновая задача обработки голосового сообщения MAX."""

    # Скачиваем аудио
    audio_data = await _download_max_audio(audio_url)
    if not audio_data:
        await send_max_message(
            sender_user_id,
            "Извините, не удалось получить ваше голосовое сообщение. "
            "Пожалуйста, напишите текстом.",
        )
        return

    # Транскрибируем через Groq Whisper
    transcribed_text = await transcribe_audio(audio_data)
    if not transcribed_text:
        await send_max_message(
            sender_user_id,
            "Извините, я не смог разобрать ваше голосовое сообщение. "
            "Пожалуйста, напишите текстом или запишите ещё раз.",
        )
        return

    logger.info(
        "Голосовое сообщение MAX (user=%d) распознано: '%s'",
        sender_user_id,
        transcribed_text[:50],
    )

    # Обрабатываем распознанный текст как обычное сообщение
    await _handle_max_message(sender_user_id, transcribed_text)


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

        # Проверяем наличие вложений (голосовые, аудио)
        attachments = message_body.get("attachments", [])

        if sender_user_id:
            # Проверяем, есть ли голосовое/аудио вложение
            audio_url = None
            for attachment in attachments:
                att_type = attachment.get("type", "")
                if att_type in ("audio", "voice"):
                    # Извлекаем URL аудио
                    payload = attachment.get("payload", {})
                    audio_url = payload.get("url")
                    break

            if audio_url:
                # Голосовое сообщение
                background_tasks.add_task(
                    _handle_max_voice,
                    int(sender_user_id),
                    audio_url,
                )
            elif text:
                # Текстовое сообщение
                background_tasks.add_task(
                    _handle_max_message,
                    int(sender_user_id),
                    text,
                )

    # MAX требует HTTP 200 в течение 30 секунд
    return Response(content="OK", status_code=200)
