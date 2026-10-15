"""Starting a sync of every source, and its progress for the sidebar and the sync dialog."""
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from athena.api import auth
from athena.api.deps import get_redis
from athena.core.models import User
from athena.database.operations import fetch_durations, get_active_sources
from athena.pipeline import sync_status
from athena.pipeline.celery_app import celery_app

router = APIRouter(prefix="/api/v1/sync", tags=["Sync"])


@router.post("", dependencies=[Depends(auth.require_admin)])
def trigger_sync(r=Depends(get_redis)):
    """Crawl every active source in the background; 409 while a sync is already running.

    The sync is opened here, not in the worker, so its progress shows at once, including when the worker
    is busy or down (the status then says it is waiting for the worker).
    """
    sources = get_active_sources()
    if not sources:
        raise HTTPException(status_code=400, detail="There are no active sources to sync")
    durations = fetch_durations([s.id for s in sources])
    sync_id = sync_status.start(r, [(str(s.id), s.name, durations.get(str(s.id))) for s in sources], "manual")
    if sync_id is None:
        raise HTTPException(status_code=409, detail="A sync is already running")
    logger.info("Manual sync triggered via API")
    celery_app.send_task("athena.pipeline.tasks.crawl_all_sources", kwargs={"sync_id": sync_id})
    return sync_status.status(r)


@router.get("/status")
def sync_progress(
    log: bool = Query(False, description="Include the log lines (admins only)"),
    log_after: int = Query(0, ge=0, description="Only log lines after this sequence number"),
    user: User = Depends(auth.active_user),
    r=Depends(get_redis),
):
    """The latest sync's progress. Its log (source URLs and errors) is for admins only, and only when asked."""
    return sync_status.status(r, with_log=log and user.role == "admin", log_after=log_after)
