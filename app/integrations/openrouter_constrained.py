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
    "Website note for {business}",
    "Homepage note for {business}",
    "One website detail — {business}",
)

# Complete rhetorical frames. Each frame contains the immutable verified finding
# exactly once and changes the shape of the note rather than swapping synonyms.
# No frame makes a second factual assertion about the prospect.
_FRAMES = (
    "I checked the {business} website before emailing and had one specific item to pass along.\n\n{claim}\n\n{closing}",
    "One detail from the {business} homepage seemed worth flagging directly.\n\n{claim}\n\n{closing}",
    "I was looking through the {business} website and verified one technical item. {claim}\n\n{closing}",
    "This is just a quick note about the {business} homepage.\n\n{claim}\n\n{closing}",
    "While checking the {business} website, I verified one item I wanted to pass along.\n\n{claim}\n\n{closing}",
    "I had one concrete website detail for {business}. {claim}\n\n{closing}",
    "A quick website note for {business}:\n\n{claim}\n\n{closing}",
    "I checked one technical item on the {business} homepage before reaching out.\n\n{claim}\n\n{closing}",
    "The reason for the note is straightforward. {claim}\n\nI verified it on the {business} homepage. {closing}",
    "I wanted to send one specific website finding rather than a general pitch.\n\n{claim}\n\nThat is the only item I am reaching out about. {closing}",
    "I was reviewing the {business} homepage and came away with one concrete item to mention.\n\n{claim}\n\n{closing}",
    "One thing I verified on the {business} website:\n\n{claim}\n\n{closing}",
    "I am reaching out about one specific homepage detail for {business}. {claim}\n\n{closing}",
    "This is a narrow website note, not a broad audit.\n\n{claim}\n\nI verified that on the {business} homepage. {closing}",
    "I checked the {business} homepage and wanted to pass along one verified detail. {claim}\n\n{closing}",
    "There is one website item I wanted to put on your radar for {business}.\n\n{claim}\n\n{closing}",
    "I took a look at the {business} website with one question in mind and verified this: {claim}\n\n{closing}",
    "A short note on the {business} website. {claim}\n\n{closing}",
    "I verified one detail on the {business} homepage and thought it was better to send the exact item than a generic introduction.\n\n{claim}\n\n{closing}",
    "The only reason I am emailing is one website detail I verified for {business}.\n\n{claim}\n\n{closing}",
    "I checked the {business} website and wanted to leave you with one concrete technical note.\n\n{claim}\n\n{closing}",
    "One verified homepage item for {business}: {claim}\n\n{closing}",
    "I had the {business} website open and checked one specific technical detail.\n\n{claim}\n\n{closing}",
    "Rather than send a general website pitch, I wanted to pass along one thing I verified on the {business} homepage. {claim}\n\n{closing}",
)

_CLOSINGS = (
    "If you already know about it, no need to reply.",
    "If it is already being handled, all good.",
    "If you want the exact page location I checked, I can send it.",
    "I can point you to the exact spot if you want to check it on your side.",
    "If you want to see exactly where I verified it, I can send the page location.",
    "If you already have it covered, you can ignore this note.",
    "If you want the exact spot, I can send that over.",
    "I can tell you exactly where I checked it if that is useful.",
    "If you want to compare it yourself, I can tell you exactly where I checked.",
    "If this is useful, I can send the exact location. If not, no worries.",
    "If this is already on your list, no response needed.",
    "If you want the detail behind that, I can send the exact location I checked.",
    "If you want to verify it on your side, I can point you to the exact spot.",
    "If this is already covered, there is nothing you need to do with this note.",
    "Do you want the exact page location I checked?",
    "If seeing the exact location would help, I can send it over.",
)


class ConstrainedOutreachClient:
    """Use Qwen only as a rhetoric selector; application owns all sent words.

    Recipient-facing prose comes exclusively from reviewed application frames. The
    verified finding is an immutable token supplied by OutreachService after live
    verification. Qwen cannot introduce names, observations, benefits, or claims.
    A stable business fingerprint is mixed into the model choice so repeated model
    output cannot directly create repeated recipient copy.
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
        words = business_name.strip().split()
        if not words:
            return "Business"
        return " ".join(words[:5])[:45]

    @classmethod
    def _render_subject(cls, business_name: str, subject_index: int) -> str:
        safe_name = cls._safe_business_name(business_name)
        candidate = _SUBJECTS[subject_index].format(business=safe_name).strip()
        if len(candidate.split()) > 6 or len(candidate) > 55:
            candidate = safe_name
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
