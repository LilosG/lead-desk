from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DemoSiteCreateRequest(BaseModel):
    template_key: str = "trade-modern-v1"
    services: list[str] = Field(default_factory=list, max_length=6)
    service_areas: list[str] = Field(default_factory=list, max_length=8)
    headline: str | None = Field(default=None, max_length=120)
    subheadline: str | None = Field(default=None, max_length=280)


class DemoSiteOptionsResponse(BaseModel):
    place_id: str
    business_name: str
    templates: list[dict[str, str]]
    defaults: dict[str, Any]


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
