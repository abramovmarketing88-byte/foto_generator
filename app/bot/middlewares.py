import time

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from redis.asyncio import Redis


class CooldownMiddleware(BaseMiddleware):
    def __init__(self, redis: Redis, seconds: int = 5) -> None:
        self.redis = redis
        self.seconds = seconds

    async def __call__(self, handler, event: TelegramObject, data):
        if isinstance(event, Message) and event.from_user:
            key = f"cooldown:{event.from_user.id}"
            now = int(time.time())
            prev = await self.redis.get(key)
            if prev and now - int(prev) < self.seconds:
                await event.answer("Слишком часто. Подождите пару секунд.")
                return
            await self.redis.set(key, str(now), ex=self.seconds)
        return await handler(event, data)
