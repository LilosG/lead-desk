from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


OutreachChannel = Literal['email', 'phone', 'form']
OutreachStatus = Literal[
    'queued',
    'researching',
    'review_required',
    'no_outreach_finding',
    'draft_ready',
    'approved',
    'contacted',
    'replied',
    'archived',
    'suppressed',
]
VerificationStatus = Literal['pending', 'verified', 'failed', 'not_required']


class OutreachQueueItem(BaseModel):
    id: str
    place_id: str
    name: str | None
    city: str | None
    vertical: str | None
    total_score: int | None
    tier: str | None
    headline_gap: str | None
    phone: str | None
    email: str | None
    channel: OutreachChannel
    status: OutreachStatus
    to_address: str | None
    subject: str | None
    body: str | None
    claim_signal: str | None
    verification_status: VerificationStatus
    verification_note: str | None
    generation_model: str | None = None
    generation_prompt_version: str | None = None
    draft_generated_at: datetime | None = None
    gmail_draft_id: str | None = None
    gmail_message_id: str | None = None
    gmail_draft_created_at: datetime | None = None
    suppressed: bool
    needs_manual_check: bool
    version: int
    created_at: datetime
    updated_at: datetime


class OutreachQueueResponse(BaseModel):
    items: list[OutreachQueueItem]
    total: int


class OutreachCreate(BaseModel):
    channel: OutreachChannel
    to_address: str | None = Field(default=None, max_length=320)


class OutreachUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    status: OutreachStatus | None = None
    to_address: str | None = Field(default=None, max_length=320)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)
    claim_signal: str | None = Field(default=None, max_length=120)
    verification_status: VerificationStatus | None = None
    verification_note: str | None = Field(default=None, max_length=2000)


class OutreachVersionAction(BaseModel):
    expected_version: int = Field(ge=1)
    angle: str | None = Field(default=None, max_length=40)
