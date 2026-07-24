import asyncio

from sqlalchemy import select

from common.database.models import VacancyApplication
from common.database.session import async_session_factory


async def main():
    async with async_session_factory() as session:
        stmt = select(VacancyApplication)
        result = await session.execute(stmt)
        apps = result.scalars().all()
        print(f"Total apps: {len(apps)}")
        for app in apps:
            print(f"ID: {app.id}, user_id: {app.user_id}, platform: {app.platform}")

if __name__ == "__main__":
    asyncio.run(main())
