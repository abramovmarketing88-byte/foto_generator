from __future__ import annotations

import asyncio
import base64
import json
import logging
from io import BytesIO

import httpx
from PIL import Image

from app.config import Settings
from app.services.keys import get_api_key

logger = logging.getLogger(__name__)


class GeminiAnalyzer:
    def __init__(self, settings: Settings):
        self._model = "gemini-2.0-flash"
        self._retries = settings.gemini_retries

    @staticmethod
    def _optimize_image(image_bytes: bytes) -> bytes:
        with Image.open(BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=85)
            return output.getvalue()

    async def analyze_user_photos(self, user_id: int, face_photos: list[bytes]) -> tuple[str, list[str]]:
        if not face_photos:
            return "", []

        optimized = [self._optimize_image(photo) for photo in face_photos]
        api_key = await get_api_key(user_id, "gemini")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Analyze these face reference photos of the same person. "
                                "Return strictly JSON with keys face_signature_text and warnings. "
                                "face_signature_text should be short and structured. warnings should be a short string array."
                            )
                        },
                        *[
                            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode("ascii")}}
                            for image in optimized
                        ],
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent?key={api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
                raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(raw_text)
                face_signature_text = str(parsed.get("face_signature_text", "")).strip()
                warnings = [str(w).strip() for w in parsed.get("warnings", []) if str(w).strip()]
                return face_signature_text, warnings
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini analysis retry", extra={"attempt": attempt, "max_attempts": self._retries})
                if attempt < self._retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.warning("Gemini analysis failed; continuing without face signature", exc_info=last_error)
        return "", []
