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
    greeting: int
    opener: int
    closing: int
    rhythm: int


_GREETINGS = (
    "Hi,",
    "Hello,",
    "",
)

_OPENERS = (
    "I took a look at the {business} website before reaching out.",
    "I checked the {business} website and wanted to pass along one technical item.",
    "I had the {business} website open and wanted to mention one thing I verified.",
    "I looked through the {business} site and wanted to send one specific note.",
    "I checked your website before reaching out and wanted to mention one item I verified.",
    "I took a look at your website and wanted to send one specific note.",
    "",
)

_CLOSINGS = (
    "If this is already on your radar, no reply needed.",
    "If you want the exact page location I checked, I can send it.",
    "I can point you to the exact spot I verified if you want to compare it on your side.",
    "If you want to see exactly what I checked, I can send the page location.",
    "If this is already handled, you can ignore this.",
    "If you want the specific page I verified, I can send that over.",
    "If it helps, I can tell you exactly where I checked it.",
    "No need to reply if you already have this covered.",
)

_RHYTHMS = (
    "opener_claim_then_close",
    "opener_then_claim_then_close",
    "claim_then_close",
    "opener_claim_close_compact",
)


class ConstrainedOutreachClient:
    """Use the model only to choose rhetoric; application owns every sent word.

    The model never writes recipient-facing prose. It selects indices from fixed,
    reviewed phrase banks. The verified finding remains an application-owned token
    inserted by OutreachService after live verification.
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
        subject = self._subject(business_name)
        body = self._render_body(business_name, choice)

        if body.count(CLAIM_TOKEN) != 1:
            raise RuntimeError("constrained outreach renderer lost verified finding token")

        return GeneratedCopy(
            subject=subject,
            body=body,
            model=self.model if used_model else "application/constrained-outreach",
        )

    @staticmethod
    def _subject(business_name: str) -> str:
        # Business name alone is deliberately plain and unique to the recipient.
        # Avoid synthetic prefixes/suffixes that make a batch look mail-merged.
        return business_name.strip()[:55]

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
                        "Choose rhetorical style indices for one short local-business outreach note. "
                        "Do not write email prose. Return JSON only with integer keys greeting, opener, closing, rhythm. "
                        f"Allowed greeting 0-{len(_GREETINGS)-1}, opener 0-{len(_OPENERS)-1}, "
                        f"closing 0-{len(_CLOSINGS)-1}, rhythm 0-{len(_RHYTHMS)-1}."
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
            0 <= choice.greeting < len(_GREETINGS)
            and 0 <= choice.opener < len(_OPENERS)
            and 0 <= choice.closing < len(_CLOSINGS)
            and 0 <= choice.rhythm < len(_RHYTHMS)
        )

    @staticmethod
    def _deterministic_choice(business_name: str) -> StyleChoice:
        digest = hashlib.sha256(business_name.encode("utf-8")).digest()
        return StyleChoice(
            greeting=digest[0] % len(_GREETINGS),
            opener=digest[1] % len(_OPENERS),
            closing=digest[2] % len(_CLOSINGS),
            rhythm=digest[3] % len(_RHYTHMS),
        )

    @staticmethod
    def _render_body(business_name: str, choice: StyleChoice) -> str:
        greeting = _GREETINGS[choice.greeting]
        opener = _OPENERS[choice.opener].format(business=business_name)
        closing = _CLOSINGS[choice.closing]
        rhythm = _RHYTHMS[choice.rhythm]

        # A no-opener style is intentional, but avoid creating an empty paragraph.
        if rhythm == "claim_then_close" or not opener:
            core = [CLAIM_TOKEN, closing]
        elif rhythm == "opener_then_claim_then_close":
            core = [opener, CLAIM_TOKEN, closing]
        elif rhythm == "opener_claim_close_compact":
            core = [f"{opener} {CLAIM_TOKEN} {closing}"]
        else:
            core = [f"{opener} {CLAIM_TOKEN}", closing]

        paragraphs = []
        if greeting:
            paragraphs.append(greeting)
        paragraphs.extend(core)
        return "\n\n".join(part for part in paragraphs if part).strip()
