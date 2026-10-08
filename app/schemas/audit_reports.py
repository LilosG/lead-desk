from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AuditReportOption(BaseModel):
    signal: str
    title: str
    category: str
    disposition: Literal["recommended", "optional", "review_required"]
    default_selected: bool
    evidence: str | None = None


class AuditReportOptionsResponse(BaseModel):
    place_id: str
    business_name: str
    options: list[AuditReportOption]


class AuditReportCreateRequest(BaseModel):
    selected_signals: list[str] = Field(min_length=1, max_length=12)


class AuditReportSummary(BaseModel):
    id: str
    place_id: str
    report_version: int
    status: str
    title: str
    selected_signals: list[str]
    source_checked_at: datetime | None = None
    created_at: datetime


class AuditReportDetail(AuditReportSummary):
    snapshot: dict


class AuditReportBatchRequest(BaseModel):
    place_ids: list[str] = Field(min_length=1, max_length=50)


class AuditReportBatchItem(BaseModel):
    place_id: str
    status: Literal["created", "skipped"]
    report_id: str | None = None
    detail: str | None = None


class AuditReportBatchResponse(BaseModel):
    items: list[AuditReportBatchItem]
    created: int
    skipped: int
