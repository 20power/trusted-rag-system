from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class ModelClientError(RuntimeError):
    pass


class OpenAICompatibleChatClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.settings.llm_is_configured:
            raise ModelClientError("生成模型未完整配置")

        base_url = self.settings.llm_base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        try:
            with httpx.Client(
                timeout=self.settings.llm_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelClientError(f"模型服务调用失败：{exc}") from exc

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelClientError("模型响应不符合 OpenAI-compatible 格式") from exc
        if not isinstance(content, str) or not content.strip():
            raise ModelClientError("模型返回了空答案")
        return content.strip()
