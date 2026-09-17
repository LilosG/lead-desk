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
    OpenRouterError,
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
    "{business} — local search audit",
    "Local search audit — {business}",
    "{business} website audit",
    "{business} search audit",
    "{business} audit",
)

_FALLBACK_SUBJECTS = (
    "Local search audit",
    "Website audit",
    "Search audit",
    "Website review",
    "Local search review",
)

_FRAMES = (
    (
        "I reviewed the website and Google profile for {business} and put together a short audit.\n\n"
        "{claim}\n\n"
        "I attached the audit so you can see exactly what I found.\n\n"
        "{closing}"
    ),
    (
        "I put together a short local search audit for {business} after reviewing the website and Google profile.\n\n"
        "{claim}\n\n"
        "The audit is attached with the findings and recommendations.\n\n"
        "{closing}"
    ),
    (
        "I reviewed {business} across the website and Google profile and summarized the findings in a short audit.\n\n"
        "{claim}\n\n"
        "I attached it so you can review the findings directly.\n\n"
        "{closing}"
    ),
    (
        "After reviewing the website and Google profile for {business}, I put together a short local search audit.\n\n"
        "{claim}\n\n"
        "I attached the audit with the findings and recommended next steps.\n\n"
        "{closing}"
    ),
    (
        "I took a direct look at the website and Google profile for {business} and put the findings into a short audit.\n\n"
        "{claim}\n\n"
        "The audit is attached so you can see the issues and recommendations in context.\n\n"
        "{closing}"
    ),
    (
        "I completed a short local search review for {business} using the website and Google profile.\n\n"
        "{claim}\n\n"
        "I attached the audit so the findings are easy to review in one place.\n\n"
        "{closing}"
    ),
    (
        "I reviewed the public website and Google profile for {business} and put together a concise audit from that review.\n\n"
        "{claim}\n\n"
        "The audit is attached with the specific findings and recommendations.\n\n"
        "{closing}"
    ),
    (
        "I put together a short audit for {business} based on the website and Google profile.\n\n"
        "{claim}\n\n"
        "I attached the audit so you can review exactly what was found.\n\n"
        "{closing}"
    ),
)

_CLOSINGS = (
    "If any of it is useful and you want help fixing it, feel free to reply.",
    "If the audit is useful and you want help implementing any of it, feel free to reply.",
    "If you want help with any of the items in the audit, feel free to reply.",
    "If any of the findings are worth addressing and you want help with them, feel free to reply.",
    "If you decide you want help implementing any of the recommendations, feel free to reply.",
    "If the findings are useful and you want a hand fixing any of them, feel free to reply.",
)


class ConstrainedOutreachClient:
    """Render only evidence-backed professional audit outreach.

    Qwen may select structure indices, but all recipient-facing prose is owned by
    the application. A verified client-facing finding is mandatory. Generic
    claim-free cold email is intentionally blocked rather than sending hollow
    outreach with no useful substance.
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
            raise OpenRouterError(
                "No verified client-facing finding is available. Lead Desk will not generate a generic cold email with no useful substance."
            )

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
        if len(candidate) > 80:
            return _FALLBACK_SUBJECTS[subject_index]
        return candidate

    def _choose_style(self, business_name: str) -> tuple[StyleChoice, bool]:
        fallback = self._deterministic_choice(business_name)
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.6,
            "max_tokens": 100,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Choose structure indices for one direct professional local-business audit email. "
                        "Do not write email prose, facts, names, observations, CTAs, or explanations. "
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

    @staticmethod
    def _pack_structure(choice: StyleChoice) -> int:
        return (
            (choice.greeting * len(_FRAMES) + choice.frame) * len(_CLOSINGS)
            + choice.closing
        )

    @staticmethod
    def _unpack_structure(slot: int, *, subject: int) -> StyleChoice:
        closing = slot % len(_CLOSINGS)
        slot //= len(_CLOSINGS)
        frame = slot % len(_FRAMES)
        slot //= len(_FRAMES)
        greeting = slot % len(_GREETINGS)
        return StyleChoice(
            subject=subject,
            greeting=greeting,
            frame=frame,
            closing=closing,
        )

    @classmethod
    def _decorrelate(cls, choice: StyleChoice, business_name: str) -> StyleChoice:
        digest = cls._fingerprint(business_name)
        structure_count = len(_GREETINGS) * len(_FRAMES) * len(_CLOSINGS)
        model_slot = cls._pack_structure(choice)
        business_offset = int.from_bytes(digest[8:16], "big") % structure_count
        structure_slot = (model_slot + business_offset) % structure_count
        subject = (choice.subject + digest[0]) % len(_SUBJECTS)
        return cls._unpack_structure(structure_slot, subject=subject)

    @classmethod
    def _deterministic_choice(cls, business_name: str) -> StyleChoice:
        digest = cls._fingerprint(business_name)
        structure_count = len(_GREETINGS) * len(_FRAMES) * len(_CLOSINGS)
        structure_slot = int.from_bytes(digest[8:16], "big") % structure_count
        subject = digest[1] % len(_SUBJECTS)
        return cls._unpack_structure(structure_slot, subject=subject)

    @classmethod
    def _render_body(cls, business_name: str, choice: StyleChoice) -> str:
        greeting = _GREETINGS[choice.greeting]
        safe_name = cls._safe_business_name(business_name)
        frame = _FRAMES[choice.frame].format(
            business=safe_name,
            claim=CLAIM_TOKEN,
            closing=_CLOSINGS[choice.closing],
        ).strip()
        if greeting:
            return f"{greeting}\n\n{frame}"
        return frame
