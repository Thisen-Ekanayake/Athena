import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from athena.api.deps import get_db
from athena.core import llm
from athena.core.config_store import get_setting
from athena.core.models import AppSetting

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])

ALLOWED_KEYS = {"LLM_API_KEY", "EMBED_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"}

# Model settings that are not secrets; an empty value falls back to the environment, then the default.
MODEL_SETTINGS = {
    "LLM_BASE_URL": llm.DEFAULT_BASE_URL,
    "LLM_CHAT_MODEL": llm.DEFAULT_CHAT_MODEL,
    "LLM_SUMMARY_MODEL": "",
    "LLM_QA_MODEL": "",
    "LLM_LIT_REVIEW_MODEL": "",
    "LLM_SERVER": "",
    "LLM_PRICE_IN_PER_M": "0",
    "LLM_PRICE_OUT_PER_M": "0",
    "EMBED_BASE_URL": "",
    "EMBED_MODEL": llm.DEFAULT_EMBED_MODEL,
    "EMBED_DIMENSIONS": "",
}


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


# ── Models ──────────────────────────────────────────────


class ModelSettingsUpdate(BaseModel):
    values: dict[str, str]


def _model_settings() -> dict:
    return {
        "values": {key: get_setting(key) for key in MODEL_SETTINGS},
        "defaults": MODEL_SETTINGS,
        "effective": {
            "chat_base_url": llm.chat_base_url(),
            "chat_model": llm.chat_model(),
            "embed_base_url": llm.embed_base_url(),
            "embed_model": llm.embed_model(),
            "llama_cpp": llm.is_llama_cpp(),
        },
        # Which model made the stored vectors: changing EMBED_MODEL means re-embedding these.
        "embed_spaces": {space: get_setting(f"EMBED_SPACE_{space.upper()}") or None for space in ("feed", "evolution")},
    }


@router.get("/models")
def get_model_settings():
    return _model_settings()


@router.put("/models")
def update_model_settings(body: ModelSettingsUpdate, db: Session = Depends(get_db)):
    unknown = set(body.values) - set(MODEL_SETTINGS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {', '.join(sorted(unknown))}")
    for key, value in body.values.items():
        value = value.strip()
        if key in ("LLM_PRICE_IN_PER_M", "LLM_PRICE_OUT_PER_M", "EMBED_DIMENSIONS") and value:
            try:
                float(value)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{key} must be a number")
        row = db.get(AppSetting, key)
        if not value:
            if row:
                db.delete(row)
        elif row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            db.add(AppSetting(key=key, value=value, updated_at=datetime.utcnow()))
    db.commit()
    return _model_settings()


def _timed(call) -> dict:
    start = time.time()
    try:
        detail = call()
        return {"ok": True, "latency_ms": int((time.time() - start) * 1000), **detail}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.time() - start) * 1000), "error": str(exc)[:300]}


@router.post("/models/test")
def test_models():
    """One tiny chat call and one embedding, so a new endpoint or model can be checked from the UI."""
    def chat():
        model = llm.chat_model()
        res = llm.chat_client(timeout=120).chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Reply with the word ready."}],
            max_tokens=5, extra_body=llm.chat_extra())
        return {"model": model, "reply": (res.choices[0].message.content or "").strip()[:40]}

    def embed():
        return {"model": llm.embed_model(), "dimensions": int(llm.embed(["ready"], timeout=120).shape[1])}

    return {"chat": _timed(chat), "embed": _timed(embed)}
