from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Загрузить 5 фото"), KeyboardButton(text="Выбрать шаблон")],
            [KeyboardButton(text="Мои кредиты/подписка"), KeyboardButton(text="Мои результаты")],
        ],
        resize_keyboard=True,
    )


def mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ИИ-продавец (чат + фоллоу-апы)", callback_data="ai_mode:ai_seller")],
            [InlineKeyboardButton(text="Отчётность и аналитика", callback_data="ai_mode:reports")],
        ]
    )


def templates_keyboard(codes: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=code, callback_data=f"tpl:{code}")] for code in codes]
    )


def branches_keyboard(branches: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=name, callback_data=f"ai_branch:select:{branch_id}")] for branch_id, name in branches]
    if not rows:
        rows = [[InlineKeyboardButton(text="Нет веток", callback_data="ai_branch:none")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prompts_scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="system", callback_data="ai_prompt:scope:system")],
            [InlineKeyboardButton(text="followup", callback_data="ai_prompt:scope:followup")],
            [InlineKeyboardButton(text="summary", callback_data="ai_prompt:scope:summary")],
        ]
    )
