from __future__ import annotations

import json
from typing import Any

import requests

from app.integrations.openrouter import (
    OPENROUTER_CHAT_URL,
    OpenRouterClient,
    OpenRouterError,
)


OUTREACH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


class StructuredOpenRouterClient(OpenRouterClient):
    """OpenRouter client for models with enforced structured-output support.

    GPT-5-series models can spend completion tokens on internal reasoning and
    support JSON-schema response_format. Keep reasoning minimal for this small
    copy task and reserve enough completion budget for the actual JSON body.
    """

    def _request_copy(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
    ) -> tuple[str, str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": 500,
            "reasoning": {
                "effort": "minimal",
                "exclude": True,
            },
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "outreach_email",
                    "strict": True,
                    "schema": OUTREACH_RESPONSE_SCHEMA,
                },
            },
            "provider": {
                "require_parameters": True,
            },
        }

        # The structured contract is more important than sampling variance for
        # this small deterministic outreach task. Keep the inherited caller API
        # stable without depending on temperature for GPT-5-series requests.
        _ = temperature

        try:
            response = requests.post(
                OPENROUTER_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://lead-desk-alpha.vercel.app",
                    "X-Title": "LILOs Growth Lead Desk",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OpenRouterError("OpenRouter request failed") from exc

        if not response.ok:
            detail = response.text[:500]
            raise OpenRouterError(
                f"OpenRouter returned {response.status_code}: {detail}"
            )

        try:
            data = response.json()
            message = data["choices"][0]["message"]
            content = message["content"]
            parsed = self._parse_structured_content(content)
            subject = str(parsed["subject"]).strip()
            body = str(parsed["body"]).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenRouterError("OpenRouter returned an invalid structured draft payload") from exc

        if not subject or not body:
            raise OpenRouterError("OpenRouter returned an incomplete structured draft payload")

        return subject, body

    @staticmethod
    def _parse_structured_content(content: Any) -> dict[str, Any]:
        if isinstance(content, str):
            return json.loads(content.strip())

        # Be tolerant of typed content arrays if provider routing returns one
        # rather than a plain chat-completions text string.
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            if parts:
                return json.loads("".join(parts).strip())

        raise TypeError("structured message content must contain JSON text")
