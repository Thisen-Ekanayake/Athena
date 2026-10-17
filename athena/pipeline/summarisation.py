"""
Item summaries and cluster labels: the shared parts.

Contains utilities for Redis-based budget tracking, Pydantic validation of model
responses, and core logic for formatting prompts and generating summaries.
"""
import os
import json
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, field_validator
from loguru import logger
from sqlalchemy import select

from athena.core import llm, usage
from athena.core.models import PromptVersion, JobType
from athena.core.redis_client import get_redis

redis = get_redis()
SUMMARY_DAILY_BUDGET_USD = float(os.getenv("SUMMARY_DAILY_BUDGET_USD", "5.00"))
USAGE_FEATURES = {"item_summary": "summary", "cluster_label": "cluster_label"}


class SummaryOutput(BaseModel):
    summary: str
    takeaways: List[str]

    @field_validator('summary')
    @classmethod
    def summary_length(cls, v):
        words = len(v.split())
        if words < 20:
            raise ValueError('Summary too short (< 20 words)')
        if words > 120:
            raise ValueError('Summary too long (> 120 words)')
        return v

    @field_validator('takeaways')
    @classmethod
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


def check_budget_before_call(job_type: str, tier: int = 2) -> bool:
    """
    Check if we have exceeded the daily summary budget.
    Tier 1 (urgent: a score of 0.75 or more) is exempt from the 80% threshold.
    Tier 2/3 pauses at 80% of daily budget to reserve capacity for urgent items.
    """
    if usage.app_over_budget():
        logger.warning("This month's model budget is used up; summaries paused until next month")
        return False
    today_spend = redis.get('summary_spend:' + today_date())
    if today_spend is None:
        return True

    current_spend = float(today_spend)
    budget = SUMMARY_DAILY_BUDGET_USD

    # Tier 1 (urgent) can use the full budget
    if tier == 1:
        if current_spend >= budget:
            logger.warning(
                f"Daily budget fully exhausted (${current_spend:.2f})"
                f" — even Tier 1 paused"
            )
            return False
        return True

    # Tier 2/3 pause at 80% to reserve capacity for Tier 1
    threshold = budget * 0.80
    if current_spend >= threshold:
        logger.warning(
            f"Tier {tier} paused at 80% budget "
            f"(${current_spend:.2f} / ${budget:.2f})"
        )
        return False
    return True


def log_usage_and_update_spend(job_type: JobType, input_tokens: int, output_tokens: int, model: str = "") -> float:
    """Counts the call in usage_events and adds its cost to today's summary spend in Redis (zero for local models)."""
    cost = llm.cost(input_tokens, output_tokens)
    if input_tokens or output_tokens:
        kind = job_type.value if hasattr(job_type, "value") else str(job_type)
        usage.add(USAGE_FEATURES.get(kind, "summary"), model, input_tokens, output_tokens)

    key = 'summary_spend:' + today_date()
    redis.incrbyfloat(key, cost)
    # Give the budget key a 2-day TTL so old limits expire naturally
    redis.expire(key, 86400 * 2)
    return cost


def get_active_prompt_version(job_type: JobType, session) -> Optional[PromptVersion]:
    """Fetch the currently active prompt version for a given job type."""
    return session.execute(
        select(PromptVersion)
        .where(PromptVersion.job_type == job_type)
        .where(PromptVersion.is_active .is_(True))
        .order_by(PromptVersion.version.desc())
    ).scalar_one_or_none()
