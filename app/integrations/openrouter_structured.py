from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.integrations.openrouter import (
    CLAIM_TOKEN,
    OPENROUTER_CHAT_URL,
    GeneratedCopy,
    OpenRouterClient,
    OpenRouterError,
)


OUTREACH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


class StructuredOpenRouterClient(OpenRouterClient):
    """OpenRouter client for models with enforced structured-output support.

    GPT-5-series models can spend completion tokens on internal reasoning and
    support JSON-schema response_format. Keep reasoning minimal for this small
    copy task and reserve enough completion budget for the actual JSON body.
    """

    def generate_email(
        self,
        *,
        business_name: str,
        city: str | None,
        vertical: str | None,
        verified_claim: str | None,
    ) -> GeneratedCopy:
        # A first-touch note must have one concrete, approved fact to justify
        # contacting the business. If verification produced only an internal
        # signal (for example a builder fingerprint that we intentionally do not
        # expose), do not generate a vague "I noticed something" email.
        if not verified_claim:
            raise OpenRouterError(
                "No approved client-facing finding is available for this prospect."
            )

        copy = super().generate_email(
            business_name=business_name,
            city=city,
            vertical=vertical,
            verified_claim=verified_claim,
        )

        body = self._normalize_claim_slot(copy.body, verified_claim)
        if body == copy.body:
            return copy
        return GeneratedCopy(subject=copy.subject, body=body, model=copy.model)

    @staticmethod
    def _normalize_claim_slot(body: str, verified_claim: str) -> str:
        """Make the application-owned finding a standalone sentence block.

        The model may grammatically attach the immutable token to its opener
        (for example ``... website and [[VERIFIED_FINDING]]``). Because the
        inserted finding is itself a complete sentence, that creates broken copy
        such as ``and The homepage...``. Normalize the token boundary before the
        application substitutes the verified finding.
        """
        normalized = body
        if verified_claim.rstrip().endswith((".", "!", "?")):
            normalized = re.sub(
                re.escape(CLAIM_TOKEN) + r"[.!?]+",
                CLAIM_TOKEN,
                normalized,
                count=1,
            )

        if CLAIM_TOKEN not in normalized:
            return normalized

        prefix, suffix = normalized.split(CLAIM_TOKEN, 1)
        prefix = prefix.rstrip()
        # A conjunction immediately before the token belongs to the model's
        # sentence, not to the immutable finding. Remove it instead of joining
        # two independently capitalized sentences.
        prefix = re.sub(
            r"(?:[,;:]?\s+)(?:and|but|so|because|while|then)\s*$",
            "",
            prefix,
            flags=re.IGNORECASE,
        ).rstrip()
        if prefix and not prefix.endswith((".", "!", "?", ",")):
            prefix += "."

        suffix = re.sub(r"^[\s.!?;,:-]+", "", suffix).strip()
        parts = [part for part in (prefix, CLAIM_TOKEN, suffix) if part]
        return "\n\n".join(parts)

    @staticmethod
    def _system_prompt() -> str:
        return (
            OpenRouterClient._system_prompt()
            + "\n\nADDITIONAL OUTPUT RULES:\n"
            + "- Write 'website' when referring to the business website. Never write 'site/profile'.\n"
            + f"- Put {CLAIM_TOKEN} in its own sentence/paragraph. Never join it to the opener with 'and', 'but', or another conjunction.\n"
            + "- Do not add a sign-off or signature such as Thanks, Best, Mike, or LILOs Growth. "
            + "The application appends the signature separately."
        )

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
        OpenRouterClient._validate_copy(
            subject=subject,
            body=body,
            has_verified_claim=has_verified_claim,
            business_name=business_name,
            city=city,
            vertical=vertical,
        )

        lowered = body.lower()
        if "site/profile" in lowered:
            raise OpenRouterError(
                "Generated copy used the unnatural site/profile construction"
            )
        if "leave it with me" in lowered:
            raise OpenRouterError(
                "Generated copy used an unnatural outreach closing"
            )
        if "lilos growth" in lowered:
            raise OpenRouterError(
                "Generated copy inserted the application-owned signature"
            )

        signature_line = re.compile(
            r"(?im)^\s*(?:thanks|thank you|best|regards|sincerely|cheers|mike(?:\s+at\s+lilos growth)?)\s*[,!]*\s*$"
        )
        if signature_line.search(body):
            raise OpenRouterError(
                "Generated copy inserted a sign-off or signature"
            )

    def _request_copy(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
    ) -> tuple[str, str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": 500,
            "reasoning": {
                "effort": "minimal",
                "exclude": True,
            },
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "outreach_email",
                    "strict": True,
                    "schema": OUTREACH_RESPONSE_SCHEMA,
                },
            },
            "provider": {
                "require_parameters": True,
            },
        }

        # The structured contract is more important than sampling variance for
        # this small deterministic outreach task. Keep the inherited caller API
        # stable without depending on temperature for GPT-5-series requests.
        _ = temperature

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
            message = data["choices"][0]["message"]
            content = message["content"]
            parsed = self._parse_structured_content(content)
            subject = str(parsed["subject"]).strip()
            body = str(parsed["body"]).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenRouterError("OpenRouter returned an invalid structured draft payload") from exc

        if not subject or not body:
            raise OpenRouterError("OpenRouter returned an incomplete structured draft payload")

        return subject, body

    @staticmethod
    def _parse_structured_content(content: Any) -> dict[str, Any]:
        if isinstance(content, str):
            return json.loads(content.strip())

        # Be tolerant of typed content arrays if provider routing returns one
        # rather than a plain chat-completions text string.
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            if parts:
                return json.loads("".join(parts).strip())

        raise TypeError("structured message content must contain JSON text")
