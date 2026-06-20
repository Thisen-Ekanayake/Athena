"""
Athena Layer 5 — Sources Router

GET  /api/v1/sources            — list all sources
POST /api/v1/sources            — add source with auto-detect + preview
PUT  /api/v1/sources/{id}/toggle — enable/disable a source
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from athena.api.deps import get_db
from athena.api.schemas import (
    SourceResponse, SourceCreateRequest, SourceToggleResponse,
)
from athena.core.models import Source

router = APIRouter(prefix="/api/v1", tags=["Sources"])


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(
    type: str | None = Query(None),
    added_by: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns all sources with authority score and last fetch time.
    """
    query = select(Source)

    if type:
        query = query.where(Source.type == type)
    if added_by:
        query = query.where(Source.added_by == added_by)

    query = query.order_by(Source.name)
    sources = db.execute(query).scalars().all()

    return [
        SourceResponse(
            id=s.id,
            name=s.name,
            url=str(s.url),
            type=s.type.value if hasattr(s.type, 'value') else str(s.type),
            category=s.category.value if hasattr(s.category, 'value') else str(s.category),  # noqa: E501
            authority_score=s.authority_score or 0.5,
            is_active=s.is_active,
            added_by=s.added_by or "system",
            last_fetched_at=s.last_fetched_at,
            consecutive_failures=s.consecutive_failures or 0,
        )
        for s in sources
    ]


@router.post("/sources")
def add_source(
    request: SourceCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Add a custom source via a two-step flow:

    - `confirm=False` (default): auto-detect the type and return a preview
      (`source_type`, `source_name`, `sample_items`) without writing anything.
    - `confirm=True`: persist the source and queue its first crawl.

    Both responses share the same shape so the frontend can render either.
    """
    from athena.database.user_sources import (
        preview_source, add_user_source,
    )

    # Step 1: Preview / auto-detect (no DB write).
    preview = preview_source(request.url, request.name)

    if preview.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach this URL — {preview['error']}",
        )

    # Preview-only request — let the user review before committing.
    if not request.confirm:
        return preview

    # Step 2: Persist the source and queue its first crawl.
    result = add_user_source(
        url=request.url,
        name=request.name,
        category=request.category,
    )

    return {
        "source_type": result["type"],
        "source_name": result["name"],
        "sample_items": preview.get("sample_items", []),
        "id": result["id"],
        "queued": result["queued"],
    }


@router.put("/sources/{source_id}/toggle", response_model=SourceToggleResponse)
def toggle_source(
    source_id: str,
    db: Session = Depends(get_db),
):
    """
    Toggle a source's is_active status (enable/disable).
    """
    try:
        source_uuid = UUID(source_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid source ID format"
        )

    source = db.execute(
        select(Source).where(Source.id == source_uuid)
    ).scalar_one_or_none()

    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    new_status = not source.is_active

    db.execute(
        update(Source)
        .where(Source.id == source_uuid)
        .values(is_active=new_status)
    )
    db.commit()

    action = "enabled" if new_status else "disabled"
    return SourceToggleResponse(
        id=source.id,
        is_active=new_status,
        message=f"Source '{source.name}' has been {action}",
    )
