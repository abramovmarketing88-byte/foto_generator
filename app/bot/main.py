from __future__ import annotations

import logging
import os
import re
import asyncio
import inspect
from pathlib import Path
from typing import Callable, Coroutine, TypeVar

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import create_session_factory
from app.logging_setup import setup_logging
from app.models import Base, PhotoKind
from app.repo import NeuroPhotoshootRepo
from app.services.keys import MissingKeyError, configure_keys_service, get_api_key
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
    waiting_height = State()
    waiting_weight = State()
    waiting_hair_color = State()
    waiting_eye_color = State()
    waiting_body_type = State()


class ApiKeyState(StatesGroup):
    waiting_gemini_key = State()
    waiting_nanobanana_key = State()


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
        [KeyboardButton(text="API ключи")],
    ],
    resize_keyboard=True,
)


def _can_reply(event: Message | CallbackQuery) -> bool:
    """Check if we can safely reply to this event (has from_user or chat)."""
    if isinstance(event, CallbackQuery):
        return event.from_user is not None
    if isinstance(event, Message):
        return event.chat is not None
    return False


def with_error_handling(func: Callable[..., Coroutine[None, None, T]]) -> Callable[..., Coroutine[None, None, T | None]]:
    signature = inspect.signature(func)
    accepted_kwargs = {
        name for name, parameter in signature.parameters.items() if parameter.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    }

    def build_context(event: Message | CallbackQuery, kwargs: dict[str, object]) -> dict[str, object]:
        context: dict[str, object] = {
            "handler": func.__name__,
            "update_type": type(event).__name__,
            "user_id": getattr(getattr(event, "from_user", None), "id", None),
            "chat_id": getattr(getattr(event, "chat", None), "id", None),
        }
        if isinstance(event, Message):
            context["event_data"] = event.text or event.caption or ""
        elif isinstance(event, CallbackQuery):
            context["event_data"] = event.data or ""
            context["chat_id"] = context["chat_id"] or getattr(getattr(event.message, "chat", None), "id", None)

        dropped_kwargs = sorted(set(kwargs) - accepted_kwargs - {"dispatcher"})
        if dropped_kwargs:
            context["dropped_kwargs"] = dropped_kwargs
        return context

    async def wrapper(event: Message | CallbackQuery, *args, **kwargs):
        context = build_context(event, kwargs)
        # Guard: from_user required for most handlers; fail fast with clear log
        from_user = getattr(event, "from_user", None)
        if from_user is None and isinstance(event, (Message, CallbackQuery)):
            logger.warning("Update missing from_user | context=%s", context)
            if _can_reply(event):
                try:
                    if isinstance(event, CallbackQuery):
                        await event.answer("Sorry, an internal error occurred.", show_alert=True)
                    else:
                        await event.answer("Sorry, an internal error occurred.")
                except Exception:
                    logger.exception("Failed to send fallback message")
            return None

        try:
            kwargs.pop("dispatcher", None)  # aiogram passes it; handlers don't expect it
            filtered_kwargs = {key: value for key, value in kwargs.items() if key in accepted_kwargs}
            return await func(event, *args, **filtered_kwargs)
        except MissingKeyError:
            logger.warning("Missing API key for handler | context=%s", context)
            if _can_reply(event):
                await event.answer("⚠️ API-ключ не найден. Используйте /set_gemini или /set_nanobanana (см. «API ключи» в меню).")
            return None
        except Exception:
            logger.exception("Handler error | context=%s", context)
            if _can_reply(event):
                try:
                    if isinstance(event, CallbackQuery):
                        await event.answer("Sorry, an internal error occurred.", show_alert=True)
                    else:
                        await event.answer("Sorry, an internal error occurred.")
                except Exception:
                    logger.exception("Failed to send fallback message")
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


