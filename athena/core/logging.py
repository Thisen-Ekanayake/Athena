import json
import os
import redis
from loguru import logger

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SYNC_LOG_CHANNEL = "athena:sync:logs"

class RedisSink:
    def __init__(self):
        self.redis_client = redis.from_url(REDIS_URL)

    def write(self, message):
        # message is a string from loguru
        try:
            # We can parse the loguru message or just send it as is
            # For simplicity, we send the raw string
            self.redis_client.publish(SYNC_LOG_CHANNEL, message.strip())
        except Exception as e:
            # Don't use the logger here to avoid infinite recursion if it fails
            print(f"Failed to publish log to Redis: {e}")

def setup_redis_logging():
    """Add a Redis sink to loguru to stream sync logs."""
    sink = RedisSink()
    # We only want to stream INFO and above, and maybe filter by module if needed
    logger.add(sink.write, level="INFO", format="{time:HH:mm:ss} | {level: <8} | {message}")
    return sink
