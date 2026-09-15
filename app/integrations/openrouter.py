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
            "You write a short first-touch email from Mike at LILOs Growth to one local business owner. "
            "It must read like a real person looked at this specific business and wrote a normal note, not like a sales sequence, mail merge, audit blast, or AI template. "
            "Use only the supplied business name, city, vertical, and verified claim. Never invent a contact name, relationship, result, urgency, familiarity, or additional finding. "
            "The application inserts the verified claim as a separate paragraph after your intro, so do not repeat, paraphrase, explain, dramatize, or add consequences to that claim. "
            "If the claim is technical, keep your surrounding copy plain-English and conversational.\n\n"
            "VOICE AND STRUCTURE:\n"
            "- Sound like a concise owner-to-owner note. Natural, calm, specific, and understated.\n"
            "- Subject: 1-4 words, usually the business name or business name + 'website'. Do not add the city unless the verified claim itself is geographic. No colons, dashes, urgency, clickbait, RE:, FWD:, or marketing language.\n"
            "- Intro: one short sentence, generally 7-16 words. It may say you looked at the site/profile, but avoid canned outreach language. Good examples of tone: 'I took a look at TNT Electric's site earlier.' or 'I was on TNT Electric's website earlier.' Do not copy these mechanically.\n"
            "- Closing: one short low-pressure sentence. Prefer natural wording like 'Happy to send over what I'd change if it's useful.' or 'I can send over the specific fix if you'd like.' It does not have to be a question.\n"
            "- Keep the generated subject + intro + closing under 45 words total. The application adds the verified finding and compliance footer separately.\n\n"
            "NEVER USE THESE PATTERNS:\n"
            "- 'quick note', 'quick observation', 'worth flagging', 'noticed one thing', 'I was reviewing', 'I came across your business', 'hope you're well'\n"
            "- 'Want me to send over...', 'Would you be open to...', 'Would it be useful if...', 'book a call', 'schedule a call'\n"
            "- 'online presence', 'grow your business', 'increase leads', 'you're losing customers', 'rankings', 'traffic', or similar consequences unless literally present in the verified claim\n"
            "- SEO jargon such as schema, title tag, PageSpeed, map pack, or Google Business Profile in the generated intro/closing\n"
            "- generic compliments, fake personalization, exclamation points, links, or claims of a free audit\n\n"
            "Do not include a greeting, signature, postal address, opt-out text, URL, or the verified claim itself. "
            "Return JSON only with string keys subject, intro, and cta."
        )
        user = (
            "Write the non-claim portions of one genuinely human first-touch email using these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.35,
            "max_tokens": 160,
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
            business_name=business_name,
            city=city,
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
        business_name: str | None = None,
        city: str | None = None,
    ) -> None:
        if not subject or not intro or not cta:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 55 or len(subject.split()) > 5:
            raise OpenRouterError("Generated subject exceeds the outreach copy limit")
        if len(intro) > 180:
            raise OpenRouterError("Generated intro exceeds the outreach copy limit")
        if len(cta) > 140:
            raise OpenRouterError("Generated CTA exceeds the outreach copy limit")
        if len((subject + " " + intro + " " + cta).split()) > 45:
            raise OpenRouterError("Generated copy is too long for first-touch outreach")

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
            "grow your business",
            "increase leads",
            "losing customers",
            "i came across your business",
            "quick observation",
            "quick note",
            "worth flagging",
            "noticed one thing",
            "i was reviewing",
            "hope you're well",
            "hope you are well",
            "want me to send over",
            "would you be open to",
            "would it be useful if",
            "online presence",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced a claim, sales cliché, jargon, or disallowed outreach pattern"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if ":" in subject or " - " in subject or " — " in subject:
            raise OpenRouterError("Generated subject used a templated subject pattern")

        if city and city.lower() in subject.lower():
            claim_lower = (verified_claim or "").lower()
            if city.lower() not in claim_lower:
                raise OpenRouterError("Generated subject added an unnecessary city qualifier")

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

        if business_name and business_name.lower() not in subject.lower():
            if len(subject.split()) > 2:
                raise OpenRouterError("Generated subject is not anchored to the business")

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
