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


def set_setting(key: str, value: str) -> None:
    """Store a value in the settings table, where it overrides the environment."""
    from datetime import datetime
    from athena.database.db import SessionLocal
    from athena.core.models import AppSetting
    with SessionLocal() as db:
        row = db.get(AppSetting, key)
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            db.add(AppSetting(key=key, value=value, updated_at=datetime.utcnow()))
        db.commit()
