"""
Конфигурация приложения.

Загрузка переменных окружения через pydantic-settings.
Все секреты и настройки инфраструктуры описаны здесь.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Централизованные настройки приложения, загружаемые из .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram ─────────────────────────────────────────────
    bot_token: SecretStr
    telegram_proxy: str = ""
    telegram_api_server: str = ""

    # ── Webhook ──────────────────────────────────────────────
    use_webhook: bool = False   # False → polling (для тестирования)
    webhook_url: str = ""       # Публичный URL, нужен только при use_webhook=True
    webhook_path: str = "/webhook"
    
    # ── WhatsApp ─────────────────────────────────────────────
    whatsapp_service_url: str = "http://localhost:3000/send"

    # ── PostgreSQL ───────────────────────────────────────────
    database_url: str  # asyncpg DSN, e.g. postgresql+asyncpg://user:pass@host/db

    # ── Redis (FSM) ──────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── RAG / ChromaDB ───────────────────────────────────────
    chroma_persist_dir: str = "./chroma_data"
    chroma_collection_name: str = "knowledge_base"
    embedding_model_name: str = "all-MiniLM-L6-v2"
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # ── DeepSeek LLM ──────────────────────────────────────────
    deepseek_api_key: SecretStr
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # ── Groq API (Voice) ──────────────────────────────────────
    groq_api_key: SecretStr

    # ── Общие ────────────────────────────────────────────────
    debug: bool = False


settings = Settings()  # type: ignore[call-arg]
