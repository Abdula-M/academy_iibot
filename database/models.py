"""
Модели SQLAlchemy.

Все ORM-модели наследуются от единого Base.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


class User(Base):
    """Пользователь Telegram-бота."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
        comment="Уникальный Telegram ID пользователя",
    )
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Telegram username (без @)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Дата регистрации пользователя",
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="user",
        lazy="selectin",
    )


class Message(Base):
    """Лог сообщений: вопрос пользователя + ответ бота."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK на пользователя",
    )
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="Telegram ID (для быстрых запросов без JOIN)",
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Вопрос пользователя",
    )
    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Ответ бота",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="Время сообщения",
    )

    user: Mapped["User"] = relationship(
        back_populates="messages",
        lazy="joined",
    )

