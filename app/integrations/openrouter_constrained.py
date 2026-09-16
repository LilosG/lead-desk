from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import requests

from app.integrations.openrouter import (
    CLAIM_TOKEN,
    GeneratedCopy,
    OPENROUTER_CHAT_URL,
)


@dataclass(frozen=True)
class StyleChoice:
    subject: int
    greeting: int
    opener: int
    closing: int
    rhythm: int


_GREETINGS = (
    "Hi,",
    "Hello,",
    "",
)

_SUBJECTS = (
    "{business}",
    "{business} website",
    "{business} site",
    "Website note for {business}",
    "Website detail for {business}",
)

_OPENERS = (
    "",
    "I checked the {business} website before emailing and had one specific detail to pass along.",
    "I was looking at the {business} website and wanted to mention one concrete item.",
    "I had one specific website detail for {business} that seemed worth sending directly.",
    "I checked one technical detail on the {business} website before reaching out.",
    "I wanted to pass along one specific thing I verified on the {business} website.",
    "This is about one concrete detail on the {business} website.",
    "I had the {business} website open and wanted to send one specific detail.",
    "I checked your website before emailing and wanted to pass along one specific item.",
    "I wanted to mention one concrete website detail I verified before reaching out.",
    "I took a look at your website and had one specific detail to pass along.",
    "I am reaching out about one specific detail on the {business} website.",
)

_CLOSINGS = (
    "If you already know about it, no need to reply.",
    "If it is already being handled, all good.",
    "If you want the exact page location I checked, I can send it.",
    "I can point you to the exact spot if you want to check it on your side.",
    "If you want to see exactly where I am seeing it, I can send the page location.",
    "If you already have it covered, you can ignore this.",
    "If you want the exact spot, I can send that over.",
    "I can tell you exactly where I checked it if that is useful.",
    "That is all I wanted to pass along. If you want the exact location, I can send it.",
    "If you want to compare it yourself, I can tell you exactly where I checked.",
    "If this is useful, I can send the exact location. If not, no worries.",
    "If this is already on your list, no response needed.",
    "If you want the detail behind that, I can send the exact location I checked.",
    "If you want to verify it on your side, I can point you to the exact spot.",
    "If this is already covered, there is nothing you need to do with this note.",
    "Do you want the exact page location I checked?",
)

_RHYTHMS = (
    "claim_then_close",
    "opener_then_claim_then_close",
    "opener_claim_then_close",
    "opener_claim_close_compact",
)


class ConstrainedOutreachClient:
    """Let the model select rhetoric while the application owns every sent word.

    Qwen never writes recipient-facing prose. It can only select indices from reviewed
    subject, greeting, opener, closing, and rhythm banks. The verified finding remains
    an application-owned token inserted by OutreachService after live verification.
    Invalid model output falls back to a deterministic application-owned style.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 25.0,
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
        if not verified_claim:
            raise RuntimeError("No approved client-facing finding is available")

        choice, used_model = self._choose_style(business_name)
        subject = self._render_subject(business_name, choice.subject)
        body = self._render_body(business_name, choice)

        if body.count(CLAIM_TOKEN) != 1:
            raise RuntimeError("constrained outreach renderer lost verified finding token")

        return GeneratedCopy(
            subject=subject,
            body=body,
            model=self.model if used_model else "application/constrained-outreach",
        )

    @staticmethod
    def _safe_business_name(business_name: str) -> str:
        words = business_name.strip().split()
        if not words:
            return "Business"
        return " ".join(words[:5])[:45]

    @classmethod
    def _render_subject(cls, business_name: str, subject_index: int) -> str:
        safe_name = cls._safe_business_name(business_name)
        candidate = _SUBJECTS[subject_index].format(business=safe_name).strip()
        # Never chop a subject into a misleading fragment such as
        # "Website detail for Richard". If a pattern does not fit the plain
        # 5-word/55-character contract, fall back to the business name itself.
        if len(candidate.split()) > 5 or len(candidate) > 55:
            candidate = safe_name
        return candidate

    def _choose_style(self, business_name: str) -> tuple[StyleChoice, bool]:
        fallback = self._deterministic_choice(business_name)

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.9,
            "max_tokens": 120,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Choose style indices for one short local-business outreach note. "
                        "Do not write email prose, facts, names, observations, or explanations. "
                        "Return JSON only with integer keys subject, greeting, opener, closing, rhythm. "
                        f"Allowed subject 0-{len(_SUBJECTS)-1}, greeting 0-{len(_GREETINGS)-1}, "
                        f"opener 0-{len(_OPENERS)-1}, closing 0-{len(_CLOSINGS)-1}, "
                        f"rhythm 0-{len(_RHYTHMS)-1}. Prefer combinations that would not resemble a repeated mail-merge pattern."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"business_name": business_name}),
                },
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
            if not response.ok:
                return fallback, False
            data = response.json()
            raw = data["choices"][0]["message"]["content"]
            parsed = self._parse_json(raw)
            choice = StyleChoice(
                subject=int(parsed["subject"]),
                greeting=int(parsed["greeting"]),
                opener=int(parsed["opener"]),
                closing=int(parsed["closing"]),
                rhythm=int(parsed["rhythm"]),
            )
            if not self._valid_choice(choice):
                return fallback, False
            return choice, True
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return fallback, False

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if not isinstance(value, str):
            raise TypeError("style response must be text")
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)

    @staticmethod
    def _valid_choice(choice: StyleChoice) -> bool:
        return (
            0 <= choice.subject < len(_SUBJECTS)
            and 0 <= choice.greeting < len(_GREETINGS)
            and 0 <= choice.opener < len(_OPENERS)
            and 0 <= choice.closing < len(_CLOSINGS)
            and 0 <= choice.rhythm < len(_RHYTHMS)
        )

    @staticmethod
    def _deterministic_choice(business_name: str) -> StyleChoice:
        digest = hashlib.sha256(business_name.encode("utf-8")).digest()
        return StyleChoice(
            subject=digest[0] % len(_SUBJECTS),
            greeting=digest[1] % len(_GREETINGS),
            opener=digest[2] % len(_OPENERS),
            closing=digest[3] % len(_CLOSINGS),
            rhythm=digest[4] % len(_RHYTHMS),
        )

    @staticmethod
    def _render_body(business_name: str, choice: StyleChoice) -> str:
        greeting = _GREETINGS[choice.greeting]
        opener = _OPENERS[choice.opener].format(business=business_name)
        closing = _CLOSINGS[choice.closing]
        rhythm = _RHYTHMS[choice.rhythm]

        if rhythm == "claim_then_close":
            core = [CLAIM_TOKEN, closing]
        elif rhythm == "opener_then_claim_then_close":
            core = [opener, CLAIM_TOKEN, closing] if opener else [CLAIM_TOKEN, closing]
        elif rhythm == "opener_claim_then_close":
            core = [f"{opener} {CLAIM_TOKEN}".strip(), closing] if opener else [CLAIM_TOKEN, closing]
        else:
            core = [f"{opener} {CLAIM_TOKEN} {closing}".strip()] if opener else [f"{CLAIM_TOKEN} {closing}"]

        paragraphs: list[str] = []
        if greeting:
            paragraphs.append(greeting)
        paragraphs.extend(part for part in core if part)
        return "\n\n".join(paragraphs).strip()
