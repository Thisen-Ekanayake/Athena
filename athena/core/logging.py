from loguru import logger

from athena.core.redis_client import get_redis


class RedisSink:
    """Keeps a sync's log lines with the sync, so the UI can show them during the sync and after it."""

    def __init__(self):
        self.redis_client = get_redis()

    def write(self, message):
        from athena.pipeline import sync_status
        try:
            sync_status.log(self.redis_client, message.record["extra"]["sync_id"], message.strip())
        except Exception as e:
            # Don't use the logger here to avoid infinite recursion if it fails
            print(f"Failed to store a sync log line in Redis: {e}")


def setup_redis_logging():
    """Add a Redis sink to loguru for the lines logged inside a sync (``logger.contextualize(sync_id=...)``)."""
    sink = RedisSink()
    logger.add(sink.write, level="INFO", format="{time:HH:mm:ss} | {level: <8} | {message}",
               filter=lambda record: bool(record["extra"].get("sync_id")))
    return sink
