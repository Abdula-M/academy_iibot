"""
LLM-клиент — обёртка над DeepSeek API.

Использует официальную библиотеку ``openai`` с кастомным base_url.
Полностью изолирован: не знает ни о Telegram, ни о RAG-движке.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI, APIConnectionError, APIStatusError

from common.core.config import settings

logger = logging.getLogger(__name__)

# ── Системный промпт ─────────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = """Вы — Марина, сотрудник приемной комиссии «Академии Северо-Кавказского федерального округа профессионального образования» (г. Махачкала). Вы позиционируете себя как живого человека, который с радостью помогает абитуриентам и их родителям получать нужную информацию о поступлении, специальностях, ценах и правилах Академии.

[Инструкции по поведению и стилю общения]
{greeting_instruction}
2. Краткость и конкретика: Отвечайте СТРОГО на заданный вопрос. Не выдавайте информацию, о которой пользователь не спрашивал. Если вопрос касается стоимости одной специальности, не перечисляйте остальные.
3. Опора на факты: Используйте ТОЛЬКО предоставленную базу знаний. Запрещено придумывать цены, сроки или условия, которых нет в тексте. Если информации для ответа нет, вежливо сообщите об этом и предложите позвонить в приемную комиссию: 8 992 900 00 54.
4. Вежливость и эмпатия: Общайтесь уважительно, приветливо и профессионально, как живой человек. Если вы видите, что клиент что-то не понимает, запутался или переспрашивает — терпеливо, подробно и понятным языком объясните ему всю необходимую информацию, искренне помогая разобраться в ситуации.
5. Задавайте уточняющие вопросы ТОЛЬКО по мере необходимости: Если вам не хватает деталей для точного ответа или пользователю нужна помощь с выбором, задайте ОДИН логичный вопрос (например: "Вы планируете поступать после 9 или 11 класса?"). Если же вы полностью ответили на вопрос пользователя и ситуация ясна, дополнительно спрашивать ничего не нужно.
6. Правило ненавязчивости (КРИТИЧЕСКИ ВАЖНО): Если пользователь в своем следующем сообщении проигнорировал ваш встречный вопрос, категорически запрещено повторять его. Просто ответьте на новый запрос пользователя.
7. Отправка выписки об аккредитации: Если пользователь спрашивает про аккредитацию, расскажите о ней и обязательно спросите: "Отправить ли вам файл официальной выписки?". Если пользователь отвечает согласием ("да", "отправь", "давай" и т.д.), ответьте "Отправляю файл выписки об аккредитации" и ОБЯЗАТЕЛЬНО добавьте в самый конец вашего ответа специальный скрытый тег: [SEND_ACCREDITATION_PDF].
8. Ответ сообщения максимум 1000 символов.
9. ВАЖНО: При оформлении текста выделяй важные моменты СТРОГО с помощью HTML-тегов <b>выделенный текст</b>. КАТЕГОРИЧЕСКИ запрещено использовать Markdown-звездочки (например, **текст**).

### Контекст из базы знаний:
{context}
"""

_SYSTEM_PROMPT_NO_CONTEXT = (
    "{greeting}, меня зовут Марина. Я — сотрудник приемной комиссии Академии Северо-Кавказского федерального округа профессионального образования (г. Махачкала).\n"
    "В данный момент моя база знаний временно недоступна. Пожалуйста, обратитесь напрямую в приемную комиссию по телефону: 8 992 900 00 54, и мы вам обязательно поможем!"
)

# ── Асинхронный клиент (singleton) ────────────────────────────
_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key.get_secret_value(),
    base_url=settings.deepseek_base_url,
)


async def get_ai_response(
    user_query: str,
    context: str,
    history: list[dict[str, str]] | None = None,
    *,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """Получить ответ от DeepSeek, обогащённый RAG-контекстом и историей диалога.

    Args:
        user_query: Вопрос пользователя.
        context: Релевантные фрагменты из базы знаний.
                 Пустая строка — если база пуста или ничего не найдено.
        history: История предыдущих сообщений в формате [{"role": "...", "content": "..."}].
        max_tokens: Максимальная длина ответа.
        temperature: Креативность модели (0.0–2.0).

    Returns:
        Текстовый ответ модели.

    Raises:
        LLMError: Обёртка над любой ошибкой API для единообразной
                  обработки в вызывающем коде.
    """
    # Определяем подходящее приветствие по времени Москвы/Махачкалы (UTC+3)
    now_msk = datetime.now(timezone(timedelta(hours=3)))
    hour = now_msk.hour
    if 5 <= hour < 12:
        greeting = "Доброе утро"
    elif 12 <= hour < 18:
        greeting = "Добрый день"
    elif 18 <= hour < 23:
        greeting = "Добрый вечер"
    else:
        greeting = "Доброй ночи"

    if not history:
        greeting_instruction = f'1. Приветствие и знакомство: Обязательно ответьте приветствием (используйте фразу: "{greeting}") и представьтесь: "меня зовут Марина. Я готова ответить на ваши вопросы."'
    else:
        greeting_instruction = '1. Знакомство: КРИТИЧЕСКИ ВАЖНО — НЕ ЗДОРОВАЙТЕСЬ и НЕ ПРЕДСТАВЛЯЙТЕСЬ в этом сообщении. Вы уже поздоровались ранее в истории диалога. Сразу переходите к ответу на вопрос пользователя.'

    system_prompt = (
        _SYSTEM_PROMPT_TEMPLATE.format(context=context, greeting_instruction=greeting_instruction)
        if context
        else _SYSTEM_PROMPT_NO_CONTEXT.format(greeting=greeting)
    )

    # ── Формирование цепочки сообщений с памятью ────────────────────
    messages = []
    messages.append({"role": "system", "content": system_prompt})

    # Добавляем историю (если она передана)
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Добавляем текущий запрос пользователя
    messages.append({"role": "user", "content": user_query})

    try:
        response = await _client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
        )

        answer = response.choices[0].message.content
        if not answer:
            return "⚠️ Модель вернула пустой ответ. Попробуйте переформулировать вопрос."

        logger.info(
            "DeepSeek ответил: model=%s, tokens_in=%s, tokens_out=%s",
            response.model,
            response.usage.prompt_tokens if response.usage else "?",
            response.usage.completion_tokens if response.usage else "?",
        )
        return answer

    except APIConnectionError:
        logger.exception("Не удалось подключиться к DeepSeek API")
        raise LLMError("Сервер ИИ недоступен. Попробуйте позже.") from None

    except APIStatusError as exc:
        logger.exception(
            "DeepSeek API вернул ошибку: status=%d", exc.status_code,
        )
        raise LLMError(
            f"Ошибка API (код {exc.status_code}). Попробуйте позже.",
        ) from None

    except Exception:
        logger.exception("Непредвиденная ошибка при вызове DeepSeek API")
        raise LLMError(
            "Непредвиденная ошибка при обращении к ИИ.",
        ) from None


class LLMError(Exception):
    """Ошибка LLM-клиента.

    Содержит user-friendly сообщение, безопасное для отправки в Telegram.
    """
