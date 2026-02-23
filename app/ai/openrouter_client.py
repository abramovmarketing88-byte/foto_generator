from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import Settings
from app.services.keys import get_api_key

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self._endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self._timeout_sec = settings.nanobanana_timeout_sec
        self._retries = settings.nanobanana_retries

    async def generate_image(self, user_id: int, final_prompt: str, images: list[bytes], size_code: str) -> bytes:
        api_key = await get_api_key(user_id, "openrouter")
        content: list[dict[str, object]] = [{"type": "text", "text": (final_prompt or "")[:1200]}]
        for image in images[:4]:
            b64 = base64.b64encode(image).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        payload = {
            "model": "google/gemini-3-pro-image-preview",
            "modalities": ["image", "text"],
            "messages": [{"role": "user", "content": content}],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(self._endpoint, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    body = response.text[:1500]
                    last_error = OpenRouterError(f"status={response.status_code} body={body}")
                    if attempt < self._retries:
                        await asyncio.sleep(2 ** (attempt - 1))
                    continue
                response.raise_for_status()
                result = response.json()
                image_url = (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("images", [{}])[0]
                    .get("image_url", {})
                    .get("url")
                )
                if not image_url:
                    raise OpenRouterError("missing image_url in response")
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    image_response = await client.get(image_url)
                image_response.raise_for_status()
                return image_response.content
            except Exception as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        raise OpenRouterError("openrouter_generation_failed") from last_error
