from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from app.repositories.demo_media import DemoMediaRepository
from app.repositories.prospects import ProspectRepository


PROMPT_VERSION = "demo-media-v1"
VALID_ROLES = {"hero", "work", "secondary"}
ROLE_ASPECT_RATIO = {
    "hero": "16:9",
    "work": "4:3",
    "secondary": "16:9",
}


class DemoMediaError(RuntimeError):
    pass


class DemoMediaService:
    def __init__(
        self,
        prospect_repository: ProspectRepository,
        media_repository: DemoMediaRepository,
    ):
        self.prospect_repository = prospect_repository
        self.media_repository = media_repository

    def generate(
        self,
        place_id: str,
        *,
        role: str,
        api_key: str,
        model: str,
        root: Path,
        base_url: str,
        direction: str | None = None,
    ) -> dict[str, Any]:
        if role not in VALID_ROLES:
            raise DemoMediaError("invalid demo image role")
        prospect = self.prospect_repository.get_prospect(place_id)
        if prospect is None:
            raise DemoMediaError("prospect not found")
        if not api_key:
            raise DemoMediaError("demo image generation is not configured")

        prompt = self._prompt(prospect, role=role, direction=direction)
        image_bytes = self._request_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            aspect_ratio=ROLE_ASPECT_RATIO[role],
        )
        extension = self._extension(image_bytes)
        prospect_key = hashlib.sha256(place_id.encode("utf-8")).hexdigest()[:16]
        media_dir = root / "_media" / prospect_key
        media_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{role}-{uuid4().hex}.{extension}"
        target = media_dir / filename
        target.write_bytes(image_bytes)
        relative = f"_media/{prospect_key}/{filename}"
        public_url = f"{base_url.rstrip('/')}/{relative}"

        return self.media_repository.create_media(
            place_id=place_id,
            role=role,
            source="generated",
            model=model,
            prompt_version=PROMPT_VERSION,
            prompt_text=prompt,
            storage_path=str(target),
            public_url=public_url,
        )

    def list_for_prospect(self, place_id: str) -> list[dict[str, Any]]:
        return self.media_repository.list_for_prospect(place_id)

    @staticmethod
    def _request_image(
        *,
        api_key: str,
        model: str,
        prompt: str,
        aspect_ratio: str,
    ) -> bytes:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/images",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                },
                timeout=120,
            )
        except requests.RequestException as exc:
            raise DemoMediaError("image provider request failed") from exc
        if not response.ok:
            raise DemoMediaError(
                f"image provider returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            encoded = (payload.get("data") or [])[0].get("b64_json")
            if not encoded:
                raise ValueError("missing image data")
            return base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, IndexError, base64.binascii.Error) as exc:
            raise DemoMediaError("image provider returned invalid image data") from exc

    @staticmethod
    def _extension(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "jpg"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "webp"
        raise DemoMediaError("image provider returned an unsupported image format")

    @staticmethod
    def _prompt(
        prospect: dict[str, Any],
        *,
        role: str,
        direction: str | None,
    ) -> str:
        name = str(prospect.get("name") or "local home-service business")
        city = str(prospect.get("city") or "the local service area")
        state = str(prospect.get("state") or "")
        category = str(prospect.get("primary_type") or "home service").replace("_", " ")
        location = ", ".join(part for part in (city, state) if part)
        role_direction = {
            "hero": (
                "Wide premium homepage hero photograph, strong subject on the right half, "
                "clean darker text-safe space on the left, natural residential setting."
            ),
            "work": (
                "Documentary-style close-to-medium photograph of skilled trade work in progress, "
                "real tools and materials, believable residential environment."
            ),
            "secondary": (
                "Wide supporting photograph that communicates local residential service and trust, "
                "natural exterior or finished-work context, visually distinct from the hero."
            ),
        }[role]
        optional = f" Additional art direction: {direction.strip()}" if direction and direction.strip() else ""
        return (
            f"Create a photorealistic website photograph for a {category} business serving {location}. "
            f"The business name is {name}, but do not place any business name, logo, signage, text, "
            "phone number, badge, license number, watermark, or branded vehicle graphics in the image. "
            "Do not imply that generated people are the real owner or employees. Use believable Southern "
            "California-style residential architecture when geographically appropriate, natural light, "
            "professional DSLR realism, authentic tools and materials, restrained color grading, and no "
            f"stock-photo poses. {role_direction}{optional}"
        )
