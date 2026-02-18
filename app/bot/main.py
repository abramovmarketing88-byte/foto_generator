import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from redis.asyncio import from_url

from app.bot.middlewares import CooldownMiddleware
from app.bot.routers import register_routers
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.scheduler import setup_scheduler
from app.core.logging import configure_logging
from app.services.template_service import seed_templates


class DbSessionMiddleware:
    async def __call__(self, handler, event: Update, data):
        async with AsyncSessionLocal() as session:
            data["session"] = session
            result = await handler(event, data)
            return result


async def main() -> None:
    configure_logging()
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        await seed_templates(session)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    register_routers(dp)

    redis = from_url(settings.redis_url)
    dp.update.middleware(DbSessionMiddleware())
    dp.message.middleware(CooldownMiddleware(redis))

    scheduler = setup_scheduler()
    scheduler.start()

    logging.getLogger(__name__).info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
