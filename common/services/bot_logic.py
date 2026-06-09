"""
Платформонезависимая логика работы с ИИ.

Выполняет RAG-поиск, обращается к LLM, логирует диалог в БД
и ищет подходящее фото для ответа. Не привязана к Telegram или WhatsApp.
"""

import logging
import re
from pathlib import Path

from common.services.knowledge import get_knowledge_context
from common.services.llm_client import LLMError, get_ai_response
from common.services.photo_mapping import find_photo_for_query

logger = logging.getLogger(__name__)


def clean_markdown_to_html(text: str) -> str:
    """Конвертировать Markdown-звёздочки в правильные Telegram HTML-теги."""
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*", r"<i>\1</i>", text)
    return text


class AIResponse:
    """Дата-класс для ответа ИИ."""
    def __init__(self, text: str, photo_path: str | None = None, document_path: str | None = None):
        self.text = text
        self.photo_path = photo_path
        self.document_path = document_path


async def process_ai_query(
    user_query: str,
    user_id: int,
    history: list[dict[str, str]],
    sent_photos: set[str],
) -> tuple[AIResponse, list[dict[str, str]], set[str]]:
    """Основной пайплайн: RAG → LLM → Сохранение памяти → Поиск фото.

    Args:
        user_query: Текст сообщения от пользователя.
        user_id: Идентификатор пользователя (например, telegram_id).
        history: История переписки (последние сообщения).
        sent_photos: Множество имен отправленных фотографий, чтобы не повторяться.

    Returns:
        Кортеж: (AIResponse, обновленная_история, обновленное_множество_фото)
    """
    try:
        # 1. Загрузка контекста из текстовой базы знаний
        context = get_knowledge_context()

        logger.info(
            "Контекст: подготовлен контекст длиной %d символов. История содержит %d сообщений.",
            len(context),
            len(history),
        )

        # 2. Запрос к DeepSeek
        raw_answer = await get_ai_response(
            user_query=user_query,
            context=context,
            history=history,
        )

        # Форматирование для Telegram/WhatsApp (HTML)
        answer = clean_markdown_to_html(raw_answer)

        # 3. Сохранение нового раунда диалога в историю (храним последние 10 сообщений)
        updated_history = history + [
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": answer},
        ]
        updated_history = updated_history[-10:]

        # Логирование сообщения вынесено в контроллер (Unit of Work)

        # Обработка тегов документов
        document_str_path = None
        if "[SEND_ACCREDITATION_PDF]" in answer:
            answer = answer.replace("[SEND_ACCREDITATION_PDF]", "").strip()
            # Путь к PDF файлу
            pdf_path = Path(__file__).resolve().parent.parent.parent / "data" / "Реестровая выписка.pdf"
            if pdf_path.is_file():
                document_str_path = str(pdf_path)
            else:
                logger.error("Не найден файл аккредитации: %s", pdf_path)

        # 5. Поиск фото по ВОПРОСУ пользователя
        photo_path = find_photo_for_query(user_query, sent_photos)
        
        photo_str_path = None
        if photo_path is not None:
            photo_str_path = str(photo_path)
            sent_photos.add(photo_path.stem)
            
        # Отменяем фото, если есть PDF (API шлет либо одно, либо другое, PDF важнее)
        if document_str_path is not None:
            photo_str_path = None

        return AIResponse(text=answer, photo_path=photo_str_path, document_path=document_str_path), updated_history, sent_photos

    except LLMError as exc:
        logger.warning("LLM ошибка: %s", exc)
        return AIResponse(text=str(exc)), history, sent_photos

    except Exception:
        logger.exception("Непредвиденная ошибка в process_ai_query")
        return AIResponse(text="⚠️ Произошла непредвиденная ошибка. Попробуйте позже."), history, sent_photos
