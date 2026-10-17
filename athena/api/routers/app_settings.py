import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api.deps import get_db, get_redis
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
    "EMBED_PRICE_PER_M": "0",
}
NUMERIC_MODEL_SETTINGS = {"LLM_PRICE_IN_PER_M", "LLM_PRICE_OUT_PER_M", "EMBED_DIMENSIONS", "EMBED_PRICE_PER_M"}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


class ApiKeyResponse(BaseModel):
    key: str
    masked_value: Optional[str]
    is_set: bool
    updated_at: Optional[str]
    # Where the value in use comes from: a saved value overrides the environment file, as in get_setting.
    source: Optional[str] = None  # database | environment


class ApiKeyUpdate(BaseModel):
    value: str


@router.get("/keys", response_model=list[ApiKeyResponse])
def get_api_keys(db: Session = Depends(get_db)):
    results = []
    for key in sorted(ALLOWED_KEYS):
        row = db.get(AppSetting, key)
        if row and row.value:
            results.append(ApiKeyResponse(
                key=key, masked_value=_mask(row.value), is_set=True, source="database",
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            ))
        elif env := os.getenv(key, "").strip():
            results.append(ApiKeyResponse(key=key, masked_value=_mask(env), is_set=True, updated_at=None,
                                          source="environment"))
        else:
            results.append(ApiKeyResponse(key=key, masked_value=None, is_set=False, updated_at=None))
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
        source="database",
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


def save_settings(db: Session, values: dict[str, str], allowed, numeric=(), whole=()) -> None:
    """Store ``values`` in the settings table; an empty value deletes the row, so the environment applies again.

    Every key must be in ``allowed``; those in ``numeric`` must be numbers no lower than 0, and those in ``whole``
    whole numbers.
    """
    unknown = set(values) - set(allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        value = value.strip()
        if (key in numeric or key in whole) and value:
            try:
                number = int(value) if key in whole else float(value)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{key} must be a {'whole ' if key in whole else ''}number")
            if number < 0:
                raise HTTPException(status_code=422, detail=f"{key} can't be negative")
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


@router.put("/models")
def update_model_settings(body: ModelSettingsUpdate, db: Session = Depends(get_db)):
    save_settings(db, body.values, MODEL_SETTINGS, NUMERIC_MODEL_SETTINGS)
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


# ── Scoring weights ─────────────────────────────────────


class CategoryWeights(BaseModel):
    citation: float = Field(..., ge=0, le=1)
    engagement: float = Field(..., ge=0, le=1)
    recency: float = Field(..., ge=0, le=1)
    authority: float = Field(..., ge=0, le=1)
    preference: float = Field(..., ge=0, le=0.8)
    half_life_days: int = Field(..., ge=1, le=365)


class ScoringUpdate(BaseModel):
    categories: dict[str, CategoryWeights]


def _scoring(db: Session) -> dict:
    from athena.pipeline.scoring import BASE_SIGNALS, DEFAULT_WEIGHTS, _get_weights
    out = {}
    for category in DEFAULT_WEIGHTS:
        weights = _get_weights(category, db)
        out[category] = {k: weights[k] for k in (*BASE_SIGNALS, "preference", "half_life_days")} | {
            "version": weights.get("version") if weights.get("saved") else None,
            "source": "saved" if weights.get("saved") else "default"}
    return {"categories": out, "defaults": DEFAULT_WEIGHTS}


@router.get("/scoring")
def get_scoring(db: Session = Depends(get_db)):
    """Each category's signal weights, half-life and For-you preference weight; defaults until first saved."""
    return _scoring(db)


@router.put("/scoring")
def update_scoring(body: ScoringUpdate, db: Session = Depends(get_db), r=Depends(get_redis)):
    """Save new weights as a new ScoringConfig version per changed category. A change to the signal weights or the
    half-life rescores every item; a change to the preference weight only re-orders For-you feeds."""
    from sqlalchemy import func, select, update

    from athena.core.models import ContentCategory, ScoringConfig
    from athena.pipeline import interests
    from athena.pipeline.scoring import BASE_SIGNALS, DEFAULT_WEIGHTS, _get_weights
    unknown = set(body.categories) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown categories: {', '.join(sorted(unknown))}")
    for category, w in body.categories.items():
        total = sum(getattr(w, k) for k in BASE_SIGNALS)
        if abs(total - 1) > 0.001:
            raise HTTPException(status_code=422, detail=f"The {category} signal weights add up to {total:.3f}, not 1")
    rescore = reorder = False
    version = db.execute(select(func.max(ScoringConfig.version))).scalar() or 0
    for category, w in body.categories.items():
        current = _get_weights(category, db)
        new = w.model_dump()
        if all(abs(float(current[k]) - float(new[k])) < 1e-9 for k in new):
            continue
        rescore |= any(abs(float(current[k]) - float(new[k])) >= 1e-9 for k in (*BASE_SIGNALS, "half_life_days"))
        reorder |= abs(float(current["preference"]) - new["preference"]) >= 1e-9
        version += 1
        cat = ContentCategory(category)
        db.execute(update(ScoringConfig).where(ScoringConfig.category == cat, ScoringConfig.is_active.is_(True))
                   .values(is_active=False))
        db.add(ScoringConfig(
            version=version, category=cat, weight_citation=w.citation, weight_engagement=w.engagement,
            weight_recency=w.recency, weight_authority=w.authority,
            weight_preference=w.preference, half_life_days=w.half_life_days, is_active=True,
            notes="Settings → Scoring"))
    db.commit()
    if reorder:
        interests.bump(r)
    if rescore:
        try:
            _queue_rescore()
        except Exception as exc:  # no broker: the weights are saved; the 6-hourly refresh applies them
            logger.warning(f"Scoring: rescore not queued: {exc}")
            rescore = False
    return _scoring(db) | {"rescoring": rescore}


def _queue_rescore() -> None:
    from athena.pipeline.scoring import score_all_items
    score_all_items.delay()


# ── Feed ────────────────────────────────────────────────

class FeedSettingsUpdate(BaseModel):
    source_share: float = Field(..., gt=0, le=1)


def _feed_settings(db: Session) -> dict:
    from athena.api.routers.feed import DEFAULT_SOURCE_SHARE, FEED_SOURCE_SHARE
    row = db.get(AppSetting, FEED_SOURCE_SHARE)
    raw = row.value if row and row.value else os.getenv(FEED_SOURCE_SHARE, "")
    try:
        share = float(raw) if raw else DEFAULT_SOURCE_SHARE
    except ValueError:
        share = DEFAULT_SOURCE_SHARE
    return {"source_share": share, "default_source_share": DEFAULT_SOURCE_SHARE}


@router.get("/feed")
def get_feed_settings(db: Session = Depends(get_db)):
    """How the feed mixes sources: the most of a Score or For-you page one source may fill (1 is no cap)."""
    return _feed_settings(db)


@router.put("/feed")
def update_feed_settings(body: FeedSettingsUpdate, db: Session = Depends(get_db)):
    from athena.api.routers.feed import FEED_SOURCE_SHARE
    save_settings(db, {FEED_SOURCE_SHARE: f"{body.source_share:g}"}, {FEED_SOURCE_SHARE}, numeric={FEED_SOURCE_SHARE})
    return _feed_settings(db)
