from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import get_settings


class NanoBananaClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.nanobanana_base_url.rstrip("/")
        self.api_key = settings.nanobanana_api_key
        self.timeout = httpx.Timeout(settings.request_timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def enroll(self, images_base64: list[str], user_tag: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/enroll",
                json={"images": images_base64, "user_tag": user_tag},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data["identity_id"]

    async def generate(
        self,
        identity_id: str,
        template_code: str,
        prompt_override: str | None,
        width: int,
        height: int,
        num_outputs: int,
    ) -> list[bytes | str]:
        payload: dict[str, Any] = {
            "identity_id": identity_id,
            "template_id": template_code,
            "prompt_override": prompt_override,
            "width": width,
            "height": height,
            "num_outputs": num_outputs,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/generate",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if "images_base64" in data:
                return [base64.b64decode(item) for item in data["images_base64"]]
            return data.get("image_urls", [])

    async def download_url(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
