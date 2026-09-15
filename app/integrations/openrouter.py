from __future__ import annotations

import json
import re
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
        # City and vertical are deliberately excluded from model context. They
        # are operational metadata, not recipient-facing personalization.
        facts = {
            "business_name": business_name,
            "verified_claim_available": bool(verified_claim),
        }
        system = self._system_prompt()
        user = (
            "Write one restrained, genuinely human note using only these facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )

        subject, body = self._request_copy(
            system=system,
            user=user,
            temperature=0.45,
        )
        subject, body = self._ensure_finding_slot(
            subject=subject,
            body=body,
            system=system,
            user=user,
            has_verified_claim=bool(verified_claim),
        )

        try:
            self._validate_copy(
                subject=subject,
                body=body,
                has_verified_claim=bool(verified_claim),
                business_name=business_name,
                city=city,
                vertical=vertical,
            )
        except OpenRouterError as exc:
            # One quality-repair pass is allowed. Model noncompliance should not
            # leak into a draft as invented personalization or unsupported impact.
            repair_user = (
                user
                + "\n\nThe previous draft violated this constraint: "
                + str(exc)
                + ". Rewrite it from scratch. Before the verified-finding token, "
                + "you may only greet the recipient and neutrally say you looked at this business's site. "
                + "Do not mention any page detail, service area, service, hours, reviews, contact information, "
                + "or anything else you observed. The verified token is the ONLY finding. After the token, "
                + "do not add a benefit, consequence, prediction, or second observation."
            )
            subject, body = self._request_copy(
                system=system,
                user=repair_user,
                temperature=0.15,
            )
            subject, body = self._ensure_finding_slot(
                subject=subject,
                body=body,
                system=system,
                user=repair_user,
                has_verified_claim=bool(verified_claim),
            )
            try:
                self._validate_copy(
                    subject=subject,
                    body=body,
                    has_verified_claim=bool(verified_claim),
                    business_name=business_name,
                    city=city,
                    vertical=vertical,
                )
            except OpenRouterError:
                subject, body = self._safe_fallback(
                    business_name=business_name,
                    has_verified_claim=bool(verified_claim),
                )
                self._validate_copy(
                    subject=subject,
                    body=body,
                    has_verified_claim=bool(verified_claim),
                    business_name=business_name,
                    city=city,
                    vertical=vertical,
                )

        return GeneratedCopy(
            subject=subject,
            body=body,
            model=self.model,
        )

    @staticmethod
    def _system_prompt() -> str:
        return f"""
You write one short first-touch email from Mike at LILOs Growth to one real local business owner.

This must feel like Mike personally opened this specific business's website/profile and sent a normal note. It must NOT read like a cold-email sequence, lead-gen template, audit pitch, prospecting list, mail merge, or AI copy.

Use only the supplied business name and the existence of one verified finding. Do not invent a contact name, relationship, result, urgency, customer impact, ranking impact, revenue impact, or ANY second finding. Do not imply Mike was browsing, comparing, researching, or checking out other businesses.

The verified finding itself is controlled by the application. If verified_claim_available is true, place the exact token {CLAIM_TOKEN} exactly once in the body. That token is the ONLY website/profile observation you are allowed to make. Do not describe any service area, service, page, contact detail, hours, review, content, design, or other site detail before or after the token. Do not explain or paraphrase the token. Do not add a benefit, harm, prediction, significance claim, or consequence. If no verified finding is available, do not use the token.

The words before the token may do only two things: greet the recipient and neutrally state that Mike looked at this business's site/profile. Nothing else. Put the token early in the note, no later than the first substantive paragraph.

Write the WHOLE note as one coherent message. Do not output separate intro / finding / CTA fields.

STYLE:
- Subject should usually just be the business name, or at most the business name plus one ordinary word such as "website". No city, industry, urgency, or sales language.
- Body: 30-65 words before Mike's signature/footer, usually 2 short paragraphs.
- A simple "Hi," is fine, but do not use fake familiarity.
- Use contractions and normal spoken business English.
- The closing should be incidental and concrete: offer to point to the exact spot, send a screenshot, or leave it there. Do not pitch services or explain why the finding matters.
- Vary syntax naturally. Do not force the same opening or closing pattern every time.
- Plain text only.

DO NOT USE:
- "quick note", "quick observation", "worth flagging", "noticed one thing", "I was reviewing", "I came across your business", "hope you're well"
- "checking out", "looking at other", "researching", "comparing", or any wording that reveals a prospecting list or category search
- "Want me to send over", "Would you be open to", "Would it be useful if", "Happy to send over", "book a call", "schedule a call"
- "quick fix", "small thing", "easy fix", "could help", "might help", "may help", "should help", "could improve", "make it easier", or any other claim about the effect or value of the finding
- "online presence", "grow your business", "increase leads", "you're losing customers", "rankings", "traffic", "free audit"
- SEO jargon in your own words such as schema, PageSpeed, map pack, title tag, or Google Business Profile
- generic compliments, hype, exclamation points, links, or marketing language

Do not include Mike's name, company, postal address, opt-out language, or a signature. The application adds those after the note.

Return JSON only with string keys "subject" and "body".
""".strip()

    def _ensure_finding_slot(
        self,
        *,
        subject: str,
        body: str,
        system: str,
        user: str,
        has_verified_claim: bool,
    ) -> tuple[str, str]:
        if not has_verified_claim or body.count(CLAIM_TOKEN) == 1:
            return subject, body

        repair_user = (
            user
            + "\n\nYour previous draft omitted or altered the required verified-finding slot. "
            + f"Rewrite the note and include the exact literal token {CLAIM_TOKEN} exactly once. "
            + "Do not paraphrase it, quote it, add a consequence, or add another finding."
        )
        subject, body = self._request_copy(
            system=system,
            user=repair_user,
            temperature=0.2,
        )
        if body.count(CLAIM_TOKEN) != 1:
            body = self._insert_verified_finding_slot(body)
        return subject, body

    def _request_copy(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
    ) -> tuple[str, str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
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

        return subject, body

    @staticmethod
    def _insert_verified_finding_slot(body: str) -> str:
        cleaned = body.replace(CLAIM_TOKEN, "").strip()
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        if not paragraphs:
            return CLAIM_TOKEN

        target_index = 0
        if paragraphs[0].lower().rstrip() in {"hi", "hi,", "hello", "hello,"} and len(paragraphs) > 1:
            target_index = 1

        target = paragraphs[target_index]
        match = re.search(r"[.!?](?:\s|$)", target)
        if match:
            insert_at = match.end()
            target = (
                target[:insert_at].rstrip()
                + " "
                + CLAIM_TOKEN
                + " "
                + target[insert_at:].lstrip()
            ).strip()
        else:
            target = f"{target} {CLAIM_TOKEN}".strip()

        paragraphs[target_index] = target
        return "\n\n".join(paragraphs)

    @staticmethod
    def _safe_fallback(*, business_name: str, has_verified_claim: bool) -> tuple[str, str]:
        subject = business_name
        if has_verified_claim:
            body = (
                f"Hi,\n\nI was on {business_name}'s website earlier. {CLAIM_TOKEN}\n\n"
                "If you want, I can point to the exact place I'm referring to or send a screenshot. "
                "No need to reply if it's already on your list."
            )
        else:
            body = (
                f"Hi,\n\nI was on {business_name}'s website earlier. "
                "If you want, I can send over the specific thing I was looking at. "
                "No need to reply if it's already on your list."
            )
        return subject, body

    @staticmethod
    def _validate_copy(
        *,
        subject: str,
        body: str,
        has_verified_claim: bool,
        business_name: str | None = None,
        city: str | None = None,
        vertical: str | None = None,
    ) -> None:
        if not subject or not body:
            raise OpenRouterError("OpenRouter returned incomplete draft copy")
        if len(subject) > 55 or len(subject.split()) > 5:
            raise OpenRouterError("Generated subject exceeds the outreach copy limit")

        body_words = len(body.split())
        if body_words < 25 or body_words > 80:
            raise OpenRouterError("Generated body is outside the first-touch length range")

        token_count = body.count(CLAIM_TOKEN)
        if has_verified_claim and token_count != 1:
            raise OpenRouterError("Generated body did not preserve the verified finding slot")
        if not has_verified_claim and token_count:
            raise OpenRouterError("Generated body inserted an unsupported finding slot")

        if has_verified_claim:
            prefix = body.split(CLAIM_TOKEN, 1)[0].lower()
            # Before the immutable finding, the model may only establish that
            # Mike looked at this business's site. Any separate observation is
            # unverified personalization and must be rejected.
            unverified_observation_terms = (
                "noticed",
                "saw ",
                "found ",
                "spotted",
                "specific about",
                "service area",
                "services are",
                "listed",
                "hours",
                "reviews",
                "contact page",
                "contact info",
                "pricing",
                "menu",
                "photos",
                "content",
                "design",
            )
            if any(term in prefix for term in unverified_observation_terms):
                raise OpenRouterError(
                    "Generated copy introduced an unverified observation before the verified finding"
                )
            prefix_words = len(prefix.replace("hi,", "").replace("hello,", "").split())
            if prefix_words > 24:
                raise OpenRouterError(
                    "Generated copy delayed the verified finding behind unsupported setup language"
                )

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
            "quick fix",
            "easy fix",
            "small thing",
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
            "checking out",
            "looking at other",
            "researching businesses",
            "comparing businesses",
            "could help",
            "might help",
            "may help",
            "should help",
            "could improve",
            "might improve",
            "may improve",
            "should improve",
            "help people",
            "help customers",
            "help google",
            "make it easier",
            "get the right info",
            "get found",
            "show up better",
        )
        if any(token in lowered for token in forbidden):
            raise OpenRouterError(
                "Generated copy introduced prospect-list language, an unsupported consequence, sales cliché, jargon, or disallowed outreach pattern"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if ":" in subject or " - " in subject or " — " in subject:
            raise OpenRouterError("Generated subject used a templated subject pattern")

        if city and city.lower() in subject.lower():
            raise OpenRouterError("Generated subject added an unnecessary city qualifier")

        body_scope = body.lower()
        if business_name:
            body_scope = body_scope.replace(business_name.lower(), "")
        if city and city.lower() in body_scope:
            raise OpenRouterError("Generated body exposed geographic prospecting context")
        if vertical:
            vertical_terms = {vertical.lower(), vertical.lower().replace("_", " ")}
            for term in vertical_terms:
                if term and term in body_scope:
                    raise OpenRouterError("Generated body exposed category prospecting context")

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
