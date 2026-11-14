"""One OpenAI Responses API call with web search: who does ChatGPT recommend?"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAISearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchAnswer:
    text: str
    sources: list[dict[str, str]] = field(default_factory=list)
    model: str = ""


class OpenAISearchClient:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def ask(self, prompt: str) -> SearchAnswer:
        try:
            response = requests.post(
                OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "tools": [{"type": "web_search"}], "input": prompt},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OpenAISearchError(f"OpenAI request failed: {exc}") from exc
        if response.status_code != 200:
            raise OpenAISearchError(f"OpenAI returned {response.status_code}: {response.text[:300]}")
        return self.parse(response.json(), self.model)

    @staticmethod
    def parse(payload: dict[str, Any], model: str) -> SearchAnswer:
        texts: list[str] = []
        sources: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in payload.get("output") or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") != "output_text":
                    continue
                texts.append(part.get("text") or "")
                for note in part.get("annotations") or []:
                    url = note.get("url")
                    if note.get("type") == "url_citation" and url and url not in seen:
                        seen.add(url)
                        sources.append({"url": url, "title": note.get("title") or ""})
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            raise OpenAISearchError("OpenAI returned no answer text")
        return SearchAnswer(text=text, sources=sources, model=payload.get("model") or model)


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterSearchClient:
    """The same question, asked of an OpenAI model with web search, through OpenRouter."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def ask(self, prompt: str) -> SearchAnswer:
        slug = self.model if self.model.endswith(":online") else f"{self.model}:online"
        try:
            response = requests.post(
                OPENROUTER_CHAT_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": slug, "messages": [{"role": "user", "content": prompt}]},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OpenAISearchError(f"OpenRouter request failed: {exc}") from exc
        if response.status_code != 200:
            raise OpenAISearchError(f"OpenRouter returned {response.status_code}: {response.text[:300]}")
        return self.parse(response.json(), self.model)

    @staticmethod
    def parse(payload: dict[str, Any], model: str) -> SearchAnswer:
        choices = payload.get("choices") or []
        message = (choices[0].get("message") if choices else None) or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        text = (content or "").strip()
        if not text:
            raise OpenAISearchError("OpenRouter returned no answer text")
        sources: list[dict[str, str]] = []
        seen: set[str] = set()
        for note in message.get("annotations") or []:
            cite = note.get("url_citation") or {}
            url = cite.get("url")
            if note.get("type") == "url_citation" and url and url not in seen:
                seen.add(url)
                sources.append({"url": url, "title": cite.get("title") or ""})
        return SearchAnswer(text=text, sources=sources, model=payload.get("model") or model)
