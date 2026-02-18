from aiogram import Dispatcher

from app.bot import (
    handlers_account,
    handlers_admin,
    handlers_enroll,
    handlers_generate,
    handlers_results,
    handlers_start,
    handlers_templates,
)
from app.bot.handlers import ai_admin, ai_seller, mode


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(ai_seller.router)
    dp.include_router(mode.router)
    dp.include_router(ai_admin.router)

    dp.include_router(handlers_start.router)
    dp.include_router(handlers_enroll.router)
    dp.include_router(handlers_templates.router)
    dp.include_router(handlers_generate.router)
    dp.include_router(handlers_account.router)
    dp.include_router(handlers_results.router)
    dp.include_router(handlers_admin.router)
