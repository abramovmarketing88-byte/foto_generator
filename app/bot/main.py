from __future__ import annotations

import logging
import re
import asyncio
from pathlib import Path
from typing import Callable, Coroutine, TypeVar

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import create_session_factory
from app.logging_setup import setup_logging
from app.models import Base, PhotoKind
from app.repo import NeuroPhotoshootRepo
from app.storage import LocalStorage
from app.worker import run_worker

logger = logging.getLogger(__name__)
router = Router()

T = TypeVar("T")


class AppContext:
    def __init__(self, settings: Settings, session_factory: sessionmaker, storage: LocalStorage):
        self.settings = settings
        self.session_factory = session_factory
        self.storage = storage


class ProfileState(StatesGroup):
    waiting_profile_text = State()


class PhotoState(StatesGroup):
    waiting_face = State()
    waiting_full_body = State()
    waiting_face_confirm = State()


class SceneState(StatesGroup):
    waiting_scene_text = State()


MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Профиль"), KeyboardButton(text="Фото")],
        [KeyboardButton(text="Сцена"), KeyboardButton(text="Камера")],
        [KeyboardButton(text="Генерация"), KeyboardButton(text="История")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Показать профиль")],
    ],
    resize_keyboard=True,
)


def with_error_handling(func: Callable[..., Coroutine[None, None, T]]) -> Callable[..., Coroutine[None, None, T | None]]:
    async def wrapper(event: Message | CallbackQuery, *args, **kwargs):
        try:
            return await func(event, *args, **kwargs)
        except Exception:
            logger.exception("Handler error")
            if isinstance(event, CallbackQuery):
                await event.answer("Произошла ошибка. Попробуйте снова.", show_alert=True)
            else:
                await event.answer("Произошла ошибка. Попробуйте снова.")
            return None

    return wrapper


def parse_profile(text: str) -> tuple[int | None, int | None, int | None]:
    age = None
    height = None
    weight = None

    age_match = re.search(r"(?:возраст|age|лет)\D{0,6}(\d{1,2})", text.lower()) or re.search(r"\b(\d{1,2})\s*(?:лет|года)\b", text.lower())
    if age_match:
        age = int(age_match.group(1))

    height_match = re.search(r"(?:рост|height)\D{0,6}(\d{2,3})", text.lower()) or re.search(r"\b(1\d{2}|2[0-2]\d)\s*см\b", text.lower())
    if height_match:
        height = int(height_match.group(1))

    weight_match = re.search(r"(?:вес|weight)\D{0,6}(\d{2,3})", text.lower()) or re.search(r"\b(\d{2,3})\s*кг\b", text.lower())
    if weight_match:
        weight = int(weight_match.group(1))

    return age, height, weight


def photo_menu(face_count: int, full_body_count: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Загрузить лицо"), KeyboardButton(text="Загрузить полный рост")],
            [KeyboardButton(text="Сбросить фото"), KeyboardButton(text="Готово")],
        ],
        resize_keyboard=True,
    )


def camera_inline(settings: dict[str, str | int | bool | None]) -> InlineKeyboardMarkup:
    lens = [
        ("Не выбирать", "none"),
        ("24mm", "24"),
        ("35mm", "35"),
        ("50mm", "50"),
        ("85mm", "85"),
        ("135mm", "135"),
    ]
    angles = ["DRONE_TOP", "LOW_FROM_BELOW", "SIDE_PROFILE", "DUTCH_ANGLE", "PANORAMA_360", "FOOT_LEVEL", "ARM_LENGTH_SELFIE", "NON_SELFIE_PORTRAIT"]
    framings = ["CLOSE_UP", "HALF_BODY", "FULL_BODY"]
    sizes = ["SQUARE_1024", "PORTRAIT_1024_1536", "LANDSCAPE_1536_1024", "IG_1080_1350", "HD_1920_1080", "LARGE_2048"]

    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(text=f"Lens: {settings['lens_mm'] if settings['lens_selected'] else 'none'}", callback_data="noop")]]
    rows += [[InlineKeyboardButton(text=label, callback_data=f"lens:{val}")] for label, val in lens]
    rows += [[InlineKeyboardButton(text=f"Angle: {a}", callback_data=f"angle:{a}")] for a in angles]
    rows += [[InlineKeyboardButton(text=f"Framing: {f}", callback_data=f"framing:{f}")] for f in framings]
    rows += [[InlineKeyboardButton(text=f"Size: {s}", callback_data=f"size:{s}")] for s in sizes]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def try_detect_face(path: Path) -> bool | None:
    try:
        import cv2
        import mediapipe as mp

        image = cv2.imread(str(path))
        if image is None:
            return None
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        with mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5) as detector:
            result = detector.process(rgb)
        return bool(result.detections)
    except Exception:
        logger.exception("Face detection unavailable")
        return None


