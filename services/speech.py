import logging
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

# Загружаем прокси из .env (если есть), иначе используем жестко заданный
PROXY_URL = "http://x3kP8n:QD1p0R@196.18.227.129:8000"

# Используем официальный клиент OpenAI, но направляем его на API Groq
_groq_client = AsyncOpenAI(
    api_key=settings.groq_api_key.get_secret_value(),
    base_url="https://api.groq.com/openai/v1",
    http_client=httpx.AsyncClient(proxy=PROXY_URL)
)

async def transcribe_audio(audio_data: bytes) -> str | None:
    """Переводит голосовое сообщение в текст с помощью Groq Whisper (In-Memory).

    Args:
        audio_data: Байты аудиофайла (ogg/mp3/wav)

    Returns:
        Распознанный текст или None в случае ошибки.
    """
    try:
        # Отправляем байты напрямую, имитируя файл "audio.ogg"
        transcription = await _groq_client.audio.transcriptions.create(
            file=("audio.ogg", audio_data),
            model="whisper-large-v3",
            response_format="text",
            language="ru",
        )
        
        text = str(transcription).strip()
        
        if not text:
            return None
            
        return text
        
    except Exception as e:
        logger.error("Ошибка при распознавании аудио через Groq: %s", e)
        return None
