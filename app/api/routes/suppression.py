import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.database import pool
from app.repositories.suppression import SuppressionRepository

router = APIRouter(prefix='/api/suppression', tags=['suppression'])

_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class SuppressionAdd(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    reason: str | None = Field(default=None, max_length=200)


def _clean(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.match(cleaned):
        raise HTTPException(status_code=422, detail="That isn't a valid email address.")
    return cleaned


@router.get('')
def list_suppressed() -> list[dict]:
    return SuppressionRepository(pool).list()


@router.post('')
def add_suppressed(payload: SuppressionAdd) -> dict:
    reason = (payload.reason or '').strip() or 'asked to be removed'
    return SuppressionRepository(pool).add(_clean(payload.email), reason)


@router.delete('/{email}')
def remove_suppressed(email: str) -> dict:
    if not SuppressionRepository(pool).remove(_clean(email)):
        raise HTTPException(status_code=404, detail='email is not on the list')
    return {'removed': _clean(email)}
