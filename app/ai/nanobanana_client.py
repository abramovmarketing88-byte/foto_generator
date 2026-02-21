from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class NanoBananaError(RuntimeError):
    pass


class NanoBananaClient:
    def __init__(self, settings: Settings):
        self._api_key = settings.nanobanana_api_key
        self._base_url = settings.nanobanana_base_url.rstrip("/")
        self._generate_path = settings.nanobanana_generate_path
        self._timeout_sec = settings.nanobanana_timeout_sec
        self._retries = settings.nanobanana_retries

    async def generate_image(self, final_prompt: str, images: list[bytes], size_code: str) -> bytes:
        payload = {
            "prompt": final_prompt,
            "size_code": size_code,
            "reference_images": [base64.b64encode(image).decode("ascii") for image in images],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}{self._generate_path}"

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    raise NanoBananaError(f"transient_response_status={response.status_code}")
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    data = response.json()
                    image_b64 = data.get("image_b64")
                    if not image_b64:
                        raise NanoBananaError("missing image_b64 in response")
                    return base64.b64decode(image_b64)
                return response.content
            except Exception as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.exception("NanoBanana generation failed after retries")
        raise NanoBananaError("nanobanana_generation_failed") from last_error
