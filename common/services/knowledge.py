import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к файлу базы знаний относительно корня проекта
KNOWLEDGE_FILE_PATH = Path(__file__).parent.parent.parent / "data" / "knowledge.txt"

# Кэш
_cached_context: str = ""
_last_mtime: float = 0.0


def get_knowledge_context() -> str:
    """Считывает файл базы знаний с диска с кэшированием.

    Использует кэширование в памяти. Инвалидация происходит
    автоматически при изменении времени модификации файла.
    Скорость работы возрастает на порядки (без I/O операций).
    """
    global _cached_context, _last_mtime

    try:
        if not KNOWLEDGE_FILE_PATH.exists():
            logger.warning(
                "Файл базы знаний не найден по пути: %s",
                KNOWLEDGE_FILE_PATH,
            )
            return ""

        current_mtime = os.stat(KNOWLEDGE_FILE_PATH).st_mtime
        if current_mtime > _last_mtime or not _cached_context:
            _cached_context = KNOWLEDGE_FILE_PATH.read_text(encoding="utf-8")
            _last_mtime = current_mtime
            logger.info("База знаний загружена в кэш (mtime: %f)", current_mtime)

        return _cached_context
    except Exception:
        logger.exception("Ошибка при чтении файла базы знаний")
        return ""
