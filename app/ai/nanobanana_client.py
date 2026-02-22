from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import Settings
from app.services.keys import get_api_key

logger = logging.getLogger(__name__)


class NanoBananaError(RuntimeError):
    pass


_SIZE_TO_ASPECT = {
    "SQUARE_1024": "1:1", "LARGE_2048": "1:1",
    "PORTRAIT_1024_1536": "3:4", "IG_1080_1350": "3:4",
    "LANDSCAPE_1536_1024": "4:3", "HD_1920_1080": "16:9",
}


class NanoBananaClient:
    """Imagen (Google Gemini Image Generation) client via generativelanguage API."""

    def __init__(self, settings: Settings):
        self._endpoint = "https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict"
        self._timeout_sec = settings.nanobanana_timeout_sec
        self._retries = settings.nanobanana_retries

    async def generate_image(self, user_id: int, final_prompt: str, images: list[bytes], size_code: str) -> bytes:
        """Generate image via Google Imagen API. Reference images are not sent (Imagen text-only format)."""
        aspect = _SIZE_TO_ASPECT.get(size_code, size_code if ":" in str(size_code) else "1:1")
        payload = {
            "instances": [{"prompt": final_prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": aspect},
        }
        api_key = await get_api_key(user_id, "nanobanana")
        url = f"{self._endpoint}?key={api_key}"
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    raise NanoBananaError(f"transient_response_status={response.status_code}")
                if response.status_code >= 400:
                    err_body = response.text[:500]
                    logger.warning("Imagen API error", extra={"status": response.status_code, "body": err_body})
                    response.raise_for_status()

                data = response.json()
                predictions = data.get("predictions")
                if not predictions or not isinstance(predictions, list):
                    raise NanoBananaError("missing or invalid predictions in response")
                pred = predictions[0]
                image_b64 = pred.get("bytesBase64Encoded")
                if not image_b64:
                    image_b64 = pred.get("image_b64")
                if not image_b64:
                    raise NanoBananaError("missing image bytes in prediction")
                return base64.b64decode(image_b64)
            except httpx.HTTPStatusError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.exception("Imagen generation failed after retries")
        raise NanoBananaError("imagen_generation_failed") from last_error