# Camera sub-menu A: Technical Settings
LENS_OPTIONS = [
    ("Авто", "auto"),
    ("24mm", "24"),
    ("35mm", "35"),
    ("50mm", "50"),
    ("85mm", "85"),
    ("135mm", "135"),
]
# Aspect ratio: label -> Imagen API code + DB storage
ASPECT_OPTIONS = [
    ("1:1 (Квадрат)", "1:1"),
    ("3:4 (Портрет)", "3:4"),
    ("4:3 (Ландшафт)", "4:3"),
    ("9:16 (Сторис)", "9:16"),
    ("16:9 (Кино)", "16:9"),
]
# Camera sub-menu B: Ракурсы и перспектива (Russian labels per spec)
ANGLE_OPTIONS = [
    ("Вид с дрона", "DRONE_TOP"),
    ("Снизу", "LOW_FROM_BELOW"),
    ("Сбоку (профиль)", "SIDE_PROFILE"),
    ("Голландский угол", "DUTCH_ANGLE"),
    ("Панорама 360", "PANORAMA_360"),
    ("С уровня ног", "FOOT_LEVEL"),
    ("Селфи", "ARM_LENGTH_SELFIE"),
    ("Портрет", "NON_SELFIE_PORTRAIT"),
    ("Авто", "AUTO"),
]
ANGLE_CODE_TO_RU = {code: label for label, code in ANGLE_OPTIONS}


