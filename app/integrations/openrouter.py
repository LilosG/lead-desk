from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedCopy:
    subject: str
    intro: str
    cta: str
    model: str


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate_email(
        self,
        *,
        business_name: str,
        city: str | None,
        vertical: str | None,
        verified_claim: str | None,
    ) -> GeneratedCopy:
        facts = {
            "business_name": business_name,
            "city": city,
            "vertical": vertical,
            "verified_claim_available": bool(verified_claim),
        }
        system = (
            "You write concise first-touch B2B outreach from Mike at LILOs Growth, a San Diego local SEO and web design agency. "
            "Write in Mike's first-person voice using I/me/my, never third person. The application will insert any verified technical/audit "
            "claim itself after your intro. You must NOT mention website condition, schema, SEO errors, rankings, reviews, PageSpeed, "
            "Google Business Profile, traffic, revenue, map pack position, missing pages, or any other audit finding. Use only the supplied "
            "business name, city, and vertical for light personalization. Write like a real owner-to-owner note, not a marketing template. "
            "Avoid phrases such as 'we work with', 'stand out online', 'quick observation', 'quick note', 'might be worth a conversation', "
            "'I came across your business', and generic compliments. Do not claim an existing relationship with their industry or city. "
            "Keep the tone calm, specific, plain-text, link-free, and non-pushy. Subject should be 3-6 words, neutral, and normally reference "
            "the business name or website without hype. Intro should be one short first-person sentence such as 'I was reviewing [business] "
            "online and noticed one thing worth flagging.' Do not describe that item because the application inserts the verified claim next. "
            "CTA should be one short, low-friction first-person question offering to send the detail or explain the fix. Do not include a "
            "signature, postal address, opt-out text, URLs, or invented facts. Return JSON only with string keys subject, intro, and cta."
        )
        user = (
            "Write the non-claim portions of a first-touch email using these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 220,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
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
            content = data["choices"][0]["message"]["content"]
            parsed = self._parse_json_content(content)
            subject = str(parsed["subject"]).strip()
            intro = str(parsed["intro"]).strip()
            cta = str(parsed["cta"]).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenRouterError("OpenRouter returned an invalid draft payload") from exc

        if not subject or not intro or not cta:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 300:
            raise OpenRouterError("Generated subject exceeds the allowed length")
        combined = f"{subject}\n{intro}\n{cta}"
        if len(combined) > 6000:
            raise OpenRouterError("Generated copy exceeds the allowed length")

        lowered = combined.lower()
        forbidden = (
            "http://",
            "https://",
            "www.",
            "schema",
            "pagespeed",
            "map pack",
            "google business",
            "ranking",
            "rankings",
            "traffic",
            "review count",
            "title tag",
            "mike was",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced a claim, link, or non-first-person phrasing outside verified application facts"
            )

        return GeneratedCopy(
            subject=subject,
            intro=intro,
            cta=cta,
            model=self.model,
        )

    @staticmethod
    def _parse_json_content(content: Any) -> dict[str, Any]:
        if not isinstance(content, str):
            raise TypeError("message content must be text")
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)
