from __future__ import annotations

import httpx

from app.core.config import get_settings, resolve_model_alias
from app.domain.models import AIBranch, PromptTemplate


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.llm_api_key
        self.timeout = httpx.Timeout(settings.request_timeout_seconds)

    async def _chat(self, model_alias: str, messages: list[dict[str, str]]) -> str:
        model = resolve_model_alias(model_alias)
        if not self.api_key:
            return "LLM API key is not configured."

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": messages, "temperature": 0.5}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def generate_reply(self, branch: AIBranch, messages: list[dict[str, str]]) -> str:
        return await self._chat(branch.gpt_model.value, messages)

    async def generate_followup(
        self,
        branch: AIBranch,
        prompt_template: PromptTemplate,
        context_data: str,
    ) -> str:
        messages = [
            {"role": "system", "content": prompt_template.content},
            {"role": "user", "content": f"Контекст:\n{context_data}\n\nСформируй follow-up сообщение."},
        ]
        return await self._chat(branch.gpt_model.value, messages)
