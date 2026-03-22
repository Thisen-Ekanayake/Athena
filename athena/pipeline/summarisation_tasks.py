import os
import time
from datetime import datetime, timezone
from typing import Optional

from celery import shared_task
from loguru import logger
from sqlalchemy import select

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, SummaryStatus, JobType
from athena.pipeline.summarisation import (
    check_budget_before_call,
    log_usage_and_update_spend,
    get_active_prompt_version,
    parse_and_validate,
)


def _get_openai_client():
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def build_item_summary_prompt(item: ContentItem, text_content: str, prompt_tpl: str) -> str:
    cat = item.category.value if hasattr(item.category, 'value') else str(item.category)
    source_name = item.source.name if item.source else "Unknown"
    authors = ", ".join(item.authors) if item.authors else "Unknown"
    pub_date = item.published_at.strftime("%Y-%m-%d") if item.published_at else "Unknown"

    return prompt_tpl.format(
        title=item.title,
        authors=authors,
        category=cat,
        source_name=source_name,
        published_at=pub_date,
        preprocessed_text=text_content
    )


def _does_item_need_resummary(item: ContentItem, active_version: int) -> bool:
    if not item.summary or item.summary_status != SummaryStatus.COMPLETE:
        return True
    # Compare with current active version
    if item.summary_version != active_version:
        return True
    return False


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def summarise_item_worker(self, item_id: str, tier: int = 2):
    """
    Tiered summarisation worker. Can be driven by any tier queue.
    Fetches the item, checks budget, loads text, generates summary.
    tier=1: urgent (exempt from 80% budget cap)
    tier=2: standard (pauses at 80% budget)
    tier=3: lazy (on-demand only, pauses at 80% budget)
    """
    if not check_budget_before_call(JobType.ITEM_SUMMARY.value, tier=tier):
        logger.warning(f"Budget exceeded for tier {tier}. Skipping summarisation for {item_id}.")
        # Let it fail so it might be retried or just ignored. If we raise self.retry,
        # it pushes to a queue. For now, we abort. Tier 1 skips this budget check logic if needed,
        # but let's implement standard budget abort here.
        return

    with SessionLocal() as session:
        item = session.execute(
            select(ContentItem).where(ContentItem.id == item_id)
        ).scalar_one_or_none()

        if not item:
            logger.error(f"Item {item_id} not found.")
            return

        active_prompt = get_active_prompt_version(JobType.ITEM_SUMMARY, session)
        if not active_prompt:
            logger.error("No active prompt version for ITEM_SUMMARY.")
            return

        if not _does_item_need_resummary(item, active_prompt.version):
            logger.info(f"Item {item_id} already summarised with active version.")
            return

        # Load staged file
        if not item.full_text_path or not os.path.exists(item.full_text_path):
            logger.error(f"Text file missing for {item_id}: {item.full_text_path}")
            # Could trigger re-stage, but for now mark failed
            item.summary_status = SummaryStatus.FAILED
            session.commit()
            return

        with open(item.full_text_path, 'r', encoding='utf-8') as f:
            text_content = f.read()

        user_msg = build_item_summary_prompt(item, text_content, active_prompt.user_prompt_tpl)

        try:
            client = _get_openai_client()
            start_time = time.time()
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": active_prompt.system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.3
            )
            raw_response = res.choices[0].message.content
            latency = int((time.time() - start_time) * 1000)

            # Validate
            try:
                parsed = parse_and_validate(raw_response)
                success = True
                err_msg = None
            except Exception as pe:
                success = False
                err_msg = str(pe)

            log_usage_and_update_spend(
                session=session,
                job_type=JobType.ITEM_SUMMARY,
                prompt_version=active_prompt.version,
                input_tokens=res.usage.prompt_tokens,
                output_tokens=res.usage.completion_tokens,
                latency_ms=latency,
                success=success,
                error_message=err_msg,
                item_id=item.id,
                model="gpt-4o-mini"
            )

            if success:
                item.summary = parsed.summary
                item.takeaways = parsed.takeaways
                item.summary_version = active_prompt.version
                item.summary_status = SummaryStatus.COMPLETE
                item.summarised_at = datetime.now(timezone.utc)
                session.commit()
                logger.info(f"Summarised item {item_id} successfully.")
            else:
                item.summary_status = SummaryStatus.FAILED
                session.commit()
                logger.error(f"Validation failed for item {item_id}: {err_msg}")
                # Retry if JSON validation failed
                raise self.retry(exc=Exception(f"Validation Error: {err_msg}"))

        except Exception as e:
            session.rollback()
            logger.error(f"OpenAI or inner error for {item_id}: {e}")
            with SessionLocal() as err_session:
                err_item = err_session.execute(
                    select(ContentItem).where(
                        ContentItem.id == item_id)).scalar_one_or_none()
                if err_item:
                    err_item.summary_status = SummaryStatus.FAILED
                    err_session.commit()
            raise self.retry(exc=e)


