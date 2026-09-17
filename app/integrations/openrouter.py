from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class OutreachStyleBrief:
    """Rhetorical variation only. Never authorizes additional prospect facts."""

    subject_mode: str
    greeting_mode: str
    opener_mode: str
    close_mode: str
    rhythm_mode: str


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

    @staticmethod
    def _style_brief(business_name: str) -> OutreachStyleBrief:
        """Assign a stable style fingerprint without changing recipient facts."""

        digest = hashlib.sha256(business_name.encode("utf-8")).digest()
        subject_modes = (
            "business_name_only",
            "business_name_plus_website",
            "plain_two_or_three_word_subject_anchored_to_business",
        )
        greeting_modes = (
            "simple_hi",
            "no_standalone_greeting",
            "brief_hello",
        )
        opener_modes = (
            "finding_first",
            "one_neutral_website_context_sentence_then_finding",
            "business_name_context_then_finding",
            "direct_note_with_finding_in_first_substantive_paragraph",
        )
        close_modes = (
            "brief_question_about_showing_the_exact_location",
            "plain_offer_to_send_the_specific_detail",
            "no_pressure_offer_without_asking_for_a_call",
            "short_acknowledgement_that_no_reply_is_needed_if_already_known",
            "brief_offer_to_clarify_what_was_checked",
        )
        rhythm_modes = (
            "two_short_paragraphs",
            "three_compact_paragraphs",
            "one_compact_body_with_a_short_final_line",
        )

        return OutreachStyleBrief(
            subject_mode=subject_modes[digest[0] % len(subject_modes)],
            greeting_mode=greeting_modes[digest[1] % len(greeting_modes)],
            opener_mode=opener_modes[digest[2] % len(opener_modes)],
            close_mode=close_modes[digest[3] % len(close_modes)],
            rhythm_mode=rhythm_modes[digest[4] % len(rhythm_modes)],
        )

    def generate_email(
        self,
        *,
        business_name: str,
        city: str | None,
        vertical: str | None,
        verified_claim: str | None,
    ) -> GeneratedCopy:
        style = self._style_brief(business_name)
        facts = {
            "business_name": business_name,
            "verified_claim_available": bool(verified_claim),
            "style_brief": asdict(style),
        }
        system = self._system_prompt()
        user = (
            "Write one restrained, genuinely human first-touch note using only the supplied recipient facts. "
            "The style_brief controls rhetoric only; it does not authorize any new factual statement.\n"
            + json.dumps(facts, ensure_ascii=False)
        )

        subject, body = self._request_copy(
            system=system,
            user=user,
            temperature=0.55,
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
            repair_user = (
                user
                + "\n\nThe previous draft violated this constraint: "
                + str(exc)
                + ". Rewrite it from scratch while preserving the style_brief. "
                + "Use only the business name plus the application-owned verified-finding token as recipient facts. "
                + "Do not add another observation, consequence, benefit, prediction, or invented familiarity. "
                + "Do not reuse the same opening and closing structure from the rejected draft."
            )
            subject, body = self._request_copy(
                system=system,
                user=repair_user,
                temperature=0.35,
            )
            subject, body = self._ensure_finding_slot(
                subject=subject,
                body=body,
                system=system,
                user=repair_user,
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

The note must read like an individual message, not a cold-email sequence, lead-gen template, audit pitch, prospecting list, mail merge, or AI copy. Different businesses must not collapse into the same opening + finding + closing skeleton.

FACT CONTRACT:
- Use only the supplied business name and the existence of one application-owned verified finding.
- Do not invent a contact name, relationship, result, urgency, customer impact, ranking impact, revenue impact, or any second finding.
- Do not imply Mike was browsing, comparing, researching, or checking other businesses.
- If verified_claim_available is true, place the exact token {CLAIM_TOKEN} exactly once in the body. The token is the only website observation you may make.
- Do not explain, paraphrase, strengthen, weaken, or add consequences to the token.
- Do not mention service area, services, hours, reviews, contact details, design, content, pricing, or any other site detail.

STYLE BRIEF:
- Follow the supplied style_brief to vary subject shape, greeting, opener shape, closing shape, and paragraph rhythm.
- The style_brief is rhetorical metadata only. It never authorizes a new fact.
- Variation must come from syntax and structure, not invented personalization.
- It is acceptable to put the verified finding immediately after a greeting with no setup sentence.
- It is acceptable to mention the business name only in the subject if the body is otherwise natural.
- Avoid awkward possessive constructions for business names ending in s. Prefer "the Bright Electric Services website" or "your website" rather than "Bright Electric Services's website".

STYLE:
- Subject: 1-5 words, plain, business-anchored, no city, industry, urgency, or sales language.
- Body: 25-80 words before Mike's application-owned footer.
- Use contractions and ordinary spoken business English.
- Keep the verified finding early.
- The closing should be low-pressure and concrete, but do not default every note to the same offer.
- Plain text only.
- Do not add Mike's name, company, postal address, opt-out language, or a signature; the application appends those.

PROHIBITED:
- fake familiarity or generic compliments
- marketing hype, exclamation points, links, or sales claims
- "quick note", "quick observation", "worth flagging", "noticed one thing", "I was reviewing", "I came across your business", "hope you're well"
- "checking out", "looking at other", "researching", "comparing"
- "Want me to send over", "Would you be open to", "Would it be useful if", "Happy to send over", "book a call", "schedule a call"
- "quick fix", "small thing", "easy fix", "could help", "might help", "may help", "should help", "could improve", "make it easier"
- "online presence", "grow your business", "increase leads", "you're losing customers", "rankings", "traffic", "free audit"
- SEO jargon in your own words such as schema, PageSpeed, map pack, title tag, or Google Business Profile

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
            temperature=0.3,
        )
        if body.count(CLAIM_TOKEN) != 1:
            raise OpenRouterError(
                "OpenRouter could not preserve the verified finding slot after repair"
            )
        return subject, body

    @staticmethod
    def _insert_verified_finding_slot(body: str) -> str:
        """Compatibility helper used by slot-repair regressions.

        Runtime generation no longer falls back to this helper after a failed
        model repair; `_ensure_finding_slot` fails closed instead.
        """

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
                "Generated copy introduced prospect-list language, an unsupported consequence, sales cliché, or jargon"
            )
        if "!" in combined:
            raise OpenRouterError("Generated copy used promotional punctuation")
        if ":" in subject or " - " in subject or " — " in subject:
            raise OpenRouterError("Generated subject used a templated subject pattern")

        if city and city.lower() in subject.lower():
            raise OpenRouterError("Generated subject added an unnecessary city qualifier")

        body_scope = body.lower()
        if business_name:
            business_lower = business_name.lower()
            if business_lower.endswith("s") and f"{business_lower}'s" in body_scope:
                raise OpenRouterError(
                    "Generated copy used an awkward possessive form of a business name ending in s"
                )
            body_scope = body_scope.replace(business_lower, "")
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
