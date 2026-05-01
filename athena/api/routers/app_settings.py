from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from athena.api.deps import get_db
from athena.core.models import AppSetting

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])

ALLOWED_KEYS = {"OPENAI_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


class ApiKeyResponse(BaseModel):
    key: str
    masked_value: Optional[str]
    is_set: bool
    updated_at: Optional[str]


class ApiKeyUpdate(BaseModel):
    value: str


@router.get("/keys", response_model=list[ApiKeyResponse])
def get_api_keys(db: Session = Depends(get_db)):
    results = []
    for key in sorted(ALLOWED_KEYS):
        row = db.get(AppSetting, key)
        results.append(ApiKeyResponse(
            key=key,
            masked_value=_mask(row.value) if row and row.value else None,
            is_set=bool(row and row.value),
            updated_at=row.updated_at.isoformat() if row and row.updated_at else None,
        ))
    return results


@router.post("/keys/{key}", response_model=ApiKeyResponse)
def set_api_key(key: str, body: ApiKeyUpdate, db: Session = Depends(get_db)):
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {key}")
    if not body.value.strip():
        raise HTTPException(status_code=422, detail="Value cannot be empty")
    row = db.get(AppSetting, key)
    if row:
        row.value = body.value.strip()
        row.updated_at = datetime.utcnow()
    else:
        row = AppSetting(key=key, value=body.value.strip(), updated_at=datetime.utcnow())
        db.add(row)
    db.commit()
    db.refresh(row)
    return ApiKeyResponse(
        key=row.key,
        masked_value=_mask(row.value),
        is_set=True,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.delete("/keys/{key}")
def delete_api_key(key: str, db: Session = Depends(get_db)):
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {key}")
    row = db.get(AppSetting, key)
    if row:
        db.delete(row)
        db.commit()
    return {"key": key, "is_set": False}
