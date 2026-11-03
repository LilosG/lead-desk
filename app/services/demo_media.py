from __future__ import annotations

import base64
import binascii
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from PIL import Image, UnidentifiedImageError

from app.repositories.demo_media import DemoMediaRepository
from app.repositories.prospects import ProspectRepository
from pipeline import verticals as vertical_config


PROMPT_VERSION = "demo-media-v2"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_IMAGE_WIDTH = 2000
WEBP_QUALITY = 82
# Places and tools rather than people: AI faces read as fake, and a generated
# "owner" would misrepresent the business.
NICHE_SCENES = {
    "home_service": "a well-kept home or job site with the real tools and materials of a {category}",
    "medical_aesthetic": "a calm, modern, spotless treatment room with soft natural light",
    "dental": "a bright, modern, welcoming dental office",
    "real_estate": "an inviting home exterior on an attractive residential street",
    "legal": "a warm, professional law office with a desk, books and natural light",
    "wellness_health": "a calm, modern treatment room with natural light",
    "auto": "a clean, organized auto repair bay with professional equipment",
    "generic_local_business": "the inside of a welcoming, well-run {category}",
}
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
        image_bytes = self._web_ready(self._request_image(
            api_key=api_key,
            model=model,
            prompt=prompt,
            aspect_ratio=ROLE_ASPECT_RATIO[role],
        ))
        prospect_key = hashlib.sha256(place_id.encode("utf-8")).hexdigest()[:16]
        media_dir = root / "_media" / prospect_key
        media_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{role}-{uuid4().hex}.webp"
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
        """OpenRouter generates images through chat completions.

        Google's models take image and text output; image-only models such as
        Seedream reject that and need ["image"], so that's the second attempt.
        """
        response = None
        for modalities in (["image", "text"], ["image"]):
            try:
                response = requests.post(
                    OPENROUTER_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "modalities": modalities,
                        "image_config": {"aspect_ratio": aspect_ratio},
                    },
                    timeout=120,
                )
            except requests.RequestException as exc:
                raise DemoMediaError("image provider request failed") from exc
            if response.status_code != 400:
                break
        if not response.ok:
            raise DemoMediaError(f"image provider returned HTTP {response.status_code}")
        try:
            message = response.json()["choices"][0]["message"]
            url = message["images"][0]["image_url"]["url"]
            return base64.b64decode(url.split(",", 1)[1], validate=True)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, binascii.Error) as exc:
            raise DemoMediaError("image provider returned no image") from exc

    @staticmethod
    def _web_ready(image_bytes: bytes) -> bytes:
        """WebP at a sensible width: the raw file is often several MB."""
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                if image.width > MAX_IMAGE_WIDTH:
                    height = round(image.height * MAX_IMAGE_WIDTH / image.width)
                    image = image.resize((MAX_IMAGE_WIDTH, height), Image.LANCZOS)
                out = BytesIO()
                image.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
                return out.getvalue()
        except (UnidentifiedImageError, OSError) as exc:
            raise DemoMediaError("image provider returned an unsupported image format") from exc

    @staticmethod
    def _prompt(
        prospect: dict[str, Any],
        *,
        role: str,
        direction: str | None,
    ) -> str:
        category = str(prospect.get("primary_type") or "local business").replace("_", " ")
        city = str(prospect.get("city") or "")
        state = str(prospect.get("state") or "")
        location = ", ".join(part for part in (city, state) if part)
        profile = vertical_config.vertical_profile(prospect.get("vertical") or "")
        scene = NICHE_SCENES.get(profile, NICHE_SCENES["generic_local_business"]).format(category=category)
        role_direction = {
            "hero": (
                f"Wide homepage hero photograph of {scene}. Main subject on the right half, "
                "calm darker space on the left where text will sit."
            ),
            "work": f"Medium photograph showing the detail and craft of {scene}.",
            "secondary": f"Wide supporting photograph of {scene}, from a different angle than the hero.",
        }[role]
        place = f" Fits the look of {location}." if location else ""
        optional = f" Additional art direction: {direction.strip()}" if direction and direction.strip() else ""
        return (
            f"Create a photorealistic website photograph for a {category}.{place} {role_direction} "
            "Do not place any business name, logo, signage, text, phone number, badge, license "
            "number, watermark, or branded vehicle graphics in the image. Do not show identifiable "
            "faces, and do not imply that any person shown is the real owner or an employee. "
            f"Natural light, professional DSLR realism, restrained color grading, no stock-photo poses.{optional}"
        )
