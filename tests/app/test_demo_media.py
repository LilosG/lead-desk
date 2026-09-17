import base64
from pathlib import Path

import pytest

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
    ok = True
    status_code = 200

    def __init__(self, encoded):
        self.encoded = encoded

    def json(self):
        return {"data": [{"b64_json": self.encoded}]}


def test_demo_media_generation_is_explicit_single_role_and_persisted(monkeypatch, tmp_path):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-image"
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(base64.b64encode(png_bytes).decode("ascii"))

    monkeypatch.setattr("app.services.demo_media.requests.post", fake_post)
    repository = FakeMediaRepository()
    service = DemoMediaService(FakeProspectRepository(), repository)

    result = service.generate(
        "volt-place",
        role="hero",
        api_key="test-key",
        model="bytedance-seed/seedream-4.5",
        root=tmp_path,
        base_url="https://demo.example.test",
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/images"
    assert captured["json"]["model"] == "bytedance-seed/seedream-4.5"
    assert captured["json"]["aspect_ratio"] == "16:9"
    assert "do not place any business name, logo" in captured["json"]["prompt"].lower()
    assert "do not imply that generated people are the real owner or employees" in captured["json"]["prompt"].lower()
    assert result["role"] == "hero"
    assert result["public_url"].startswith("https://demo.example.test/_media/")
    stored = Path(repository.created[0]["storage_path"])
    assert stored.exists()
    assert stored.read_bytes() == png_bytes


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
