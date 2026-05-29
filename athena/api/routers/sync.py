import json
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from athena.pipeline.celery_app import celery_app
from athena.core.logging import SYNC_LOG_CHANNEL
from athena.core.redis_client import get_redis
import asyncio
from loguru import logger

router = APIRouter(prefix="/api/v1/sync", tags=["Sync"])


@router.post("")
async def trigger_sync(background_tasks: BackgroundTasks):
    """
    Trigger a manual sync of all active sources.
    This runs the crawl_all_sources task in the background (via Celery).
    """
    logger.info("Manual sync triggered via API")
    celery_app.send_task("athena.pipeline.tasks.crawl_all_sources")
    return {"status": "Sync triggered", "message": "Scraping pipeline has been started in the background."}


@router.get("/events")
async def sync_events(request: Request):
    """
    Stream live sync logs to the client via Server-Sent Events (SSE).
    """
    async def log_generator():
        r = get_redis()
        pubsub = r.pubsub()
        pubsub.subscribe(SYNC_LOG_CHANNEL)

        try:
            # Send initial message
            yield f"data: {json.dumps({'message': 'Connection established. Waiting for logs...'})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                # Check for messages
                message = pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    log_data = message['data']
                    if isinstance(log_data, bytes):
                        log_data = log_data.decode('utf-8')

                    yield f"data: {json.dumps({'message': log_data})}\n\n"

                await asyncio.sleep(0.1)  # Avoid pegging CPU
        except Exception as e:
            logger.error(f"Error in log generator: {e}")
        finally:
            pubsub.unsubscribe(SYNC_LOG_CHANNEL)
            pubsub.close()

    return StreamingResponse(log_generator(), media_type="text/event-stream")
