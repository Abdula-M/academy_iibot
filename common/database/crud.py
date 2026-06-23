"""
CRUD-операции для работы с пользователями и сообщениями.

Вся бизнес-логика доступа к данным вынесена в отдельные функции,
чтобы не засорять обработчики бота.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, case, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.database.models import Message, User, VacancyApplication


async def add_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    platform: str | None = None,
) -> User:
    """Добавить нового пользователя или вернуть существующего (upsert).

    Использует PostgreSQL ON CONFLICT DO UPDATE, чтобы
    атомарно обработать повторную регистрацию и обновить username.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        telegram_id: Уникальный Telegram ID пользователя.
        username: Telegram username (опционально).
        platform: Платформа (telegram/instagram/whatsapp/max).

    Returns:
        Экземпляр модели User.
    """
    stmt = (
        pg_insert(User)
        .values(telegram_id=telegram_id, username=username, platform=platform)
        .on_conflict_do_update(
            index_elements=[User.telegram_id],
            set_={"username": username, "platform": platform},
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


async def mark_messages_read(session: AsyncSession, telegram_id: int) -> None:
    """Помечает все сообщения пользователя как прочитанные."""
    stmt = (
        update(Message)
        .where(Message.telegram_id == telegram_id)
        .where(Message.is_read == False)
        .values(is_read=True)
    )
    await session.execute(stmt)
    await session.commit()


async def mark_vacancy_application_read(session: AsyncSession, application_id: int) -> None:
    """Помечает конкретную заявку на вакансию как прочитанную."""
    stmt = (
        update(VacancyApplication)
        .where(VacancyApplication.id == application_id)
        .values(is_read=True)
    )
    await session.execute(stmt)
    await session.commit()


async def get_unread_applications_count(session: AsyncSession) -> int:
    """Возвращает количество непрочитанных заявок на вакансию."""
    stmt = select(func.count(VacancyApplication.id)).where(VacancyApplication.is_read == False)
    result = await session.execute(stmt)
    return result.scalar() or 0


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


async def get_users_list(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Получить список пользователей с последним сообщением и счётчиком.

    Args:
        session: Активная асинхронная сессия.
        offset: Смещение для пагинации.
        limit: Максимальное количество записей.

    Returns:
        Словарь: items (список пользователей), total (общее количество).
    """
    # Подзапрос: агрегаты по каждому пользователю
    last_msg_subq = (
        select(
            Message.telegram_id,
            func.max(Message.created_at).label("last_time"),
            func.sum(case((Message.is_read == False, 1), else_=0)).label("msg_count"),
        )
        .group_by(Message.telegram_id)
        .subquery()
    )

    # Подзапрос: последний вопрос каждого пользователя (убирает N+1)
    last_question_subq = (
        select(
            Message.telegram_id,
            Message.question.label("last_question"),
        )
        .distinct(Message.telegram_id)
        .order_by(Message.telegram_id, Message.created_at.desc())
        .subquery()
    )

    # Общее количество пользователей с сообщениями
    count_stmt = (
        select(func.count())
        .select_from(User)
        .join(last_msg_subq, User.telegram_id == last_msg_subq.c.telegram_id)
    )
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Основной запрос с пагинацией
    stmt = (
        select(
            User.telegram_id,
            User.username,
            User.platform,
            last_msg_subq.c.last_time,
            last_msg_subq.c.msg_count,
            last_question_subq.c.last_question,
        )
        .join(last_msg_subq, User.telegram_id == last_msg_subq.c.telegram_id)
        .outerjoin(last_question_subq, User.telegram_id == last_question_subq.c.telegram_id)
        .order_by(last_msg_subq.c.last_time.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    items: list[dict[str, object]] = []
    for row in rows:
        last_question = row.last_question or ""
        items.append({
            "telegram_id": row.telegram_id,
            "username": row.username or f"id:{row.telegram_id}",
            "platform": row.platform or "telegram",
            "last_question": last_question[:80] + "..." if len(last_question) > 80 else last_question,
            "last_time": row.last_time.isoformat() if row.last_time else "",
            "msg_count": row.msg_count or 0,
        })

    return {"items": items, "total": total}


async def get_messages_by_user(
    session: AsyncSession,
    telegram_id: int,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Получить историю диалога конкретного пользователя с пагинацией.

    Args:
        session: Активная асинхронная сессия.
        telegram_id: Telegram ID пользователя.
        offset: Смещение от конца (0 = последние сообщения).
        limit: Максимальное количество сообщений.

    Returns:
        Словарь: items (список сообщений в хронологическом порядке), total.
    """
    # Общее количество сообщений пользователя
    count_stmt = (
        select(func.count(Message.id))
        .where(Message.telegram_id == telegram_id)
    )
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Берём последние сообщения с учётом offset
    stmt = (
        select(Message.id, Message.question, Message.answer, Message.created_at)
        .where(Message.telegram_id == telegram_id)
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()[::-1]  # Разворачиваем в хронологический порядок

    items = [
        {
            "id": row.id,
            "question": row.question,
            "answer": row.answer,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]

    return {"items": items, "total": total}


# ── Заявки на вакансии ───────────────────────────────────────


async def save_vacancy_application(
    session: AsyncSession,
    user_id: int,
    platform_user_id: int,
    platform: str,
    application_text: str,
) -> None:
    """Сохранить заявку на вакансию.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        user_id: PK пользователя (модель User.id).
        platform_user_id: ID пользователя на платформе.
        platform: Название платформы (telegram/instagram/whatsapp/max).
        application_text: Полный текст заполненной анкеты.
    """
    application = VacancyApplication(
        user_id=user_id,
        platform_user_id=platform_user_id,
        platform=platform,
        application_text=application_text,
    )
    session.add(application)


async def get_vacancy_applications(
    session: AsyncSession,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, object]:
    """Получить список заявок на вакансии для дашборда с пагинацией.

    Args:
        session: Активная асинхронная сессия SQLAlchemy.
        offset: Смещение для пагинации.
        limit: Максимальное количество записей.

    Returns:
        Словарь: items (список заявок), total (общее количество).
    """
    # Общее количество заявок
    count_stmt = select(func.count(VacancyApplication.id))
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = (
        select(
            VacancyApplication.id,
            User.username,
            VacancyApplication.platform_user_id,
            VacancyApplication.platform,
            VacancyApplication.application_text,
            VacancyApplication.created_at,
            VacancyApplication.is_read,
        )
        .outerjoin(User, VacancyApplication.user_id == User.id)
        .order_by(VacancyApplication.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await session.execute(stmt)
    rows = result.all()

    items = [
        {
            "id": row.id,
            "username": row.username or f"id:{row.platform_user_id}",
            "platform": row.platform,
            "application_text": row.application_text,
            "created_at": row.created_at.isoformat(),
            "is_read": row.is_read,
        }
        for row in rows
    ]

    return {"items": items, "total": total}


async def get_vacancy_application(session: AsyncSession, application_id: int):
    """Получить детальную информацию о заявке."""
    result = await session.execute(select(VacancyApplication).where(VacancyApplication.id == application_id))
    return result.scalar_one_or_none()


async def delete_vacancy_application(session: AsyncSession, application_id: int) -> None:
    """Удалить заявку на вакансию."""
    stmt = update(VacancyApplication).where(VacancyApplication.id == application_id).values(is_deleted=True)
    await session.execute(stmt)
    await session.commit()


async def get_all_vacancy_applications_count(session: AsyncSession) -> int:
    """Возвращает общее количество заявок."""
    result = await session.execute(select(func.count(VacancyApplication.id)))
    return result.scalar() or 0
