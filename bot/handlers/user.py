"""
Хендлеры пользовательских команд.

Каждый хендлер — тонкий: принимает update, делегирует логику
в CRUD / сервисный слой и возвращает ответ.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from database.crud import add_user, log_message
from database.session import async_session_factory
from services.bot_logic import process_ai_query
from services.speech import transcribe_audio


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создать красивую реплай-клавиатуру для главного меню."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🎓 Направления обучения"))
    builder.row(
        KeyboardButton(text="💰 Стоимость и сроки"),
        KeyboardButton(text="📅 Сроки подачи и экзамены"),
    )
    builder.row(
        KeyboardButton(text="📂 Необходимые документы"),
        KeyboardButton(text="👔 Дресс-код и проживание"),
    )
    return builder.as_markup(
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню или напишите вопрос...",
    )

logger = logging.getLogger(__name__)

router = Router(name="user")

# ── Максимальная длина сообщения Telegram ─────────────────────
_TG_MSG_MAX_LEN = 4096


# ── /start ────────────────────────────────────────────────────

@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    """/start — приветствие + сохранение пользователя в БД.

    Использует upsert: повторный /start безопасно обновит username.
    """
    if message.from_user is None:
        return

    await state.clear()  # Очищаем историю диалога при перезапуске бота

    telegram_id = message.from_user.id
    username = message.from_user.username

    async with async_session_factory() as session:
        try:
            user = await add_user(
                session=session,
                telegram_id=telegram_id,
                username=username,
            )
            await session.commit()

            logger.info(
                "Пользователь сохранён: id=%d, tg_id=%d, username=%s",
                user.id,
                user.telegram_id,
                user.username,
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "Ошибка при сохранении пользователя tg_id=%d", telegram_id,
            )
            await message.answer("⚠️ Произошла ошибка. Попробуйте позже.")
            return

    await message.answer(
        f"👋 Приветствуем вас в Академии СКФО, <b>{message.from_user.full_name}</b>!\n\n"
        "🏛 Я — ваш официальный цифровой ИИ-помощник приемной комиссии.\n\n"
        "Я могу подробно проконсультировать вас по следующим темам:\n"
        "• 🎓 <b>Направления обучения</b> (после 9 и 11 классов)\n"
        "• 💰 <b>Стоимость и сроки</b> обучения\n"
        "• 📅 <b>Сроки подачи документов</b> и экзамены\n"
        "• 📂 <b>Необходимые документы</b> для поступления\n"
        "• 👔 <b>Дресс-код для студентов</b> и проживание\n\n"
        "✍️ Задайте мне любой интересующий вас вопрос!",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.voice)
async def handle_voice_message(message: Message, state: FSMContext) -> None:
    """Обработка голосового сообщения."""
    if message.from_user is None or not message.voice or not message.bot:
        return

    thinking_msg = await message.answer("🎧 <b>Слушаю...</b>")

    # Скачиваем файл
    file_id = message.voice.file_id
    try:
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
    except Exception as e:
        logger.error("Ошибка при получении голосового сообщения: %s", e)
        await message.bot.edit_message_text("⚠️ Ошибка: не удалось получить аудиофайл.", chat_id=thinking_msg.chat.id, message_id=thinking_msg.message_id)
        return

    if not file_path:
        await message.bot.edit_message_text("⚠️ Ошибка: пустой путь аудиофайла.", chat_id=thinking_msg.chat.id, message_id=thinking_msg.message_id)
        return

    # Сохраняем в память (BytesIO) без использования диска
    audio_buffer = io.BytesIO()
        
    try:
        await message.bot.download_file(file_path, destination=audio_buffer)
        audio_bytes = audio_buffer.getvalue()
        
        # Распознаем текст
        transcribed_text = await transcribe_audio(audio_bytes)
    except Exception as e:
        logger.error("Ошибка при скачивании или распознавании аудио: %s", e)
        transcribed_text = None
            
    if not transcribed_text:
        await message.bot.edit_message_text(
            "Извините, я не смог разобрать ваше голосовое сообщение. Пожалуйста, напишите текстом или запишите еще раз.", 
            chat_id=thinking_msg.chat.id, 
            message_id=thinking_msg.message_id
        )
        return

    await message.bot.edit_message_text(
        f"🗣 <b>Вы сказали:</b> <i>{transcribed_text}</i>\n\n🤔 <b>Думаю...</b>", 
        chat_id=thinking_msg.chat.id, 
        message_id=thinking_msg.message_id
    )

    # Вызываем AI логику
    state_data = await state.get_data()
    history = state_data.get("history", [])
    sent_photos: list[str] = state_data.get("sent_photos", [])

    asyncio.create_task(
        _process_ai_query(
            user_query=transcribed_text,
            chat_id=thinking_msg.chat.id,
            message_id=thinking_msg.message_id,
            bot=message.bot,
            state=state,
            history=history,
            sent_photos=set(sent_photos),
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        ),
    )


# ── Текстовые сообщения (RAG + LLM) ─────────────────────────

@router.message(F.text)
async def handle_text_message(message: Message, state: FSMContext) -> None:
    """Обработка произвольного текстового сообщения.

    1. Получает историю диалога из FSM-хранилища Redis.
    2. Мгновенно отправляет «Думаю...».
    3. Запускает фоновую задачу для RAG-поиска, запроса к LLM и сохранения памяти.
    """
    if not message.text or message.from_user is None:
        return

    # Загружаем историю диалога и список отправленных фото из FSM
    state_data = await state.get_data()
    history = state_data.get("history", [])
    sent_photos: list[str] = state_data.get("sent_photos", [])

    thinking_msg = await message.answer("🤔 <b>Думаю...</b>")

    asyncio.create_task(
        _process_ai_query(
            user_query=message.text,
            chat_id=thinking_msg.chat.id,
            message_id=thinking_msg.message_id,
            bot=message.bot,
            state=state,
            history=history,
            sent_photos=set(sent_photos),
            telegram_id=message.from_user.id,
            username=message.from_user.username,
        ),
    )





async def _process_ai_query(
    user_query: str,
    chat_id: int,
    message_id: int,
    bot: object,
    state: FSMContext,
    history: list[dict[str, str]],
    sent_photos: set[str],
    telegram_id: int,
    username: str | None,
) -> None:
    """Фоновая задача: вызов сервиса ИИ → Редактирование сообщения.

    Вынесена из хендлера, чтобы не блокировать event loop.
    """
    from aiogram import Bot  # локальный импорт для типизации

    if not isinstance(bot, Bot):
        logger.error("Невалидный экземпляр Bot в _process_ai_query")
        return

    # Вызываем независимую от платформы логику
    ai_response, updated_history, updated_photos = await process_ai_query(
        user_query=user_query,
        user_id=telegram_id,
        history=history,
        sent_photos=sent_photos,
    )

    await state.update_data(history=updated_history, sent_photos=list(updated_photos))

    # Логируем в БД
    try:
        from database.crud import add_user, log_message
        from database.session import async_session_factory
        async with async_session_factory() as session:
            user = await add_user(session, telegram_id=telegram_id, username=username)
            await log_message(session, user_id=user.id, telegram_id=telegram_id, question=user_query, answer=ai_response.text)
            await session.commit()
    except Exception as e:
        logger.warning("Ошибка логирования сообщения Telegram: %s", e)

    if ai_response.photo_path is not None:
        # ── Режим: фото + подпись (одно сообщение) ────────────
        _TG_CAPTION_MAX_LEN = 1024
        answer = ai_response.text

        # Удаляем сообщение «Думаю...» — оно заменяется фото
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass  # Не критично, если не удалось удалить

        if len(answer) <= _TG_CAPTION_MAX_LEN:
            # Ответ помещается в подпись к фото
            await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(ai_response.photo_path),
                caption=answer,
            )
        else:
            # Ответ длинный: первая часть в подпись, остаток — отдельным сообщением
            cut_point = answer.rfind("\n", 0, _TG_CAPTION_MAX_LEN - 3)
            if cut_point <= 0:
                cut_point = _TG_CAPTION_MAX_LEN - 3
            caption_part = answer[:cut_point] + "..."
            rest_part = answer[cut_point:].lstrip("\n")

            await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(ai_response.photo_path),
                caption=caption_part,
            )

            # Обрезка остатка под лимит обычного сообщения
            if len(rest_part) > _TG_MSG_MAX_LEN:
                rest_part = rest_part[: _TG_MSG_MAX_LEN - 30] + "\n\n⚠️ <i>Ответ обрезан.</i>"

            await bot.send_message(chat_id=chat_id, text=rest_part)
    elif getattr(ai_response, "document_path", None) is not None:
        # ── Режим: документ + подпись (одно сообщение) ────────
        _TG_CAPTION_MAX_LEN = 1024
        answer = ai_response.text

        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

        if len(answer) <= _TG_CAPTION_MAX_LEN:
            await bot.send_document(
                chat_id=chat_id,
                document=FSInputFile(ai_response.document_path),
                caption=answer,
            )
        else:
            cut_point = answer.rfind("\n", 0, _TG_CAPTION_MAX_LEN - 3)
            if cut_point <= 0:
                cut_point = _TG_CAPTION_MAX_LEN - 3
            caption_part = answer[:cut_point] + "..."
            rest_part = answer[cut_point:].lstrip("\n")

            await bot.send_document(
                chat_id=chat_id,
                document=FSInputFile(ai_response.document_path),
                caption=caption_part,
            )

            if len(rest_part) > _TG_MSG_MAX_LEN:
                rest_part = rest_part[: _TG_MSG_MAX_LEN - 30] + "\n\n⚠️ <i>Ответ обрезан.</i>"

            await bot.send_message(chat_id=chat_id, text=rest_part)
    else:
        # ── Режим: только текст (без фото) ────────────────────
        answer = ai_response.text
        if len(answer) > _TG_MSG_MAX_LEN:
            answer = answer[: _TG_MSG_MAX_LEN - 30] + "\n\n⚠️ <i>Ответ обрезан.</i>"

        try:
            await bot.edit_message_text(
                text=answer,
                chat_id=chat_id,
                message_id=message_id,
            )
        except Exception:
            await _edit_with_error(bot, chat_id, message_id, "⚠️ Ошибка при отправке сообщения.")


async def _edit_with_error(
    bot: object,
    chat_id: int,
    message_id: int,
    error_text: str,
) -> None:
    """Безопасно редактировать сообщение на текст ошибки.

    Перехватывает исключения Telegram API, чтобы фоновая задача
    не падала с необработанной ошибкой.
    """
    from aiogram import Bot

    if not isinstance(bot, Bot):
        return

    try:
        await bot.edit_message_text(
            text=error_text,
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception:
        logger.exception(
            "Не удалось отредактировать сообщение об ошибке: chat=%d, msg=%d",
            chat_id,
            message_id,
        )
