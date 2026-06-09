"""
CRUD-операции для работы с пользователями и сообщениями.

Вся бизнес-логика доступа к данным вынесена в отдельные функции,
чтобы не засорять обработчики бота.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.database.models import Message, User


async def add_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
) -> User:
    """Добавить нового пользователя или вернуть существующего (upsert).

    Использует PostgreSQL ON CONFLICT DO UPDATE, чтобы
    атомарно обработать повторную регистрацию и обновить username.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        telegram_id: Уникальный Telegram ID пользователя.
        username: Telegram username (опционально).

    Returns:
        Экземпляр модели User.
    """
    stmt = (
        pg_insert(User)
        .values(telegram_id=telegram_id, username=username)
        .on_conflict_do_update(
            index_elements=[User.telegram_id],
            set_={"username": username},
        )
        .returning(User)
    )

    result = await session.execute(stmt)
    return result.scalars().one()


async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> User | None:
    """Найти пользователя по Telegram ID.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        telegram_id: Уникальный Telegram ID пользователя.

    Returns:
        Экземпляр User или None, если пользователь не найден.
    """
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ── Логирование сообщений ────────────────────────────────────


async def log_message(
    session: AsyncSession,
    user_id: int,
    telegram_id: int,
    question: str,
    answer: str,
) -> None:
    """Сохранить пару вопрос→ответ в таблицу messages.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        user_id: PK пользователя (модель User.id).
        telegram_id: Telegram ID пользователя.
        question: Текст вопроса.
        answer: Текст ответа бота.
        
    Важно: Функция больше не вызывает session.commit() самостоятельно.
    Это ответственность вызывающего кода (Unit of Work).
    """
    msg = Message(
        user_id=user_id,
        telegram_id=telegram_id,
        question=question,
        answer=answer,
    )
    session.add(msg)


# ── Аналитика для дашборда ───────────────────────────────────


async def get_dashboard_stats(session: AsyncSession) -> dict[str, int]:
    """Получить статистику для дашборда.

    Returns:
        Словарь с ключами: total_users, today_users, today_messages.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Всего пользователей
    total_users_result = await session.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar() or 0

    # Уникальных пользователей сегодня (кто отправлял сообщения)
    today_users_result = await session.execute(
        select(func.count(func.distinct(Message.telegram_id))).where(
            Message.created_at >= today_start,
        ),
    )
    today_users = today_users_result.scalar() or 0

    # Сообщений сегодня
    today_messages_result = await session.execute(
        select(func.count(Message.id)).where(
            Message.created_at >= today_start,
        ),
    )
    today_messages = today_messages_result.scalar() or 0

    return {
        "total_users": total_users,
        "today_users": today_users,
        "today_messages": today_messages,
    }


async def get_recent_messages(
    session: AsyncSession,
    limit: int = 100,
) -> list[dict[str, str]]:
    """Получить последние сообщения для таблицы дашборда.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        limit: Максимальное количество записей.

    Returns:
        Список словарей с полями: username, question, answer, created_at.
    """
    stmt = (
        select(
            User.username,
            User.telegram_id,
            Message.question,
            Message.answer,
            Message.created_at,
        )
        .join(User, Message.user_id == User.id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "username": row.username or f"id:{row.telegram_id}",
            "question": row.question,
            "answer": row.answer,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]


async def get_users_list(session: AsyncSession) -> list[dict[str, object]]:
    """Получить список пользователей с последним сообщением и счётчиком.

    Returns:
        Список словарей: telegram_id, username, last_question, last_time, msg_count.
    """
    # Подзапрос: последнее сообщение каждого пользователя
    last_msg_subq = (
        select(
            Message.telegram_id,
            func.max(Message.created_at).label("last_time"),
            func.count(Message.id).label("msg_count"),
        )
        .group_by(Message.telegram_id)
        .subquery()
    )

    stmt = (
        select(
            User.telegram_id,
            User.username,
            last_msg_subq.c.last_time,
            last_msg_subq.c.msg_count,
        )
        .join(last_msg_subq, User.telegram_id == last_msg_subq.c.telegram_id)
        .order_by(last_msg_subq.c.last_time.desc())
    )

    result = await session.execute(stmt)
    rows = result.all()

    # Получаем последний вопрос для каждого
    users_data: list[dict[str, object]] = []
    for row in rows:
        last_q_result = await session.execute(
            select(Message.question)
            .where(Message.telegram_id == row.telegram_id)
            .order_by(Message.created_at.desc())
            .limit(1),
        )
        last_question = last_q_result.scalar() or ""

        users_data.append({
            "telegram_id": row.telegram_id,
            "username": row.username or f"id:{row.telegram_id}",
            "last_question": last_question[:80] + "..." if len(last_question) > 80 else last_question,
            "last_time": row.last_time.isoformat() if row.last_time else "",
            "msg_count": row.msg_count or 0,
        })

    return users_data


async def get_messages_by_user(
    session: AsyncSession,
    telegram_id: int,
    limit: int = 200,
) -> list[dict[str, str]]:
    """Получить историю диалога конкретного пользователя.

    Args:
        session: Активная асинхронная сессия.
        telegram_id: Telegram ID пользователя.
        limit: Максимальное количество сообщений.

    Returns:
        Список словарей: question, answer, created_at (в хронологическом порядке).
    """
    stmt = (
        select(Message.question, Message.answer, Message.created_at)
        .where(Message.telegram_id == telegram_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "question": row.question,
            "answer": row.answer,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]


