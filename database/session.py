"""
Настройка асинхронного подключения к PostgreSQL.

Создаёт async engine и фабрику сессий.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

async_engine = create_async_engine(
    url=settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость для получения асинхронной сессии.

    Используется как async context-manager:
        async with get_session() as session:
            ...
    Или как async-генератор для DI.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
