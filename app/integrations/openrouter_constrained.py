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
    frame: int
    closing: int


_GREETINGS = (
    "Hi,",
    "Hello,",
    "",
)

_SUBJECTS = (
    "{business}",
    "{business} website",
    "{business} homepage",
    "Website question — {business}",
    "Website note — {business}",
)

_FALLBACK_SUBJECTS = (
    "Website question",
    "Website detail",
    "Homepage question",
    "Website note",
    "Homepage detail",
)

# The application owns every sent word. The immutable claim block contains the
# recipient-specific public evidence plus one separately verified technical finding.
# Frames exist only to make the note read naturally; they do not explain the sales
# process, claim personalization, or add any prospect facts.
_FRAMES = (
    "{claim}\n\n{closing}",
    "I checked {business} before reaching out.\n\n{claim}\n\n{closing}",
    "I pulled up {business} before emailing.\n\n{claim}\n\n{closing}",
    "I had {business} open and wanted to pass this along.\n\n{claim}\n\n{closing}",
    "For context:\n\n{claim}\n\n{closing}",
    "This is what I was looking at:\n\n{claim}\n\n{closing}",
    "I checked the Google listing and the website before sending this.\n\n{claim}\n\n{closing}",
    "I took a look at {business} before sending this.\n\n{claim}\n\n{closing}",
    "I wanted to pass this along after checking {business}.\n\n{claim}\n\n{closing}",
    "I had one thing from {business} I wanted to send over.\n\n{claim}\n\n{closing}",
    "I checked {business} and this was the detail I wanted to share.\n\n{claim}\n\n{closing}",
    "I was looking at {business} earlier and wanted to send this over.\n\n{claim}\n\n{closing}",
    "I pulled up the public listing and the website for {business}.\n\n{claim}\n\n{closing}",
    "Here is what I found when I checked {business}:\n\n{claim}\n\n{closing}",
    "A note on {business}:\n\n{claim}\n\n{closing}",
    "I checked {business} and wanted to make sure this got to you.\n\n{claim}\n\n{closing}",
)

_CLOSINGS = (
    "If you already know about it, no need to reply.",
    "If it is already being handled, all good.",
    "If you want the exact page I checked, I can send it.",
    "I can point you to the exact spot if useful.",
    "If you want, I can send a screenshot of the exact spot.",
    "If you already have it covered, you can ignore this.",
    "That is all I wanted to pass along.",
    "I can send the exact page location if you want it.",
    "No need to respond if you already have it covered.",
    "If useful, I can send the page and exact spot I checked.",
    "Just wanted to pass it along.",
    "If you want to verify it on your side, I can point you to the page.",
)


class ConstrainedOutreachClient:
    """Use Qwen only as a rhetoric selector; application owns all sent words.

    Recipient-facing prose comes exclusively from reviewed application frames. The
    verified finding token contains application-owned public evidence plus the live
    verified technical finding. Qwen cannot introduce names, observations, benefits,
    or claims. A stable business fingerprint is mixed into the model choice so
    repeated model output cannot directly create repeated recipient copy.
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

        raw_choice, used_model = self._choose_style(business_name)
        choice = self._decorrelate(raw_choice, business_name)
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
        return " ".join(business_name.strip().split()) or "Business"

    @classmethod
    def _render_subject(cls, business_name: str, subject_index: int) -> str:
        safe_name = cls._safe_business_name(business_name)
        candidate = _SUBJECTS[subject_index].format(business=safe_name).strip()
        if len(candidate.split()) > 5 or len(candidate) > 55:
            return _FALLBACK_SUBJECTS[subject_index]
        return candidate

    def _choose_style(self, business_name: str) -> tuple[StyleChoice, bool]:
        fallback = self._deterministic_choice(business_name)
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.9,
            "max_tokens": 100,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Choose style indices for one short local-business outreach note. "
                        "Do not write email prose, facts, names, observations, or explanations. "
                        "Return JSON only with integer keys subject, greeting, frame, closing. "
                        f"Allowed subject 0-{len(_SUBJECTS)-1}, greeting 0-{len(_GREETINGS)-1}, "
                        f"frame 0-{len(_FRAMES)-1}, closing 0-{len(_CLOSINGS)-1}."
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
                frame=int(parsed["frame"]),
                closing=int(parsed["closing"]),
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
            and 0 <= choice.frame < len(_FRAMES)
            and 0 <= choice.closing < len(_CLOSINGS)
        )

    @staticmethod
    def _fingerprint(business_name: str) -> bytes:
        return hashlib.sha256(business_name.strip().lower().encode("utf-8")).digest()

    @classmethod
    def _decorrelate(cls, choice: StyleChoice, business_name: str) -> StyleChoice:
        digest = cls._fingerprint(business_name)
        return StyleChoice(
            subject=(choice.subject + digest[0]) % len(_SUBJECTS),
            greeting=(choice.greeting + digest[5]) % len(_GREETINGS),
            frame=(choice.frame + int.from_bytes(digest[8:12], "big")) % len(_FRAMES),
            closing=(choice.closing + int.from_bytes(digest[16:20], "big")) % len(_CLOSINGS),
        )

    @classmethod
    def _deterministic_choice(cls, business_name: str) -> StyleChoice:
        digest = cls._fingerprint(business_name)
        return StyleChoice(
            subject=digest[1] % len(_SUBJECTS),
            greeting=digest[2] % len(_GREETINGS),
            frame=int.from_bytes(digest[12:16], "big") % len(_FRAMES),
            closing=int.from_bytes(digest[20:24], "big") % len(_CLOSINGS),
        )

    @staticmethod
    def _render_body(business_name: str, choice: StyleChoice) -> str:
        greeting = _GREETINGS[choice.greeting]
        frame = _FRAMES[choice.frame].format(
            business=business_name,
            claim=CLAIM_TOKEN,
            closing=_CLOSINGS[choice.closing],
        ).strip()
        if greeting:
            return f"{greeting}\n\n{frame}"
        return frame