def camera_technical_inline(settings: dict) -> InlineKeyboardMarkup:
    """Sub-menu A: Lens + Aspect Ratio."""
    lens_val = settings.get("lens_mm")
    lens_selected = settings.get("lens_selected", False)
    lens_label = "Авто" if not lens_selected or lens_val is None else f"{lens_val}mm"
    size_label = settings.get("output_size_code", "1:1")

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="◀ Назад в Камеру", callback_data="camera:back")],
        [InlineKeyboardButton(text=f"Объектив: {lens_label}", callback_data="noop")],
    ]
    rows += [[InlineKeyboardButton(text=label, callback_data=f"cam_lens:{val}")] for label, val in LENS_OPTIONS]
    rows.append([InlineKeyboardButton(text=f"Размер фото: {size_label}", callback_data="noop")])
    rows += [[InlineKeyboardButton(text=label, callback_data=f"cam_size:{val}")] for label, val in ASPECT_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def camera_angles_inline(settings: dict) -> InlineKeyboardMarkup:
    """Sub-menu B: Angles & Perspectives."""
    angle_label = settings.get("angle_code", "NON_SELFIE_PORTRAIT")
    angle_ru = next((l for l, c in ANGLE_OPTIONS if c == angle_label), angle_label)

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"◀ Назад в Камеру", callback_data="camera:back")],
        [InlineKeyboardButton(text=f"Ракурс: {angle_ru}", callback_data="noop")],
    ]
    rows += [[InlineKeyboardButton(text=label, callback_data=f"cam_angle:{code}")] for label, code in ANGLE_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def camera_main_inline() -> InlineKeyboardMarkup:
    """Main Camera menu: choose sub-menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Технические настройки", callback_data="camera:technical")],
            [InlineKeyboardButton(text="Ракурсы и перспектива", callback_data="camera:angles")],
        ]
    )


def try_detect_face(path: Path) -> bool | None:
    """Detect if image contains a face. Returns True/False, or None if detection unavailable (fallback = allow save)."""
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        logger.warning("Face detection skipped (missing deps: opencv-python-headless, mediapipe): %s", e)
        return None
    try:
        image = cv2.imread(str(path))
        if image is None:
            return None
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        with mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5) as detector:
            result = detector.process(rgb)
        return bool(result.detections)
    except Exception as e:
        logger.warning("Face detection failed for %s: %s", path, e)
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
async def on_start(message: Message, app_ctx: AppContext, **kwargs: object) -> None:
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
    await message.answer(
        "1. Профиль — укажите рост, вес, цвет волос, глаза, тип телосложения\n"
        "2. Фото — загрузите минимум 1 фото лица\n"
        "3. Сцена — опишите сцену\n"
        "4. API ключи — установите ключи Gemini и Imagen\n"
        "5. Генерация — запустите генерацию"
    )


@router.message(F.text == "API ключи")
@with_error_handling
async def api_keys_menu(message: Message, app_ctx: AppContext) -> None:
    _get_user(app_ctx, message.from_user.id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Установить ключ Gemini", callback_data="api_set:gemini")],
            [InlineKeyboardButton(text="Установить ключ Imagen", callback_data="api_set:nanobanana")],
            [InlineKeyboardButton(text="Справка: Gemini", callback_data="api_help:gemini")],
            [InlineKeyboardButton(text="Справка: Imagen", callback_data="api_help:nanobanana")],
        ]
    )
    await message.answer(
        "Управление API ключами. Выберите действие:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("api_set:"))
@with_error_handling
async def api_set_callback(callback: CallbackQuery, state: FSMContext, app_ctx: AppContext) -> None:
    provider = (callback.data or "").replace("api_set:", "", 1)
    if not callback.message:
        await callback.answer("Ошибка", show_alert=True)
        return
    if provider == "gemini":
        await state.set_state(ApiKeyState.waiting_gemini_key)
        await callback.message.answer("Отправьте ваш Gemini API ключ в следующем сообщении.")
    elif provider == "nanobanana":
        await state.set_state(ApiKeyState.waiting_nanobanana_key)
        await callback.message.answer("Отправьте ваш Imagen API ключ в следующем сообщении.")
    else:
        await callback.answer("Неизвестный сервис", show_alert=True)
        return
    await callback.answer()


@router.message(ApiKeyState.waiting_gemini_key, F.text)
@with_error_handling
async def save_gemini_key_from_state(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    if not message.from_user:
        return
    key = (message.text or "").strip()
    if not key:
        await message.answer("Ключ не может быть пустым. Попробуйте снова.")
        return
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_gemini_key(message.from_user.id, key)
    await state.clear()
    await message.answer("Ключ Gemini сохранён.", reply_markup=MAIN_MENU)


@router.message(ApiKeyState.waiting_nanobanana_key, F.text)
@with_error_handling
async def save_nanobanana_key_from_state(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    if not message.from_user:
        return
    key = (message.text or "").strip()
    if not key:
        await message.answer("Ключ не может быть пустым. Попробуйте снова.")
        return
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_nanobanana_key(message.from_user.id, key)
    await state.clear()
    await message.answer("Ключ Imagen сохранён.", reply_markup=MAIN_MENU)


@router.callback_query(F.data.startswith("api_help:"))
@with_error_handling
async def api_help_callback(callback: CallbackQuery, app_ctx: AppContext) -> None:
    provider = (callback.data or "").replace("api_help:", "", 1)
    if provider == "gemini":
        text = (
            "🔑 Gemini API key (Google AI)\n\n"
            "1. Откройте https://aistudio.google.com/apikey\n"
            "2. Создайте ключ\n"
            "3. Отправьте в чат:\n"
            "<code>/set_gemini ВАШ_КЛЮЧ</code>"
        )
    elif provider == "nanobanana":
        text = (
            "🔑 Imagen (генерация изображений)\n\n"
            "Используется модель Google Imagen (Gemini Image Generation). Тот же ключ, что и для Gemini.\n\n"
            "1. Откройте https://aistudio.google.com/apikey\n"
            "2. Создайте API-ключ (или используйте уже созданный для Gemini)\n"
            "3. Включите доступ к генерации изображений в проекте Google Cloud при необходимости\n"
            "4. Отправьте в чат:\n"
            "<code>/set_nanobanana ВАШ_КЛЮЧ</code>\n\n"
            "Документация: https://cloud.google.com/vertex-ai/docs/generative-ai/image/generate-images"
        )
    else:
        text = "Неизвестный сервис."
    await callback.answer()
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML")


@router.message(Command("set_gemini"))
@with_error_handling
async def set_gemini_key(message: Message, app_ctx: AppContext) -> None:
    if not message.from_user:
        await message.answer("Пользователь не определен.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Использование: /set_gemini <API_KEY>")
        return

    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_gemini_key(message.from_user.id, parts[1].strip())
    await message.answer("Gemini API key сохранен.")


@router.message(Command("set_nanobanana"))
@with_error_handling
async def set_nanobanana_key(message: Message, app_ctx: AppContext) -> None:
    if not message.from_user:
        await message.answer("Пользователь не определен.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Использование: /set_nanobanana <API_KEY>")
        return

    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_nanobanana_key(message.from_user.id, parts[1].strip())
    await message.answer("Ключ Imagen (генерация) сохранён.")


def _format_profile_prompt(profile: object | None) -> str:
    """Build profile_text from structured fields for prompt."""
    if not profile:
        return ""
    parts = []
    if getattr(profile, "height_cm", None):
        parts.append(f"рост {profile.height_cm} см")
    if getattr(profile, "weight_kg", None):
        parts.append(f"вес {profile.weight_kg} кг")
    if getattr(profile, "hair_color", None):
        parts.append(f"волосы {profile.hair_color}")
    if getattr(profile, "eye_color", None):
        parts.append(f"глаза {profile.eye_color}")
    if getattr(profile, "body_type", None):
        parts.append(f"телосложение {profile.body_type}")
    if getattr(profile, "profile_text", None) and profile.profile_text:
        parts.append(profile.profile_text)
    return ", ".join(parts) if parts else ""


@router.message(F.text == "Профиль")
@with_error_handling
async def ask_profile(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        profile = NeuroPhotoshootRepo(session).get_profile(user_id)
    if profile and _format_profile_prompt(profile):
        preview = _format_profile_prompt(profile)
        await message.answer(f"Текущий профиль: {preview}\n\nОбновить? Введите рост в см (например 175):")
    else:
        await message.answer("Введите рост в см (например 175):")
    await state.set_state(ProfileState.waiting_height)


@router.message(ProfileState.waiting_height, F.text)
@with_error_handling
async def save_height(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    text = (message.text or "").strip()
    try:
        height = int(text)
        if 100 <= height <= 250:
            await state.update_data(profile_height=height)
            await state.set_state(ProfileState.waiting_weight)
            await message.answer("Введите вес в кг (например 70):")
        else:
            await message.answer("Рост должен быть от 100 до 250 см. Попробуйте снова.")
    except ValueError:
        await message.answer("Введите число (рост в см).")


@router.message(ProfileState.waiting_weight, F.text)
@with_error_handling
async def save_weight(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    text = (message.text or "").strip()
    try:
        weight = int(text)
        if 30 <= weight <= 200:
            await state.update_data(profile_weight=weight)
            await state.set_state(ProfileState.waiting_hair_color)
            await message.answer("Введите цвет волос (например: тёмно-каштановые, блонд, черные):")
        else:
            await message.answer("Вес должен быть от 30 до 200 кг. Попробуйте снова.")
    except ValueError:
        await message.answer("Введите число (вес в кг).")


@router.message(ProfileState.waiting_hair_color, F.text)
@with_error_handling
async def save_hair_color(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    hair = (message.text or "").strip()
    if not hair or len(hair) < 2:
        await message.answer("Введите цвет волос.")
        return
    await state.update_data(profile_hair=hair[:64])
    await state.set_state(ProfileState.waiting_eye_color)
    await message.answer("Введите цвет глаз (например: карие, голубые, зеленые):")


@router.message(ProfileState.waiting_eye_color, F.text)
@with_error_handling
async def save_eye_color(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    eyes = (message.text or "").strip()
    if not eyes or len(eyes) < 2:
        await message.answer("Введите цвет глаз.")
        return
    await state.update_data(profile_eyes=eyes[:64])
    await state.set_state(ProfileState.waiting_body_type)
    await message.answer("Введите тип телосложения (например: стройное, атлетичное, полное):")


@router.message(ProfileState.waiting_body_type, F.text)
@with_error_handling
async def save_body_type(message: Message, state: FSMContext, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    body = (message.text or "").strip()
    if not body or len(body) < 2:
        await message.answer("Введите тип телосложения.")
        return
    data = await state.get_data()
    parts = []
    if data.get("profile_height"):
        parts.append(f"рост {data['profile_height']} см")
    if data.get("profile_weight"):
        parts.append(f"вес {data['profile_weight']} кг")
    if data.get("profile_hair"):
        parts.append(f"волосы {data['profile_hair']}")
    if data.get("profile_eyes"):
        parts.append(f"глаза {data['profile_eyes']}")
    parts.append(f"телосложение {body}")
    profile_text = ", ".join(parts)
    with app_ctx.session_factory() as session:
        NeuroPhotoshootRepo(session).upsert_profile(
            user_id,
            profile_text=profile_text,
            height_cm=data.get("profile_height"),
            weight_kg=data.get("profile_weight"),
            hair_color=data.get("profile_hair"),
            eye_color=data.get("profile_eyes"),
            body_type=body[:64],
        )
    await state.clear()
    await message.answer("Профиль сохранён.", reply_markup=MAIN_MENU)


@router.message(F.text == "Показать профиль")
@with_error_handling
async def show_profile(message: Message, app_ctx: AppContext) -> None:
    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        profile = repo.get_profile(user_id)
        complete = repo.is_profile_complete(user_id) if profile else False
    text = _format_profile_prompt(profile) if profile else "Профиль ещё не заполнен."
    status = "\n✅ Профиль полный." if complete else "\n⚠️ Заполните все поля (рост, вес, волосы, глаза, телосложение)."
    await message.answer(text + status)


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
    _get_user(app_ctx, message.from_user.id)
    await message.answer("Настройки камеры:", reply_markup=camera_main_inline())


@router.callback_query(F.data.startswith(("camera:", "cam_lens:", "cam_size:", "cam_angle:", "noop")))
@with_error_handling
async def on_camera_callback(callback: CallbackQuery, app_ctx: AppContext) -> None:
    if callback.data == "noop":
        await callback.answer()
        return
    if not callback.message:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return
    user_id = _get_user(app_ctx, callback.from_user.id)
    data_raw = callback.data or ""

    if data_raw == "camera:back":
        await callback.message.edit_text("Настройки камеры:", reply_markup=camera_main_inline())
        await callback.answer()
        return
    if data_raw == "camera:technical":
        with app_ctx.session_factory() as session:
            settings = NeuroPhotoshootRepo(session).get_or_create_shoot_settings(user_id)
        settings_dict = {
            "lens_selected": settings.lens_selected,
            "lens_mm": settings.lens_mm,
            "output_size_code": settings.output_size_code or "1:1",
        }
        await callback.message.edit_text("Технические настройки:", reply_markup=camera_technical_inline(settings_dict))
        await callback.answer()
        return
    if data_raw == "camera:angles":
        with app_ctx.session_factory() as session:
            settings = NeuroPhotoshootRepo(session).get_or_create_shoot_settings(user_id)
        settings_dict = {"angle_code": settings.angle_code or "NON_SELFIE_PORTRAIT"}
        await callback.message.edit_text("Ракурсы и перспектива:", reply_markup=camera_angles_inline(settings_dict))
        await callback.answer()
        return

    if data_raw.startswith("cam_lens:"):
        val = data_raw.replace("cam_lens:", "", 1)
        if val == "auto":
            payload = {"lens_selected": False, "lens_mm": None}
        else:
            try:
                payload = {"lens_selected": True, "lens_mm": int(val)}
            except ValueError:
                await callback.answer("Ошибка", show_alert=True)
                return
    elif data_raw.startswith("cam_size:"):
        payload = {"output_size_code": data_raw.replace("cam_size:", "", 1)}
    elif data_raw.startswith("cam_angle:"):
        payload = {"angle_code": data_raw.replace("cam_angle:", "", 1)}
    else:
        await callback.answer()
        return

    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        repo.update_shoot_settings(user_id, **payload)
        settings = repo.get_or_create_shoot_settings(user_id)

    settings_dict_tech = {
        "lens_selected": settings.lens_selected,
        "lens_mm": settings.lens_mm,
        "output_size_code": settings.output_size_code or "1:1",
    }
    settings_dict_angles = {"angle_code": settings.angle_code}
    if "lens_selected" in payload or "lens_mm" in payload or "output_size_code" in payload:
        try:
            await callback.message.edit_reply_markup(reply_markup=camera_technical_inline(settings_dict_tech))
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.warning("Failed to edit camera markup: %s", e)
    elif "angle_code" in payload:
        try:
            await callback.message.edit_reply_markup(reply_markup=camera_angles_inline(settings_dict_angles))
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.warning("Failed to edit camera markup: %s", e)

    await callback.answer("Сохранено")


@router.message(F.text == "Генерация")
@with_error_handling
async def generate(message: Message, app_ctx: AppContext) -> None:
    if not message.from_user:
        await message.answer("Пользователь не определен.")
        return

    await get_api_key(message.from_user.id, "gemini")
    await get_api_key(message.from_user.id, "nanobanana")

    user_id = _get_user(app_ctx, message.from_user.id)
    with app_ctx.session_factory() as session:
        repo = NeuroPhotoshootRepo(session)
        profile = repo.get_profile(user_id)
        scene = repo.get_scene(user_id)
        face_photos = repo.list_photos(user_id, PhotoKind.FACE)
        full_body_photos = repo.list_photos(user_id, PhotoKind.FULL_BODY)

        if not profile:
            await message.answer("Сначала заполните профиль (рост, вес, цвет волос, цвет глаз, тип телосложения).")
            return
        if not repo.is_profile_complete(user_id):
            await message.answer(
                "Заполните все поля профиля: рост, вес, цвет волос, цвет глаз, тип телосложения. "
                "Используйте меню «Профиль»."
            )
            return
        if len(face_photos) < 5:
            await message.answer("Загрузите 5 фото лица в меню «Фото» перед генерацией.")
            return
        if len(full_body_photos) < 2:
            await message.answer("Загрузите 2 фото в полный рост в меню «Фото» перед генерацией.")
            return

        missing_face = [photo.file_path for photo in face_photos if not Path(photo.file_path).exists()]
        missing_full_body = [photo.file_path for photo in full_body_photos if not Path(photo.file_path).exists()]
        if missing_face or missing_full_body:
            logger.warning(
                "Generate rejected due to missing files on disk",
                extra={
                    "user_id": user_id,
                    "missing_face_count": len(missing_face),
                    "missing_full_body_count": len(missing_full_body),
                },
            )
            await message.answer(
                "⚠️ Часть фото недоступна после перезапуска сервера. "
                "Пожалуйста, заново загрузите фото в меню «Фото»."
            )
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
        scene_preview = (g.final_prompt or "")[:50] + ("..." if len(g.final_prompt or "") > 50 else "")
        lens_str = f"{settings.lens_mm}mm" if (settings.lens_selected and settings.lens_mm) else "Авто"
        angle_str = ANGLE_CODE_TO_RU.get(settings.angle_code, settings.angle_code or "—")
        size_str = settings.output_size_code or "1:1"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Отправить результат", callback_data=f"send_result:{g.id}")]]
        )
        await message.answer(
            f"{g.created_at:%Y-%m-%d %H:%M}\n"
            f"Сцена: {scene_preview}\n"
            f"Линза: {lens_str}\n"
            f"Ракурс: {angle_str}\n"
            f"Размер: {size_str}",
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("send_result:"))
@with_error_handling
async def send_result(callback: CallbackQuery, app_ctx: AppContext, bot: Bot) -> None:
    user_id = _get_user(app_ctx, callback.from_user.id)
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1].strip():
        logger.warning("Invalid send_result callback_data", extra={"data": callback.data})
        await callback.answer("Invalid request", show_alert=True)
        return
    try:
        generation_id = int(parts[1].strip())
    except ValueError:
        logger.warning("Invalid generation_id in callback", extra={"data": callback.data})
        await callback.answer("Invalid request", show_alert=True)
        return
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
    configure_keys_service(settings, session_factory)
    with session_factory() as session:
        Base.metadata.create_all(bind=session.bind)
        # Migration: add new profile columns if missing
        for col, typ in [("hair_color", "VARCHAR(64)"), ("eye_color", "VARCHAR(64)"), ("body_type", "VARCHAR(64)")]:
            try:
                session.execute(text(f"ALTER TABLE profiles ADD COLUMN {col} {typ}"))  # noqa: S608
                session.commit()
            except Exception as e:
                session.rollback()
                if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                    logger.warning("Profile migration for %s failed: %s", col, e)

    app_ctx = AppContext(settings=settings, session_factory=session_factory, storage=storage)

    token = settings.telegram_bot_token
    token_suffix = token[-4:] if len(token) >= 4 else "????"
    # Single Instance Guard: one process, one Bot, one polling loop. Prevents TelegramConflictError.
    logger.info(
        "Single instance guard | pid=%s | token_suffix=%s | drop_pending_updates=True",
        os.getpid(),
        token_suffix,
    )
    bot = Bot(token)
    dp = Dispatcher()
    dp.include_router(router)
    dp["app_ctx"] = app_ctx

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(bot, settings, session_factory, storage, stop_event))

    logger.info("Starting bot polling (single process, no webhook)")
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
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
