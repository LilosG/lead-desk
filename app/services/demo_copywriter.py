"""Writes demo homepage copy with the text model already used for outreach.

The model only sees facts Lead Desk has verified (listing, reviews, the lead's
own site) and every field it returns is checked: anything that states a claim
the demo can't back up (licences, years, guarantees, prices, speed, awards) or
a number that isn't the real rating or review count is dropped, and the page
uses its standard wording for that field instead.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import requests

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
LIMITS = {"headline": 70, "subheadline": 200, "about": 480, "blurb": 140}

# Claims a concept page can't verify about a real business.
BANNED = re.compile(
    r"licen[cs]|insured|bonded|certif|accredit|guarantee|warrant|award|voted|#\s*1|number one|"
    r"\bbest\b|cheapest|lowest|afford|discount|free\b|\$|%|price|pricing|years?\b|since\s+(19|20)\d\d|"
    r"decade|family[- ]owned|veteran|24/7|24 hours|same[- ]day|next[- ]day|within \d|minutes|"
    r"fast(est)?\b|quick(est)?\b|emergency response|on[- ]call|board[- ]certified|top[- ]rated|"
    r"trusted by|thousands|hundreds|\bwe\b|\bour\b|\bus\b",
    re.I,
)

SYSTEM_PROMPT = """You write homepage copy for a concept website of a real local business.
Write in the third person about the business by name. Do not write as the business ("we", "our", "us").
Use ONLY the facts provided. Never state or imply: licences, insurance, certifications, years in
business, founding dates, family ownership, awards, rankings, "best", guarantees, warranties, prices,
discounts, free offers, speed, response times, 24/7 or same-day availability, or customer counts.
The only numbers you may use are the Google rating and review count given.
Plain, warm, specific language. No exclamation marks, no clichés like "look no further".
Return JSON only, with exactly these keys:
{"headline": "...", "subheadline": "...", "about": "...", "service_blurbs": {"<service name exactly as given>": "..."}}
headline: at most 60 characters, names the city or the main service.
subheadline: one or two sentences, at most 180 characters.
about: two or three sentences, at most 420 characters, drawing on what the reviews praise.
service_blurbs: one line per service, at most 120 characters, describing the job and why someone needs it."""

Post = Callable[..., Any]


class DemoCopyError(RuntimeError):
    pass


def _facts(facts: dict[str, Any]) -> str:
    lines = [
        f"Business: {facts['name']}",
        f"Category: {facts['category']}",
        f"City: {facts['city']}",
        f"Areas served: {', '.join(facts.get('areas') or [])}",
        f"Services (write one blurb for each, keep names exactly): {json.dumps(facts.get('services') or [])}",
        f"Their customers are called: {facts.get('audience') or 'customers'}",
    ]
    if facts.get("rating") is not None and facts.get("review_count") is not None:
        lines.append(f"Google rating: {facts['rating']:.1f} from {facts['review_count']} reviews")
    for text in (facts.get("review_texts") or [])[:3]:
        lines.append(f"Review: {text[:400]}")
    if facts.get("site_summary"):
        lines.append(f"Their current site describes them as: {facts['site_summary'][:300]}")
    return "\n".join(lines)


def _payload(model: str, facts: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _facts(facts)},
        ],
    }
    if model.startswith("openai/gpt-5"):
        # Reasoning models spend completion tokens thinking; keep it minimal.
        payload["max_completion_tokens"] = 1200
        payload["reasoning"] = {"effort": "minimal", "exclude": True}
    else:
        payload["max_tokens"] = 900
        payload["temperature"] = 0.5
    return payload


def _parse(content: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", content or "", re.S)
    if not match:
        raise DemoCopyError("the model returned no JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise DemoCopyError("the model returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise DemoCopyError("the model returned an unexpected shape")
    return data


def _clean(value: Any, limit: int, allowed_numbers: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace("!", ".").split()).strip().strip('"')
    if not text or len(text) > limit or BANNED.search(text):
        return None
    if any(number not in allowed_numbers for number in re.findall(r"\d+(?:[.,]\d+)?", text)):
        return None
    return text


def checked_copy(data: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Only the fields that pass every check; anything else falls back to standard wording."""
    # Numbers that are part of a real name ("Route 66 Electric") are fine too.
    named = " ".join([str(facts.get("name") or ""), str(facts.get("city") or ""),
                      *map(str, facts.get("areas") or []), *map(str, facts.get("services") or [])])
    allowed: set[str] = set(re.findall(r"\d+(?:[.,]\d+)?", named))
    if facts.get("rating") is not None:
        allowed |= {f"{float(facts['rating']):.1f}", str(float(facts["rating"])).rstrip("0").rstrip(".")}
    if facts.get("review_count") is not None:
        count = int(facts["review_count"])
        allowed |= {str(count), f"{count:,}"}
    result: dict[str, Any] = {}
    for key in ("headline", "subheadline", "about"):
        text = _clean(data.get(key), LIMITS[key], allowed)
        if text:
            result[key] = text
    blurbs: dict[str, str] = {}
    raw = data.get("service_blurbs") if isinstance(data.get("service_blurbs"), dict) else {}
    for service in facts.get("services") or []:
        text = _clean(raw.get(service), LIMITS["blurb"], allowed)
        if text:
            blurbs[service] = text
    result["service_blurbs"] = blurbs
    return result


def write_demo_copy(
    facts: dict[str, Any],
    *,
    api_key: str,
    model: str,
    post: Post = requests.post,
    timeout: float = 45.0,
) -> dict[str, Any]:
    try:
        response = post(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://lead-desk-alpha.vercel.app",
                "X-Title": "LILOs Growth Lead Desk",
            },
            json=_payload(model, facts),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DemoCopyError("the copy request failed") from exc
    if not response.ok:
        raise DemoCopyError(f"the text model returned HTTP {response.status_code}")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DemoCopyError("the text model returned no text") from exc
    result = checked_copy(_parse(content), facts)
    if not any(result.get(key) for key in ("headline", "subheadline", "about")) and not result["service_blurbs"]:
        raise DemoCopyError("none of the suggested copy passed the checks")
    result["model"] = model
    return result
