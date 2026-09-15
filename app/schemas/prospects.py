from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Pagination


WorkflowStatus = Literal[
    "new",
    "researching",
    "qualified",
    "outreach_ready",
    "contacted",
    "replied",
    "won",
    "lost",
    "disqualified",
]

WorkflowPriority = Literal["low", "normal", "high", "urgent"]


class ProspectListItem(BaseModel):
    place_id: str
    name: str | None
    city: str | None
    vertical: str | None

    total_score: int
    tier: str | None
    headline_gap: str | None

    phone: str | None
    email: str | None
    website_url: str | None

    rating: float | None
    review_count: int | None

    psi_performance: int | None
    cms_detected: str | None

    business_status: str | None
    last_review_days: int | None
    recent_reviews_90d: int | None

    confirmed_trading: bool
    category_opportunity: bool
    established: bool
    real_gap_count: int

    needs_manual_check: bool
    scored_at: datetime


class ProspectListResponse(BaseModel):
    items: list[ProspectListItem]
    pagination: Pagination


class AuditFinding(BaseModel):
    category: str | None
    severity: str | None
    points: int | None
    finding: str | None
    signal: str | None
    observed: Any = None


class WebsiteAudit(BaseModel):
    checked_at: datetime | None
    resolved_url: str | None
    http_status: int | None
    is_reachable: bool | None
    has_ssl: bool | None
    redirects_to: str | None

    title: str | None
    title_length: int | None
    meta_description: str | None
    meta_desc_length: int | None
    h1_text: str | None
    h1_count: int | None
    word_count: int | None
    page_count_estimate: int | None

    has_localbusiness_schema: bool | None
    schema_types: list[str] | None

    nap_phone_on_site: str | None
    nap_address_on_site: str | None
    nap_matches_gbp: bool | None

    has_service_pages: bool | None
    has_city_pages: bool | None
    has_gbp_link: bool | None
    has_contact_form: bool | None
    contact_page_url: str | None

    emails_found: list[str] | None
    phones_found: list[str] | None
    social_profiles: dict[str, Any] | None

    cms_detected: str | None
    is_template_builder: bool | None

    psi_performance: int | None
    psi_seo: int | None
    psi_accessibility: int | None
    psi_best_practices: int | None
    psi_lcp_ms: int | None
    psi_cls: float | None
    psi_mobile_friendly: bool | None

    crawl_error: str | None


class ProspectWorkflowState(BaseModel):
    status: WorkflowStatus = "new"
    priority: WorkflowPriority = "normal"
    owner: str | None = None
    next_action: str | None = None
    next_action_at: datetime | None = None
    notes: str | None = None
    version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProspectWorkflowEvent(BaseModel):
    id: str
    event_type: Literal["created", "updated"]
    changes: dict[str, Any]
    created_at: datetime


class ProspectWorkflowUpdate(BaseModel):
    status: WorkflowStatus | None = None
    priority: WorkflowPriority | None = None
    owner: str | None = Field(default=None, max_length=120)
    next_action: str | None = Field(default=None, max_length=500)
    next_action_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10000)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "ProspectWorkflowUpdate":
        for field_name in ("status", "priority"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ProspectDetail(BaseModel):
    place_id: str
    name: str | None
    vertical: str | None
    primary_type: str | None
    types: list[str] | None
    business_status: str | None

    formatted_address: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    lat: float | None
    lng: float | None

    phone: str | None
    email: str | None
    website_url: str | None
    google_maps_uri: str | None

    rating: float | None
    review_count: int | None
    last_review_days: int | None
    recent_reviews_90d: int | None
    has_hours: bool | None
    photo_count: int | None

    total_score: int
    tier: str | None
    headline_gap: str | None
    gbp_gap_score: int | None
    website_gap_score: int | None
    reachability_score: int | None
    scored_at: datetime

    confirmed_trading: bool
    category_opportunity: bool
    established: bool
    real_gap_count: int

    what_to_fix: str | None
    major_issues: int
    needs_manual_check: bool

    website_audit: WebsiteAudit | None
    findings: list[AuditFinding]
    workflow: ProspectWorkflowState
    workflow_events: list[ProspectWorkflowEvent]


class ProspectFilterMeta(BaseModel):
    cities: list[str]
    verticals: list[str]
    tiers: list[str]
    total_prospects: int