def summarise_on_demand_sync(item_id: str) -> Optional[ContentItem]:
    """Synchronous on-demand summary for Tier 3 items, triggered by API."""
    import time
    time.time()
    logger.info(f"Triggering on-demand summarisation for {item_id}")
    task = summarise_item_worker.apply_async(args=[item_id], queue='summary_lazy')

    # Wait for completion up to 8 seconds
    try:
        task.get(timeout=8.0)
    except Exception as e:
        logger.error(f"On-demand summary timed out or failed for {item_id}: {e}")

    with SessionLocal() as session:
        return session.execute(select(ContentItem).where(ContentItem.id == item_id)).scalar_one_or_none()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def label_cluster_worker(self, cluster_id: str):
    """
    Generate label and description for a cluster based on top 5 items.
    """
    from athena.core.models import Cluster
    import json

    if not check_budget_before_call(JobType.CLUSTER_LABEL.value):
        logger.warning(f"Budget exceeded. Skipping cluster label for {cluster_id}.")
        return

    with SessionLocal() as session:
        cluster = session.execute(select(Cluster).where(Cluster.id == cluster_id)).scalar_one_or_none()
        if not cluster:
            logger.error(f"Cluster {cluster_id} not found.")
            return

        active_prompt = get_active_prompt_version(JobType.CLUSTER_LABEL, session)
        if not active_prompt:
            logger.error("No active prompt version for CLUSTER_LABEL.")
            return

        top_items = session.execute(
            select(ContentItem)
            .where(ContentItem.cluster_id == cluster_id)
            .order_by(ContentItem.score.desc())
            .limit(5)
        ).scalars().all()

        if len(top_items) < 3:
            logger.warning(f"Cluster {cluster_id} has < 3 items, skipping label generation.")
            return

        items_str_list = []
        for i, item in enumerate(top_items, 1):
            items_str_list.append(f"Item {i}:\n  Title: {item.title}\n  Abstract: {item.abstract or 'N/A'}")

        user_msg = active_prompt.user_prompt_tpl.format(
            item_count=len(top_items),
            items_str="\n\n".join(items_str_list)
        )

        try:
            client = _get_openai_client()
            start_time = time.time()
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": active_prompt.system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.3
            )
            raw_response = res.choices[0].message.content
            latency = int((time.time() - start_time) * 1000)

            try:
                clean = raw_response.strip().lstrip('```json').rstrip('```').strip()
                data = json.loads(clean)
                label = data.get("label", "")
                desc = data.get("description", "")
                if len(label.split()) > 10:
                    raise ValueError("Label too long")
                success = True
                err_msg = None
            except Exception as pe:
                success = False
                err_msg = str(pe)

            log_usage_and_update_spend(
                session=session,
                job_type=JobType.CLUSTER_LABEL,
                prompt_version=active_prompt.version,
                input_tokens=res.usage.prompt_tokens,
                output_tokens=res.usage.completion_tokens,
                latency_ms=latency,
                success=success,
                error_message=err_msg,
                cluster_id=cluster.id,
                model="gpt-4o-mini"
            )

            if success:
                cluster.label = label
                cluster.summary = desc
                session.commit()
                logger.info(f"Labelled cluster {cluster_id} successfully.")
            else:
                session.commit()
                logger.error(f"Validation failed for cluster {cluster_id}: {err_msg}")
                raise self.retry(exc=Exception(f"Cluster Label Error: {err_msg}"))

        except Exception as e:
            logger.error(f"OpenAI error for cluster {cluster_id}: {e}")
            raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_trending_brief_worker(self, category: str):
    """
    Generate daily trending brief for a specific category based on top trending items.
    """
    from athena.core.models import ContentCategory, TrendingBrief
    import json

    if not check_budget_before_call(JobType.TRENDING_BRIEF.value):
        logger.warning(f"Budget exceeded. Skipping trending brief for {category}.")
        return

    with SessionLocal() as session:
        active_prompt = get_active_prompt_version(JobType.TRENDING_BRIEF, session)
        if not active_prompt:
            logger.error("No active prompt version for TRENDING_BRIEF.")
            return

        cat_enum = ContentCategory(category)

        # Get top 5 trending items
        top_items = session.execute(
            select(ContentItem)
            .where(ContentItem.category == cat_enum)
            .where(ContentItem.is_trending .is_(True))
            .order_by(ContentItem.score.desc())
            .limit(5)
        ).scalars().all()

        if len(top_items) < 3:
            logger.warning(f"Not enough trending items in {category} for a brief.")
            return

        items_str_list = []
        for i, item in enumerate(top_items, 1):
            items_str_list.append(f"Title: {item.title}\nSummary: {item.summary or item.abstract or 'N/A'}")

        user_msg = active_prompt.user_prompt_tpl.format(
            category=category,
            items_str="\n\n".join(items_str_list)
        )

        try:
            client = _get_openai_client()
            start_time = time.time()
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": active_prompt.system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.3
            )
            raw_response = res.choices[0].message.content
            latency = int((time.time() - start_time) * 1000)

            try:
                clean = raw_response.strip().lstrip('```json').rstrip('```').strip()
                data = json.loads(clean)
                brief = data.get("brief", "")
                theme = data.get("theme", "")
                success = True
                err_msg = None
            except Exception as pe:
                success = False
                err_msg = str(pe)

            log_usage_and_update_spend(
                session=session,
                job_type=JobType.TRENDING_BRIEF,
                prompt_version=active_prompt.version,
                input_tokens=res.usage.prompt_tokens,
                output_tokens=res.usage.completion_tokens,
                latency_ms=latency,
                success=success,
                error_message=err_msg,
                model="gpt-4o-mini"
            )

            if success:
                trend_brief = TrendingBrief(
                    category=cat_enum,
                    brief=brief,
                    theme=theme,
                    prompt_version=active_prompt.version,
                    source_item_ids=[item.id for item in top_items]
                )
                session.add(trend_brief)
                session.commit()
                logger.info(f"Generated trending brief for {category} successfully.")
            else:
                session.commit()
                logger.error(f"Validation failed for trending brief {category}: {err_msg}")
                raise self.retry(exc=Exception(f"Trending Brief Error: {err_msg}"))

        except Exception as e:
            logger.error(f"OpenAI error for trending brief in {category}: {e}")
            raise self.retry(exc=e)
