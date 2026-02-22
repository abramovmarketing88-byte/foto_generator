from aiogram import Dispatcher

from app.bot.main import router


def main() -> None:
    dp = Dispatcher()
    dp.include_router(router)

    message_handlers = len(dp.message.handlers)
    callback_handlers = len(dp.callback_query.handlers)

    if message_handlers == 0:
        raise RuntimeError("No message handlers registered")
    if callback_handlers == 0:
        raise RuntimeError("No callback handlers registered")

    print(
        f"Router smoke test passed: message_handlers={message_handlers}, "
        f"callback_handlers={callback_handlers}"
    )


if __name__ == "__main__":
    main()
