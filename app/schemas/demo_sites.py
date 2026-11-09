from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DemoSiteCreateRequest(BaseModel):
    template_key: str = "trade-modern-v3"
    services: list[str] = Field(default_factory=list, max_length=12)
    service_areas: list[str] = Field(default_factory=list, max_length=16)
    headline: str | None = Field(default=None, max_length=120)
    subheadline: str | None = Field(default=None, max_length=280)
    hero_image_url: str | None = Field(default=None, max_length=2048)
    work_image_url: str | None = Field(default=None, max_length=2048)
    secondary_image_url: str | None = Field(default=None, max_length=2048)
    use_site_branding: bool = True
    about: str | None = Field(default=None, max_length=600)
    service_blurbs: dict[str, str] = Field(default_factory=dict, max_length=12)


class DemoCopyRequest(BaseModel):
    services: list[str] = Field(default_factory=list, max_length=12)
    service_areas: list[str] = Field(default_factory=list, max_length=16)


class DemoCopyResponse(BaseModel):
    headline: str | None = None
    subheadline: str | None = None
    about: str | None = None
    service_blurbs: dict[str, str] = Field(default_factory=dict)
    model: str


class DemoMediaGenerateRequest(BaseModel):
    role: Literal["hero", "work", "secondary"]
    direction: str | None = Field(default=None, max_length=300)


class DemoMediaItem(BaseModel):
    id: str
    place_id: str
    role: str
    source: str
    model: str | None = None
    prompt_version: str | None = None
    public_url: str
    created_at: datetime


class DemoSiteOptionsResponse(BaseModel):
    place_id: str
    business_name: str
    templates: list[dict[str, str]]
    defaults: dict[str, Any]
    ai_copy_available: bool = False


class DemoSiteSummary(BaseModel):
    id: str
    place_id: str
    demo_version: int
    status: str
    template_key: str
    slug: str
    public_url: str | None = None
    build_error: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class DemoSiteDetail(DemoSiteSummary):
    source_snapshot: dict[str, Any]
    content_snapshot: dict[str, Any]
    brand_snapshot: dict[str, Any]
    published_path: str | None = None
