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


PROMPT_VERSION = "demo-media-v6"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_IMAGE_WIDTH = 2000
WEBP_QUALITY = 82
# Places and tools rather than people: AI faces read as fake, and a generated
# "owner" would misrepresent the business.
NICHE_SCENES = {
    "home_service": "a beautiful, well-kept home with the real tools and work of a {category} in the foreground",
    "medical_aesthetic": "a serene, high-end treatment suite with soft textures, plants and natural light",
    "dental": "a bright, modern, design-led dental studio with warm wood and natural light",
    "real_estate": "a striking, inviting home exterior with a lit entry and landscaped approach",
    "legal": "a refined law office with warm wood, leather, books and city light through the windows",
    "wellness_health": "a calm, modern treatment studio with natural materials and soft daylight",
    "auto": "a spotless, well-lit auto repair bay with a car on the lift and professional equipment",
    "generic_local_business": "the welcoming, beautifully kept interior of a {category}",
}
# One fixed subject per trade, so every lead in a niche gets a consistent shot.
TRADE_SCENES = {
    "electrician": (
        "a modern home's tidy garage with a neatly wired open electrical panel and professional "
        "tools in the foreground, warm lights glowing through the house behind it"
    ),
    "plumber": (
        "a modern kitchen with a new chrome faucet, open under-sink copper pipework and "
        "professional tools in the foreground"
    ),
    "hvac": (
        "a clean new outdoor air conditioning unit beside a well-kept home, with gauges and "
        "professional tools in the foreground"
    ),
    "roofing": (
        "a clean new roof on a well-kept home, seen along the ridge line, with roofing tools and "
        "materials in the foreground"
    ),
    "restoration": (
        "a bright home interior mid-restoration, with professional drying fans and equipment "
        "set out in a clean, orderly way"
    ),
    "landscaping": (
        "a lush, freshly landscaped front yard with crisp edges, a stone path and healthy plants "
        "that suit the local climate"
    ),
    "handyman": (
        "a well-kept home interior with a freshly finished repair and a neat, well-used toolbox "
        "in the foreground"
    ),
    "party_rentals": (
        "an elegant outdoor event set up with tables, chairs and string lights, ready for guests"
    ),
}
# The hero sits behind the headline (left) and a lead form (right), so it is a
# calm architectural shot that sets the scene: a beautiful finished space with
# the trade's work in it, no people or hands. Close-up craft goes in the work photo.
HERO_TRADE_SCENES = {
    "electrician": (
        "a beautiful modern home at blue hour, warm interior and landscape lighting glowing, "
        "an EV charger neatly mounted in the open, tidy garage"
    ),
    "plumber": "a bright, newly finished modern kitchen and open-plan living space with a polished chrome faucet",
    "hvac": "a calm, comfortable modern living room in soft daylight, with a sleek wall-mounted mini-split unit",
    "roofing": "a beautiful home with a crisp new roof, photographed from the street at golden hour",
    "restoration": "a bright, freshly restored home interior with new floors and clean walls in soft daylight",
    "landscaping": "a lush, freshly landscaped front yard and stone path leading to a welcoming home at golden hour",
    "handyman": "a warm, well-kept modern home interior with freshly finished trim and paint in soft daylight",
    "party_rentals": "an elegant outdoor event set up with tables, chairs and string lights at dusk, ready for guests",
}
HERO_NICHE_SCENES = {
    "home_service": "a beautiful, well-kept modern home at golden hour with warm lights glowing inside",
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

        Google's models take image and text output and newer ones take a size;
        image-only models such as Seedream reject those, so each attempt asks for less.
        """
        config = {"aspect_ratio": aspect_ratio}
        attempts = [(["image", "text"], config), (["image"], config)]
        if model.startswith("google/gemini-3"):
            attempts.insert(0, (["image", "text"], {**config, "image_size": "2K"}))
        response = None
        for modalities, image_config in attempts:
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
                        "image_config": image_config,
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
        vertical = prospect.get("vertical") or ""
        profile = vertical_config.vertical_profile(vertical)
        trade = vertical_config.normalize_vertical_key(vertical) if vertical.strip() else ""
        scene = TRADE_SCENES.get(trade) or NICHE_SCENES.get(
            profile, NICHE_SCENES["generic_local_business"]
        ).format(category=category)
        hero_scene = (
            HERO_TRADE_SCENES.get(trade)
            or HERO_NICHE_SCENES.get(profile)
            or NICHE_SCENES.get(profile, NICHE_SCENES["generic_local_business"]).format(category=category)
        )
        role_direction = {
            "hero": (
                f"Wide architectural photograph of {hero_scene}. Balanced composition with detail spread "
                "across the frame, because website text covers the left side and a form covers the right. "
                "Real depth, inviting light."
            ),
            "work": f"Close, detailed photograph showing the craft of {scene}, shallow depth of field.",
            "secondary": f"Wide photograph of {scene}, from a different angle than a typical hero shot.",
        }[role]
        people_rule = (
            "Show no people at all: no faces, bodies, arms or hands. "
            if role == "hero" else
            "Show no people: no faces, heads or bodies. At most a gloved hand may enter the edge of the frame. "
        )
        place = f" Fits the look of {location}." if location else ""
        optional = (
            f" Art direction, which takes priority over the scene described above: {direction.strip()}. "
            "If it mentions a person or a worker, show the place and the finished work instead, never the person."
            if direction and direction.strip() else ""
        )
        return (
            f"Create a photorealistic website photograph for {'an' if category[:1].lower() in 'aeiou' else 'a'} "
            f"{category}.{place} {role_direction} "
            "Do not place any business name, logo, signage, text, phone number, badge, license "
            f"number, watermark, or branded vehicle graphics in the image. {people_rule}"
            "One single continuous photograph from one camera position: never a collage, diptych, "
            "split screen, grid, inset or before-and-after. "
            "Premium editorial commercial photography, shot on a full-frame camera with a 35mm lens, "
            "tack sharp, rich natural color, no stock-photo poses. The photograph fills the whole frame "
            "edge to edge: no black bars, borders, gradients, vignettes, panels or darkened areas, "
            f"because the website adds its own overlay.{optional}"
        )
