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
            "You write first-touch B2B email copy from Mike at LILOs Growth, a San Diego local SEO and web agency. "
            "The goal is a credible reply from a real local-business owner, not a click, meeting booking, or hard sell. "
            "Write in Mike's first-person voice using I/me/my. Make the note sound individually written, calm, commercially aware, "
            "and easy to answer. The application inserts one independently verified audit observation immediately after your intro, so "
            "you must not invent, repeat, summarize, soften, or expand any technical claim yourself. Never mention website condition, "
            "schema, SEO errors, rankings, reviews, PageSpeed, Google Business Profile, traffic, revenue, map-pack position, missing pages, "
            "or any other audit finding unless it is the supplied verified claim; the application handles that separately. Use only the "
            "business name, city, and vertical as personalization facts. Do not invent a contact name, tenure, service area, customer count, "
            "award, relationship, result, or familiarity with the business. Do not compliment them generically. "
            "\n\n"
            "COPY STANDARD:\n"
            "- Subject: 2-6 words, under 60 characters, neutral and human. Prefer the business name plus a simple context word such as "
            "website, search, or local visibility when natural. Never use RE:, FWD:, urgency, hype, emojis, or clickbait.\n"
            "- Intro: one sentence, usually 10-20 words. Establish that Mike personally looked at the business online without sounding "
            "like a mass-email template. Do not use 'I came across your business', 'quick note', 'quick observation', 'noticed one thing worth "
            "flagging', 'hope you're well', or 'we work with businesses like yours'.\n"
            "- CTA: one short question, usually 8-18 words. Ask for a simple reply and offer one useful next step tied to the observation, "
            "such as sending the exact recommendation or showing what Mike would change. Do not ask to book a call, schedule 15 minutes, "
            "visit a link, download anything, or commit to a project.\n"
            "- Keep it plain-text, professional, low-pressure, and specific. No exclamation points. No buzzwords such as game-changer, "
            "skyrocket, dominate, unlock, leverage, or guaranteed. No claims of free audits, guaranteed results, increased revenue, or "
            "exclusive opportunities. No links.\n"
            "- Do not include a greeting, signature, postal address, opt-out text, URLs, or the verified claim itself; the application adds "
            "the claim and compliance footer.\n"
            "Return JSON only with string keys subject, intro, and cta."
        )
        user = (
            "Write the non-claim portions of one high-quality first-touch email using these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.25,
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

        self._validate_copy(subject=subject, intro=intro, cta=cta)

        return GeneratedCopy(
            subject=subject,
            intro=intro,
            cta=cta,
            model=self.model,
        )

    @staticmethod
    def _validate_copy(*, subject: str, intro: str, cta: str) -> None:
        if not subject or not intro or not cta:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 60 or len(subject.split()) > 8:
            raise OpenRouterError("Generated subject exceeds the outreach copy limit")
        if len(intro) > 240:
            raise OpenRouterError("Generated intro exceeds the outreach copy limit")
        if len(cta) > 220:
            raise OpenRouterError("Generated CTA exceeds the outreach copy limit")

        combined = f"{subject}\n{intro}\n{cta}"
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
            "re:",
            "fwd:",
            "book a call",
            "schedule a call",
            "15 minutes",
            "free audit",
            "game-changer",
            "game changer",
            "skyrocket",
            "dominate",
            "guaranteed",
            "unlock your",
            "i came across your business",
            "quick observation",
            "quick note",
            "noticed one thing worth flagging",
            "hope you're well",
            "hope you are well",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced a claim, link, sales cliché, or disallowed outreach pattern"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if not cta.rstrip().endswith("?"):
            raise OpenRouterError("Generated CTA must be a low-friction question")

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
