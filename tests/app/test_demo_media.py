import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services.demo_media import DemoMediaError, DemoMediaService


class FakeProspectRepository:
    def get_prospect(self, place_id):
        if place_id != "volt-place":
            return None
        return {
            "place_id": place_id,
            "name": "Volt Electric",
            "city": "Vista",
            "state": "CA",
            "primary_type": "electrician",
        }


class FakeMediaRepository:
    def __init__(self):
        self.created = []

    def create_media(self, **kwargs):
        self.created.append(kwargs)
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2026-09-17T19:00:00Z",
            **{key: kwargs[key] for key in (
                "place_id", "role", "source", "model",
                "prompt_version", "public_url"
            )},
        }

    def list_for_prospect(self, place_id, *, limit=12):
        return []


class FakeResponse:
    def __init__(self, encoded, status_code=200):
        self.encoded = encoded
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        url = f"data:image/png;base64,{self.encoded}"
        return {"choices": [{"message": {"images": [{"image_url": {"url": url}}]}}]}


def png_bytes(width=3000, height=1600):
    out = BytesIO()
    Image.new("RGB", (width, height), "#336699").save(out, "PNG")
    return out.getvalue()


def test_demo_media_generation_is_explicit_single_role_and_persisted(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(base64.b64encode(png_bytes()).decode("ascii"))

    monkeypatch.setattr("app.services.demo_media.requests.post", fake_post)
    repository = FakeMediaRepository()
    service = DemoMediaService(FakeProspectRepository(), repository)

    result = service.generate(
        "volt-place",
        role="hero",
        api_key="test-key",
        model="google/gemini-2.5-flash-image",
        root=tmp_path,
        base_url="https://demo.example.test",
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["json"]["model"] == "google/gemini-2.5-flash-image"
    assert captured["json"]["modalities"] == ["image", "text"]
    assert captured["json"]["image_config"] == {"aspect_ratio": "16:9"}
    prompt = captured["json"]["messages"][0]["content"].lower()
    assert "do not place any business name, logo" in prompt
    assert "show no people" in prompt and "never a collage" in prompt
    assert "southern california" not in prompt
    assert result["role"] == "hero"
    assert result["public_url"].startswith("https://demo.example.test/_media/")
    stored = Path(repository.created[0]["storage_path"])
    with Image.open(stored) as saved:
        assert saved.format == "WEBP"
        assert saved.width == 2000


def test_image_only_models_get_a_second_attempt(monkeypatch, tmp_path):
    attempts = []

    def fake_post(url, *, headers, json, timeout):
        attempts.append(json["modalities"])
        encoded = base64.b64encode(png_bytes(800, 450)).decode("ascii")
        return FakeResponse(encoded, status_code=400 if len(attempts) == 1 else 200)

    monkeypatch.setattr("app.services.demo_media.requests.post", fake_post)
    DemoMediaService(FakeProspectRepository(), FakeMediaRepository()).generate(
        "volt-place", role="hero", api_key="k", model="bytedance-seed/seedream-4.5",
        root=tmp_path, base_url="https://demo.example.test",
    )
    assert attempts == [["image", "text"], ["image"]]


def test_prompt_follows_the_niche_not_home_services():
    prompt = DemoMediaService._prompt(
        {"name": "Glow", "city": "Scottsdale", "state": "AZ", "primary_type": "spa", "vertical": "med_spa"},
        role="hero", direction=None,
    )
    assert "treatment suite" in prompt and "Scottsdale, AZ" in prompt


def test_demo_media_rejects_invalid_role_before_provider_call(tmp_path):
    service = DemoMediaService(FakeProspectRepository(), FakeMediaRepository())
    with pytest.raises(DemoMediaError, match="invalid demo image role"):
        service.generate(
            "volt-place",
            role="gallery",
            api_key="test-key",
            model="bytedance-seed/seedream-4.5",
            root=tmp_path,
            base_url="https://demo.example.test",
        )


def test_demo_media_requires_existing_prospect(tmp_path):
    service = DemoMediaService(FakeProspectRepository(), FakeMediaRepository())
    with pytest.raises(DemoMediaError, match="prospect not found"):
        service.generate(
            "missing-place",
            role="hero",
            api_key="test-key",
            model="bytedance-seed/seedream-4.5",
            root=tmp_path,
            base_url="https://demo.example.test",
        )


def test_each_trade_gets_its_own_scene_and_direction_overrides_it():
    electrician = DemoMediaService._prompt(
        {"primary_type": "electrician", "vertical": "electrician", "city": "Tucson", "state": "AZ"},
        role="hero", direction=None,
    )
    plumber = DemoMediaService._prompt(
        {"primary_type": "plumber", "vertical": "plumber"}, role="hero", direction=None,
    )
    # Heroes are calm architectural shots of the trade's finished work; close-up craft is the work photo.
    assert "EV charger" in electrician and "Tucson, AZ" in electrician
    assert "chrome faucet" in plumber and "EV charger" not in plumber
    work = DemoMediaService._prompt({"primary_type": "plumber", "vertical": "plumber"}, role="work", direction=None)
    assert "copper pipework" in work

    directed = DemoMediaService._prompt(
        {"primary_type": "plumber", "vertical": "plumber"}, role="hero", direction="water heater in a garage",
    )
    assert "takes priority over the scene described above: water heater in a garage" in directed


def test_a_niche_without_its_own_scene_keeps_the_general_one():
    prompt = DemoMediaService._prompt(
        {"primary_type": "dentist", "vertical": "dentist"}, role="hero", direction=None,
    )
    assert "dental studio" in prompt
