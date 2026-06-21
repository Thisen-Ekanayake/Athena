"""
Athena Layer 5 — Saved Lists Router

User-created collections (e.g. "NLP", "Computer Vision") of content items.

GET    /api/v1/lists                       — list all lists (with item counts)
POST   /api/v1/lists                       — create a list
PATCH  /api/v1/lists/{list_id}             — rename a list
DELETE /api/v1/lists/{list_id}             — delete a list
GET    /api/v1/lists/{list_id}/items       — content items saved in a list
POST   /api/v1/lists/{list_id}/items       — add a content item to a list
DELETE /api/v1/lists/{list_id}/items/{item_id} — remove an item from a list

Passing ?item_id=<uuid> to GET /lists adds a `contains_item` flag to each list,
used by the per-card "add to list" menu.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from athena.api.deps import get_db
from athena.api.schemas import (
    SavedListResponse, SavedListCreateRequest, SavedListUpdateRequest,
    AddItemToListRequest,
)
from athena.api.routers.feed import _build_feed_item
from athena.core.models import SavedList, SavedListItem, ContentItem

router = APIRouter(prefix="/api/v1", tags=["Saved Lists"])


def _parse_uuid(value: str, label: str = "ID") -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {label} format")


def _get_list_or_404(db: Session, list_uuid: UUID) -> SavedList:
    saved_list = db.execute(
        select(SavedList).where(SavedList.id == list_uuid)
    ).scalar_one_or_none()
    if not saved_list:
        raise HTTPException(status_code=404, detail="List not found")
    return saved_list


@router.get("/lists", response_model=list[SavedListResponse])
def list_lists(
    item_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """All saved lists with their item counts, newest first."""
    counts = dict(
        db.execute(
            select(SavedListItem.list_id, func.count(SavedListItem.id))
            .group_by(SavedListItem.list_id)
        ).all()
    )

    contains: set = set()
    if item_id is not None:
        item_uuid = _parse_uuid(item_id, "item ID")
        contains = {
            row[0]
            for row in db.execute(
                select(SavedListItem.list_id)
                .where(SavedListItem.item_id == item_uuid)
            ).all()
        }

    lists = db.execute(
        select(SavedList).order_by(SavedList.created_at.desc())
    ).scalars().all()

    return [
        SavedListResponse(
            id=lst.id,
            name=lst.name,
            item_count=counts.get(lst.id, 0),
            created_at=lst.created_at,
            contains_item=(lst.id in contains) if item_id is not None else None,
        )
        for lst in lists
    ]


@router.post("/lists", response_model=SavedListResponse, status_code=201)
def create_list(
    request: SavedListCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a new (uniquely named) list."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="List name cannot be empty")

    existing = db.execute(
        select(SavedList).where(func.lower(SavedList.name) == name.lower())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"A list named '{name}' already exists")

    saved_list = SavedList(name=name)
    db.add(saved_list)
    db.commit()
    db.refresh(saved_list)

    return SavedListResponse(
        id=saved_list.id,
        name=saved_list.name,
        item_count=0,
        created_at=saved_list.created_at,
    )


@router.patch("/lists/{list_id}", response_model=SavedListResponse)
def rename_list(
    list_id: str,
    request: SavedListUpdateRequest,
    db: Session = Depends(get_db),
):
    """Rename a list."""
    list_uuid = _parse_uuid(list_id, "list ID")
    saved_list = _get_list_or_404(db, list_uuid)

    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="List name cannot be empty")

    clash = db.execute(
        select(SavedList).where(
            func.lower(SavedList.name) == name.lower(),
            SavedList.id != list_uuid,
        )
    ).scalar_one_or_none()
    if clash:
        raise HTTPException(status_code=409, detail=f"A list named '{name}' already exists")

    saved_list.name = name
    db.commit()

    count = db.execute(
        select(func.count(SavedListItem.id)).where(SavedListItem.list_id == list_uuid)
    ).scalar() or 0

    return SavedListResponse(
        id=saved_list.id,
        name=saved_list.name,
        item_count=count,
        created_at=saved_list.created_at,
    )


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(
    list_id: str,
    db: Session = Depends(get_db),
):
    """Delete a list and all of its memberships."""
    list_uuid = _parse_uuid(list_id, "list ID")
    saved_list = _get_list_or_404(db, list_uuid)
    db.delete(saved_list)
    db.commit()


@router.get("/lists/{list_id}/items")
def get_list_items(
    list_id: str,
    db: Session = Depends(get_db),
):
    """Content items saved in a list, newest-added first, as feed cards."""
    list_uuid = _parse_uuid(list_id, "list ID")
    _get_list_or_404(db, list_uuid)

    rows = db.execute(
        select(ContentItem)
        .join(SavedListItem, SavedListItem.item_id == ContentItem.id)
        .where(SavedListItem.list_id == list_uuid)
        .order_by(SavedListItem.added_at.desc())
    ).scalars().all()

    return {"items": [_build_feed_item(item) for item in rows]}


@router.post("/lists/{list_id}/items", status_code=201)
def add_item_to_list(
    list_id: str,
    request: AddItemToListRequest,
    db: Session = Depends(get_db),
):
    """Add a content item to a list (idempotent)."""
    list_uuid = _parse_uuid(list_id, "list ID")
    _get_list_or_404(db, list_uuid)

    item = db.execute(
        select(ContentItem).where(ContentItem.id == request.item_id)
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")

    existing = db.execute(
        select(SavedListItem).where(
            SavedListItem.list_id == list_uuid,
            SavedListItem.item_id == request.item_id,
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(SavedListItem(list_id=list_uuid, item_id=request.item_id))
        db.commit()

    return {"list_id": str(list_uuid), "item_id": str(request.item_id), "added": True}


@router.delete("/lists/{list_id}/items/{item_id}", status_code=204)
def remove_item_from_list(
    list_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    """Remove a content item from a list."""
    list_uuid = _parse_uuid(list_id, "list ID")
    item_uuid = _parse_uuid(item_id, "item ID")

    db.execute(
        delete(SavedListItem).where(
            SavedListItem.list_id == list_uuid,
            SavedListItem.item_id == item_uuid,
        )
    )
    db.commit()
