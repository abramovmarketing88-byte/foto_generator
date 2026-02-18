from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards import main_menu

router = Router()


@router.message(F.text == "Загрузить 5 фото")
async def enroll_button(message: Message) -> None:
    await message.answer("Введите /enroll для запуска загрузки.")


@router.message(F.text == "Выбрать шаблон")
async def templates_button(message: Message) -> None:
    await message.answer("Введите /templates")


@router.message(F.text == "Меню")
async def show_menu(message: Message) -> None:
    await message.answer("Главное меню", reply_markup=main_menu())
