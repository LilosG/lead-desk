from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
CLAIM_TOKEN = "[[VERIFIED_FINDING]]"


class OpenRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedCopy:
    subject: str
    body: str
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
        system = f"""
You write one short first-touch email from Mike at LILOs Growth to a real local business owner.

This must feel like Mike personally opened the business's website/profile and sent a normal note. It must NOT read like a cold-email sequence, lead-gen template, audit pitch, mail merge, or AI copy.

You may use only the supplied business name, city, vertical, and the existence of a verified finding. Do not invent a contact name, relationship, result, urgency, customer impact, ranking impact, revenue impact, or any second finding.

The verified finding itself is controlled by the application. If verified_claim_available is true, place the exact token {CLAIM_TOKEN} exactly once inside the body where the observation naturally belongs. Do not explain or paraphrase the token and do not add a consequence to it. The application replaces it after generation. If no verified finding is available, do not use the token.

Write the WHOLE note as one coherent message. Do not output separate intro / finding / CTA blocks.

STYLE:
- Subject should usually just be the business name, or at most the business name plus one ordinary word such as "website". Do not stuff the city into the subject.
- Body: 35-75 words before Mike's signature/footer, usually 2 short paragraphs.
- A simple "Hi," is fine, but do not use fake familiarity.
- Use contractions and normal spoken business English.
- The closing should feel incidental, not like a conversion CTA. It can offer to point out the exact change, send a screenshot, or leave it there. It does not need to be a question.
- Vary syntax naturally. Do not force the same opening or closing pattern every time.
- Plain text only.

DO NOT USE:
- "quick note", "quick observation", "worth flagging", "noticed one thing", "I was reviewing", "I came across your business", "hope you're well"
- "Want me to send over", "Would you be open to", "Would it be useful if", "Happy to send over", "book a call", "schedule a call"
- "online presence", "grow your business", "increase leads", "you're losing customers", "rankings", "traffic", "free audit"
- SEO jargon in your own words such as schema, PageSpeed, map pack, title tag, or Google Business Profile
- generic compliments, hype, exclamation points, links, or marketing language

Do not include Mike's name, company, postal address, opt-out language, or a signature. The application adds those after the note.

Return JSON only with string keys "subject" and "body".
""".strip()
        user = (
            "Write one restrained, genuinely human note using only these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.55,
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
            body = str(parsed["body"]).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenRouterError("OpenRouter returned an invalid draft payload") from exc

        self._validate_copy(
            subject=subject,
            body=body,
            has_verified_claim=bool(verified_claim),
            business_name=business_name,
            city=city,
        )

        return GeneratedCopy(
            subject=subject,
            body=body,
            model=self.model,
        )

    @staticmethod
    def _validate_copy(
        *,
        subject: str,
        body: str,
        has_verified_claim: bool,
        business_name: str | None = None,
        city: str | None = None,
    ) -> None:
        if not subject or not body:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 55 or len(subject.split()) > 5:
            raise OpenRouterError("Generated subject exceeds the outreach copy limit")

        body_words = len(body.split())
        if body_words < 25 or body_words > 90:
            raise OpenRouterError("Generated body is outside the first-touch length range")

        token_count = body.count(CLAIM_TOKEN)
        if has_verified_claim and token_count != 1:
            raise OpenRouterError("Generated body did not preserve the verified finding slot")
        if not has_verified_claim and token_count:
            raise OpenRouterError("Generated body inserted an unsupported finding slot")

        combined = f"{subject}\n{body}"
        lowered = combined.lower()
        forbidden = (
            "http://",
            "https://",
            "www.",
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
            "happy to send over",
            "online presence",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced a sales cliché, jargon, or disallowed outreach pattern"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if ":" in subject or " - " in subject or " — " in subject:
            raise OpenRouterError("Generated subject used a templated subject pattern")

        if city and city.lower() in subject.lower():
            raise OpenRouterError("Generated subject added an unnecessary city qualifier")

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