def _get_user(app_ctx: AppContext, telegram_user_id: int) -> int:
    with app_ctx.session_factory() as session:
        user = NeuroPhotoshootRepo(session).ensure_user(telegram_user_id)
    return user.id


async def _photo_counts(app_ctx: AppContext, user_id: int) -> tuple[int, int]:
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        return repo.count_photos(user_id, PhotoKind.FACE), repo.count_photos(user_id, PhotoKind.FULL_BODY)


@router.message(Command("start"))
@with_error_handling
async def on_start(message: Message, app_ctx: AppContext) -> None:
    _get_user(app_ctx, message.from_user.id)
    await message.answer("Добро пожаловать! Выберите раздел:", reply_markup=MAIN_MENU)


@router.message(Command("help"))
@with_error_handling
async def on_help_cmd(message: Message, app_ctx: AppContext) -> None:
    await on_help(message, app_ctx)


@router.message(F.text == "Помощь")
@with_error_handling
async def on_help(message: Message, app_ctx: AppContext) -> None:
    _get_user(app_ctx, message.from_user.id)
    await message.answer("Заполните профиль, загрузите минимум 1 фото лица, добавьте сцену и запустите генерацию.")


@router.message(F.text == "Профиль")
@with_error_handling
async def ask_profile(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    _get_user(app_ctx, message.from_user.id)
    await state.set_state(ProfileState.waiting_profile_text)
    await message.answer("Отправьте одним сообщением физические признаки.")


@router.message(ProfileState.waiting_profile_text, F.text)
@with_error_handling
async def save_profile(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    age, height_cm, weight_kg = parse_profile(message.text)
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_profile(user_id, message.text, age, height_cm, weight_kg)
    await state.clear()
    await message.answer("Профиль сохранён.", reply_markup=MAIN_MENU)


@router.message(F.text == "Показать профиль")
@with_error_handling
async def show_profile(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        profile = NeuroPhotoshootRepo(session).get_profile(user_id)
    await message.answer(profile.profile_text if profile else "Профиль ещё не заполнен.")


@router.message(F.text == "Фото")
@with_error_handling
async def photo_menu_handler(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    face_count, full_body_count = await _photo_counts(app_ctx, user_id)
    await message.answer(
        f"Лицо: {face_count}/5\nПолный рост: {full_body_count}/2",
        reply_markup=photo_menu(face_count, full_body_count),
    )


@router.message(F.text == "Загрузить лицо")
@with_error_handling
async def request_face(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    face_count, _ = await _photo_counts(app_ctx, user_id)
    if face_count >= 5:
        await message.answer("Лимит фото лица достигнут.")
        return
    await state.set_state(PhotoState.waiting_face)
    await message.answer("Отправьте фото лица.")


@router.message(F.text == "Загрузить полный рост")
@with_error_handling
async def request_full_body(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    _, full_body_count = await _photo_counts(app_ctx, user_id)
    if full_body_count >= 2:
        await message.answer("Лимит фото в полный рост достигнут.")
        return
    await state.set_state(PhotoState.waiting_full_body)
    await message.answer("Отправьте фото в полный рост.")


async def _save_photo(message: Message, bot: Bot, app_ctx: AppContext, user_id: int, kind: PhotoKind) -> str:
    largest_photo = message.photo[-1]
    tg_file = await bot.get_file(largest_photo.file_id)
    destination = app_ctx.storage.build_raw_photo_path(user_id=user_id)
    await bot.download(tg_file, destination=destination)
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).add_photo(user_id, kind, str(destination))
    return str(destination)


@router.message(PhotoState.waiting_face, F.photo)
@with_error_handling
async def save_face(message: Message, state: FSMContext, bot: Bot, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    face_count, _ = await _photo_counts(app_ctx, user_id)
    if face_count >= 5:
        await state.clear()
        await message.answer("Лимит фото лица достигнут.")
        return
    largest_photo = message.photo[-1]
    tg_file = await bot.get_file(largest_photo.file_id)
    destination = app_ctx.storage.build_raw_photo_path(user_id=user_id)
    await bot.download(tg_file, destination=destination)
    detection_result = try_detect_face(destination)
    if detection_result is False:
        await state.set_state(PhotoState.waiting_face_confirm)
        await state.update_data(temp_face_path=str(destination))
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Все равно сохранить")], [KeyboardButton(text="Фото")]], resize_keyboard=True)
        await message.answer("Лицо не найдено. Нажмите «Все равно сохранить» или загрузите другое фото.", reply_markup=kb)
        return
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).add_photo(user_id, PhotoKind.FACE, str(destination))
    await state.clear()
    await message.answer("Фото лица сохранено.", reply_markup=MAIN_MENU)


@router.message(PhotoState.waiting_face_confirm, F.text == "Все равно сохранить")
@with_error_handling
async def confirm_save_face(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    data = await state.get_data()
    temp_path = data.get("temp_face_path")
    if not temp_path:
        await message.answer("Нет ожидающего фото.")
        return
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).add_photo(user_id, PhotoKind.FACE, temp_path)
    await state.clear()
    await message.answer("Фото сохранено.", reply_markup=MAIN_MENU)


@router.message(PhotoState.waiting_full_body, F.photo)
@with_error_handling
async def save_full_body(message: Message, state: FSMContext, bot: Bot, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    _, full_body_count = await _photo_counts(app_ctx, user_id)
    if full_body_count >= 2:
        await state.clear()
        await message.answer("Лимит фото в полный рост достигнут.")
        return
    await _save_photo(message, bot, app_ctx, user_id, PhotoKind.FULL_BODY)
    await state.clear()
    await message.answer("Фото в полный рост сохранено.", reply_markup=MAIN_MENU)


@router.message(F.text == "Сбросить фото")
@with_error_handling
async def reset_photos(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        paths = NeuroPhotoshootRepo(session).clear_user_photos(user_id)
    for path in paths:
        Path(path).unlink(missing_ok=True)
    await message.answer("Фото удалены.")


@router.message(F.text == "Готово")
@with_error_handling
async def photos_done(message: Message) -> None:
    await message.answer("Загрузка фото завершена.", reply_markup=MAIN_MENU)


@router.message(F.text == "Сцена")
@with_error_handling
async def ask_scene(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    _get_user(app_ctx, message.from_user.id)
    await state.set_state(SceneState.waiting_scene_text)
    await message.answer("Опишите сцену одним сообщением.")


@router.message(SceneState.waiting_scene_text, F.text)
@with_error_handling
async def save_scene(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_scene(user_id, message.text)
    await state.clear()
    await message.answer("Сцена сохранена.", reply_markup=MAIN_MENU)


@router.message(F.text == "Камера")
@with_error_handling
async def camera_menu(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        settings = NeuroPhotoshootRepo(session).get_or_create_shoot_settings(user_id)
    data = {
        "lens_selected": settings.lens_selected,
        "lens_mm": settings.lens_mm,
    }
    await message.answer("Настройки камеры:", reply_markup=camera_inline(data))


@router.callback_query(F.data.startswith(("lens:", "angle:", "framing:", "size:", "noop")))
@with_error_handling
async def on_camera_callback(callback: CallbackQuery, app_ctx: AppContext) -> None:
    if callback.data == "noop":
        await callback.answer()
        return
    user_id = _get_user(app_ctx, callback.from_user.id)
    key, value = callback.data.split(":", 1)
    payload = {}
    if key == "lens":
        if value == "none":
            payload = {"lens_selected": False, "lens_mm": None}
        else:
            payload = {"lens_selected": True, "lens_mm": int(value)}
    elif key == "angle":
        payload = {"angle_code": value}
    elif key == "framing":
        payload = {"framing_code": value}
    elif key == "size":
        payload = {"output_size_code": value}

    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        repo.update_shoot_settings(user_id, **payload)
        settings = repo.get_or_create_shoot_settings(user_id)

    await callback.message.edit_reply_markup(
        reply_markup=camera_inline({"lens_selected": settings.lens_selected, "lens_mm": settings.lens_mm})
    )
    await callback.answer("Сохранено")


@router.message(F.text == "Генерация")
@with_error_handling
async def generate(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        profile = repo.get_profile(user_id)
        scene = repo.get_scene(user_id)
        face_count = repo.count_photos(user_id, PhotoKind.FACE)

        if not profile:
            await message.answer("Сначала заполните профиль.")
            return
        if face_count < 1:
            await message.answer("Загрузите минимум 1 фото лица.")
            return
        if not scene:
            await message.answer("Сначала опишите сцену.")
            return
        if repo.count_active_jobs(user_id) >= app_ctx.settings.max_concurrent_jobs_per_user:
            await message.answer("Превышен лимит активных задач.")
            return

        job = repo.create_job(user_id)

    await message.answer(f"Задача #{job.id} поставлена в очередь. Job queued.")


@router.message(F.text == "История")
@with_error_handling
async def history(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        generations = repo.get_generations(user_id, limit=10)
        settings = repo.get_or_create_shoot_settings(user_id)

    if not generations:
        await message.answer("История пока пустая.")
        return

    for g in generations:
        scene_preview = g.final_prompt[:50] + ("..." if len(g.final_prompt) > 50 else "")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Отправить результат", callback_data=f"send_result:{g.id}")]]
        )
        await message.answer(
            f"{g.created_at:%Y-%m-%d %H:%M}\n"
            f"Сцена: {scene_preview}\n"
            f"Линза: {settings.lens_mm if settings.lens_selected else 'не выбрана'}\n"
            f"Ракурс: {settings.angle_code}\n"
            f"Размер: {settings.output_size_code}",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("send_result:"))
@with_error_handling
async def send_result(callback: CallbackQuery, app_ctx: AppContext, bot: Bot) -> None:
    user_id = _get_user(app_ctx, callback.from_user.id)
    generation_id = int(callback.data.split(":", 1)[1])
    with app_ctx.session_factory() as session:
        generation = NeuroPhotoshootRepo(session).get_generation(generation_id, user_id)
    if not generation:
        await callback.answer("Результат не найден", show_alert=True)
        return

    path = Path(generation.result_file_path)
    if not path.exists():
        logger.exception("Result file missing", extra={"user_id": user_id, "generation_id": generation_id})
        await callback.answer("Файл результата не найден", show_alert=True)
        return

    await bot.send_document(chat_id=callback.from_user.id, document=FSInputFile(path))
    await callback.answer()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    storage = LocalStorage(settings.storage_dir)
    storage.ensure_dirs()

    session_factory = create_session_factory(settings)
    with session_factory() as session:
        Base.metadata.create_all(bind=session.bind)

    app_ctx = AppContext(settings=settings, session_factory=session_factory, storage=storage)

    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    dp["app_ctx"] = app_ctx

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(bot, settings, session_factory, storage, stop_event))

    logger.info("Starting bot polling")
    try:
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            logger.info("Worker task cancelled")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
