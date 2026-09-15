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
            "verified_claim": verified_claim,
        }
        system = (
            "You write first-touch B2B email copy from Mike at LILOs Growth, a San Diego local SEO and web agency. "
            "The goal is a credible reply from a real local-business owner, not a click, meeting booking, or hard sell. "
            "Write in Mike's first-person voice using I/me/my. Make the note sound individually written, calm, commercially aware, "
            "and easy to answer. The application will insert the supplied verified_claim verbatim immediately after your intro. "
            "You may read that claim only to keep the subject, intro, and CTA contextually aligned. You must not repeat it, paraphrase it, "
            "expand it, add consequences, predict results, or introduce any additional finding. If the verified claim is about the website, "
            "keep the framing about the website. If it is about search visibility, reviews, GBP, or another area, frame only around that area. "
            "Never broaden a website finding into 'local search', 'online presence', rankings, traffic, leads, revenue, or visibility unless those "
            "ideas are explicitly present in the verified claim. Use only the supplied business name, city, vertical, and verified claim. "
            "Do not invent a contact name, tenure, service area, customer count, award, relationship, result, or familiarity with the business. "
            "Do not compliment them generically.\n\n"
            "COPY STANDARD:\n"
            "- Subject: 2-5 words, under 55 characters, neutral and natural. Prefer the business name plus the narrow context actually supported "
            "by the verified claim, such as 'website'. Do not use 'search' unless the verified claim itself is about search. Never use RE:, FWD:, "
            "urgency, hype, emojis, or clickbait.\n"
            "- Intro: exactly one short sentence, usually 8-16 words. State only that Mike looked at the relevant surface before reaching out. "
            "For a website claim, a strong pattern is 'I took a look at [business]'s website before reaching out.' Avoid filler about the city, "
            "industry, online presence, or local search unless the verified claim requires it.\n"
            "- CTA: one short question, usually 5-12 words. Ask for a simple reply and offer one concrete next step. Prefer direct language such as "
            "'Want me to send over the fix I'd make?' or 'Want me to send over the recommendation?' Do not use 'Would you be open to me...', "
            "'Would it be useful if...', 'exact change I'd recommend', 'book a call', 'schedule time', or any multi-step ask.\n"
            "- Keep it plain-text, professional, low-pressure, and specific. No exclamation points. No buzzwords such as game-changer, skyrocket, "
            "dominate, unlock, leverage, guaranteed, improve your online presence, or grow your business. No claims of free audits, guaranteed results, "
            "increased revenue, or exclusive opportunities. No links.\n"
            "- Do not include a greeting, signature, postal address, opt-out text, URLs, or the verified claim itself; the application adds the claim "
            "and compliance footer.\n"
            "Return JSON only with string keys subject, intro, and cta."
        )
        user = (
            "Write the non-claim portions of one high-quality first-touch email using these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 180,
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

        self._validate_copy(
            subject=subject,
            intro=intro,
            cta=cta,
            verified_claim=verified_claim,
        )

        return GeneratedCopy(
            subject=subject,
            intro=intro,
            cta=cta,
            model=self.model,
        )

    @staticmethod
    def _validate_copy(
        *,
        subject: str,
        intro: str,
        cta: str,
        verified_claim: str | None = None,
    ) -> None:
        if not subject or not intro or not cta:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 55 or len(subject.split()) > 6:
            raise OpenRouterError("Generated subject exceeds the outreach copy limit")
        if len(intro) > 180:
            raise OpenRouterError("Generated intro exceeds the outreach copy limit")
        if len(cta) > 140:
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
            "would you be open to me",
            "would it be useful if",
            "exact change i'd recommend",
            "exact change i’d recommend",
            "online presence",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced a claim, link, sales cliché, or disallowed outreach pattern"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if not cta.rstrip().endswith("?"):
            raise OpenRouterError("Generated CTA must be a low-friction question")

        claim_lower = (verified_claim or "").lower()
        unsupported_context = (
            ("local search", "search"),
            ("search results", "search"),
            ("visibility", "visibility"),
            ("rank", "rank"),
            ("reviews", "review"),
        )
        for phrase, required_token in unsupported_context:
            if phrase in lowered and required_token not in claim_lower:
                raise OpenRouterError(
                    "Generated copy introduced context not supported by the verified claim"
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
