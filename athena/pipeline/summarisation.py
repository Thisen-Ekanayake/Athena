"""
Athena Layer 4 — Summarisation Core Logic

Contains utilities for Redis-based budget tracking, Pydantic validation of OpenAI
responses, and core logic for formatting prompts and generating summaries.
"""
import os
import json
from datetime import datetime, timezone
from typing import List, Optional

import redis as redis_lib
from pydantic import BaseModel, validator
from loguru import logger
from sqlalchemy import select

from athena.core.models import PromptVersion, SummaryUsageLog, JobType

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis = redis_lib.from_url(REDIS_URL)
SUMMARY_DAILY_BUDGET_USD = float(os.getenv("SUMMARY_DAILY_BUDGET_USD", "5.00"))


class SummaryOutput(BaseModel):
    summary: str
    takeaways: List[str]

    @validator('summary')
    def summary_length(cls, v):
        words = len(v.split())
        if words < 20:
            raise ValueError('Summary too short (< 20 words)')
        if words > 120:
            raise ValueError('Summary too long (> 120 words)')
        return v

    @validator('takeaways')
    def takeaways_count(cls, v):
        if len(v) < 3:
            raise ValueError('Need at least 3 takeaways')
        if len(v) > 5:
            raise ValueError('No more than 5 takeaways')
        if any(len(t.split()) < 5 for t in v):
            raise ValueError('Takeaway too short')
        return v


def parse_and_validate(raw: str) -> SummaryOutput:
    """Parse raw LLM response into a validated SummaryOutput object."""
    clean = raw.strip().lstrip('```json').rstrip('```').strip()
    data = json.loads(clean)
    return SummaryOutput(**data)


def today_date() -> str:
    """Returns YYYY-MM-DD in UTC for budget tracking."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_budget_before_call(job_type: str) -> bool:
    """Check if we have exceeded the daily summary budget (default $5.00)."""
    today_spend = redis.get('summary_spend:' + today_date())
    if today_spend is not None and float(today_spend) >= SUMMARY_DAILY_BUDGET_USD:
        logger.warning(f"Daily summary budget exhausted (${today_spend}) - pausing non-urgent execution")
        return False
    return True


def log_usage_and_update_spend(
    session,
    job_type: JobType,
    prompt_version: int,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    success: bool,
    error_message: Optional[str] = None,
    item_id: Optional[str] = None,
    cluster_id: Optional[str] = None,
    model: str = "gpt-4o-mini"
):
    """Logs usage to the DB and increments daily spend in Redis."""
    # gpt-4o-mini pricing: $0.15 / 1M input, $0.60 / 1M output options
    cost = (input_tokens * 0.00015 + output_tokens * 0.0006) / 1000

    key = 'summary_spend:' + today_date()
    redis.incrbyfloat(key, cost)
    # Give the budget key a 2-day TTL so old limits expire naturally
    redis.expire(key, 86400 * 2)

    log_entry = SummaryUsageLog(
        item_id=item_id,
        cluster_id=cluster_id,
        job_type=job_type,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost_usd=cost,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message
    )
    session.add(log_entry)

    return cost


def get_active_prompt_version(job_type: JobType, session) -> Optional[PromptVersion]:
    """Fetch the currently active prompt version for a given job type."""
    return session.execute(
        select(PromptVersion)
        .where(PromptVersion.job_type == job_type)
        .where(PromptVersion.is_active .is_(True))
        .order_by(PromptVersion.version.desc())
    ).scalar_one_or_none()
