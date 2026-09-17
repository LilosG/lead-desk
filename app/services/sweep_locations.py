from __future__ import annotations

from typing import Any

import requests


PLACES_AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
AUTOCOMPLETE_FIELD_MASK = ",".join(
    [
        "suggestions.placePrediction.placeId",
        "suggestions.placePrediction.text.text",
    ]
)


class SweepLocationLookupError(RuntimeError):
    pass


def suggest_us_cities(
    query: str,
    *,
    api_key: str,
    limit: int = 6,
    timeout_seconds: float = 8.0,
) -> list[dict[str, str]]:
    """Return canonical U.S. city predictions without exposing the Places key."""

    normalized = " ".join(query.split())
    if len(normalized) < 2:
        return []
    if len(normalized) > 80:
        raise SweepLocationLookupError("city search is too long")
    if not api_key:
        raise SweepLocationLookupError("Google Places city lookup is not configured")

    payload: dict[str, Any] = {
        "input": normalized,
        "includedPrimaryTypes": ["(cities)"],
        "includedRegionCodes": ["us"],
        "languageCode": "en",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": AUTOCOMPLETE_FIELD_MASK,
    }

    try:
        response = requests.post(
            PLACES_AUTOCOMPLETE_URL,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise SweepLocationLookupError("Google Places city lookup failed") from exc

    if not response.ok:
        raise SweepLocationLookupError(
            f"Google Places city lookup returned {response.status_code}"
        )

    try:
        suggestions = response.json().get("suggestions", [])
    except ValueError as exc:
        raise SweepLocationLookupError("Google Places returned invalid city data") from exc

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        prediction = suggestion.get("placePrediction") or {}
        place_id = str(prediction.get("placeId") or "").strip()
        label = str(((prediction.get("text") or {}).get("text")) or "").strip()
        key = label.casefold()
        if not place_id or not label or key in seen:
            continue
        seen.add(key)
        results.append({"place_id": place_id, "label": label})
        if len(results) >= max(1, min(limit, 10)):
            break

    return results
