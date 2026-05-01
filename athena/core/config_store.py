import os
from loguru import logger


def get_setting(key: str, default: str = "") -> str:
    """Return a config value — DB takes precedence over env var."""
    try:
        from athena.database.db import SessionLocal
        from athena.core.models import AppSetting
        with SessionLocal() as db:
            row = db.get(AppSetting, key)
            if row and row.value:
                return row.value
    except Exception as e:
        logger.debug(f"config_store DB lookup failed for {key}, falling back to env: {e}")
    return os.getenv(key, default)
