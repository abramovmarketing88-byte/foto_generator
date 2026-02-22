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


class ImagenBillingRequiredError(NanoBananaError):
    """Imagen API requires a billed Google Cloud project (400)."""


# Map UI size codes and menu values to Imagen API aspectRatio.
# Vertex AI / Gemini Image API: use string "1:1", "3:4", "4:3", "9:16", "16:9" (per docs).
# If your API returns 400 on aspectRatio, try ASPECT_RATIO_* enum (see _ASPECT_RATIO_ENUM).
_ASPECT_RATIO_COLON = {
    "SQUARE_1024": "1:1", "LARGE_2048": "1:1",
    "PORTRAIT_1024_1536": "3:4", "IG_1080_1350": "3:4",
    "LANDSCAPE_1536_1024": "4:3", "HD_1920_1080": "16:9",
    "1:1": "1:1", "3:4": "3:4", "4:3": "4:3", "9:16": "9:16", "16:9": "16:9",
}
_ASPECT_RATIO_ENUM = {
    "1:1": "ASPECT_RATIO_1_1",
    "3:4": "ASPECT_RATIO_3_4",
    "4:3": "ASPECT_RATIO_4_3",
    "9:16": "ASPECT_RATIO_9_16",
    "16:9": "ASPECT_RATIO_16_9",
}
_VALID_COLON = frozenset(("1:1", "3:4", "4:3", "9:16", "16:9"))


def _normalize_aspect(size_code: str, use_enum: bool = False) -> str:
    """Return API-ready aspect ratio. use_enum=True for ASPECT_RATIO_* (if API rejects "1:1")."""
    v = _ASPECT_RATIO_COLON.get(size_code) or (size_code if ":" in str(size_code) else "1:1")
    v = v if v in _VALID_COLON else "1:1"
    return _ASPECT_RATIO_ENUM[v] if use_enum else v


class NanoBananaClient:
    """Imagen (Google Gemini Image Generation) client via generativelanguage API."""

    def __init__(self, settings: Settings):
        self._endpoint = "https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict"
        self._timeout_sec = settings.nanobanana_timeout_sec
        self._retries = settings.nanobanana_retries

    async def generate_image(self, user_id: int, final_prompt: str, images: list[bytes], size_code: str) -> bytes:
        """Generate image via Google Imagen API. Reference images are not sent (Imagen text-only format)."""
        aspect = _normalize_aspect(size_code, use_enum=False)
        prompt_trimmed = (final_prompt or "")[:480]
        payload = {
            "instances": [{"prompt": prompt_trimmed}],
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
                    body_full = response.text[:2000]
                    logger.warning(
                        "Imagen API 429/5xx | status=%s | attempt=%s | response=%s",
                        response.status_code, attempt, body_full,
                        extra={"status": response.status_code, "attempt": attempt, "response_body": body_full},
                    )
                    last_error = NanoBananaError(f"status={response.status_code} body={body_full[:1000]}")
                    if attempt < self._retries:
                        await asyncio.sleep(5 * (2 ** (attempt - 1)))
                    continue
                if response.status_code >= 400:
                    body_full = response.text[:2000]
                    logger.warning(
                        "Imagen API 4xx | status=%s | attempt=%s | request_payload=%s | response=%s",
                        response.status_code, attempt, str(payload)[:800], body_full,
                        extra={
                            "status": response.status_code,
                            "attempt": attempt,
                            "request_payload": payload,
                            "response_body": body_full,
                        },
                    )
                    if "only accessible to billed users" in body_full.lower() or "billed users" in body_full.lower():
                        raise ImagenBillingRequiredError(
                            "Imagen is only available with Google Cloud billing. Enable billing: https://console.cloud.google.com/billing"
                        )
                    response.raise_for_status()

                data = response.json()
                predictions = data.get("predictions")
                if not predictions or not isinstance(predictions, list):
                    raise NanoBananaError("missing or invalid predictions in response")
                pred = predictions[0]
                image_b64 = pred.get("bytesBase64Encoded") or pred.get("image_b64")
                if not image_b64:
                    raise NanoBananaError("missing image bytes in prediction")
                return base64.b64decode(image_b64)
            except ImagenBillingRequiredError:
                raise
            except httpx.HTTPStatusError as exc:
                body_full = (exc.response.text if exc.response else "")[:2000]
                if "only accessible to billed users" in body_full.lower() or "billed users" in body_full.lower():
                    raise ImagenBillingRequiredError(
                        "Imagen is only available with Google Cloud billing. Enable billing: https://console.cloud.google.com/billing"
                    )
                logger.warning(
                    "Imagen HTTPStatusError | status=%s | response=%s",
                    exc.response.status_code if exc.response else None, body_full,
                    extra={"response_body": body_full},
                )
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.exception("Imagen generation failed after retries")
        raise NanoBananaError("imagen_generation_failed") from last_error
