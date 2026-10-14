"""
Citation momentum (ROADMAP P3): how fast feed papers gather citations.

Once a day:

1. Feed papers up to MOMENTUM_DAYS old get their citation counts from Semantic Scholar (one batch request covers
   200 papers and works without a key). Before this, a paper's count was looked up once, minutes after it was
   published, and never again.
2. A paper that already has citations, and whose past was never rebuilt, gets it rebuilt once from the
   publication dates of the papers citing it: a cumulative count per day, scaled so it ends at the true count
   (citing papers without a date are assumed to follow the same curve, so they don't make a jump). Only days
   before the paper's first daily snapshot are filled, one ``rebuilt`` row per day the count changed.
3. Every feed paper in the window, and every community post with engagement data, gets one ``daily`` snapshot.
   Company blog posts have no number that changes, so they get none.
4. Each paper's gains over 7 and 30 days go on the item (``citation_gain_7d``/``_30d``) for the feed, the
   "Rising fast" list and the score.

The task runs from an hourly beat entry but only does the work once per UTC day (marker MOMENTUM_DAY in
app_settings). The old 24-hour interval entry restarted its clock whenever beat restarted, so on a machine that
restarts often it never fired: metric_snapshots was empty.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from loguru import logger
from sqlalchemy import delete, select, update

from athena.core.config_store import get_setting, set_setting
from athena.pipeline.celery_app import celery_app

DAY_MARKER = "MOMENTUM_DAY"
COUNT_FIELDS = "paperId,externalIds,citationCount"
REFRESH_MAX_AGE = 20 * 3600     # seconds: a paper's count is asked for again after this long
REBUILDS_PER_RUN = 30           # one request each; the keyless pool allows about one every 3 s
SERIES_DAYS = 90                # how much of a paper's history the item route returns


def window_days() -> int:
    try:
        return max(1, int(get_setting("MOMENTUM_DAYS", "365") or 365))
    except ValueError:
        return 365


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _midday(day: date) -> datetime:
    return datetime.combine(day, time(12), tzinfo=timezone.utc)


def _feed_items(session, now: datetime, categories) -> list:
    from athena.core.models import ContentItem
    return list(session.execute(select(ContentItem).where(
        ContentItem.category.in_(categories),
        ContentItem.published_at >= now - timedelta(days=window_days()))).scalars())


def _papers(session, now: datetime) -> list:
    from athena.core.models import ContentCategory
    return _feed_items(session, now, [ContentCategory.PAPER])


# ── 1. counts ────────────────────────────────────────────────────────


def refresh_feed_citations(session, s2, now: datetime) -> int:
    """Citation counts for the window's arXiv papers from Semantic Scholar. Returns how many were found."""
    from athena.evolution.feedlink import arxiv_id_from_url
    by_id = {}
    for item in _papers(session, now):
        if arxiv := arxiv_id_from_url(item.url):
            by_id[f"ARXIV:{arxiv}"] = item
    if not by_id:
        return 0
    found = s2.get_papers(list(by_id), fields=COUNT_FIELDS, max_age=REFRESH_MAX_AGE)
    updated = 0
    for key, item in by_id.items():
        paper = found.get(key)
        if paper is None:
            continue
        extra = dict(item.extra_data or {})
        ss = dict(extra.get("semantic_scholar") or {})
        ss.update(paper_id=paper.paper_id, citations=paper.citation_count, fetched_at=now.isoformat())
        item.extra_data = {**extra, "semantic_scholar": ss}
        item.citation_count = paper.citation_count
        updated += 1
    session.commit()
    return updated


# ── 2. rebuilt history ───────────────────────────────────────────────


def rebuilt_points(dates: list[str | None], published: date, cutoff: date, target: int) -> list[tuple[date, int]]:
    """(day, citations) for each day the count changed before ``cutoff``, starting from 0 on ``published``.

    The citing papers with a date are counted per day and scaled so the last point is ``target``, the true count
    at ``cutoff``: the ones without a date are assumed to have arrived like the rest.
    """
    days = []
    for raw in dates:
        try:
            day = date.fromisoformat(raw) if raw else None
        except ValueError:
            day = None
        if day is not None and day < cutoff:
            days.append(max(day, published))
    if not days or target <= 0:
        return []
    per_day = Counter(days)
    points, running, last = [], 0, None
    if min(per_day) > published:
        points.append((published, 0))
        last = 0
    for day in sorted(per_day):
        running += per_day[day]
        value = round(running * target / len(days))
        if value != last:
            points.append((day, value))
            last = value
    return points


def rebuild_history(session, item, s2, now: datetime) -> int:
    """Rebuild a paper's citation history once from its citing papers' dates. Returns the rows written."""
    from athena.core.models import MetricSnapshot
    from athena.pipeline.scoring import engagement_raw
    from athena.pipeline.signals import _extract_engagement_signals
    extra = dict(item.extra_data or {})
    ss = dict(extra.get("semantic_scholar") or {})
    if not ss.get("paper_id"):
        return 0
    first = session.execute(
        select(MetricSnapshot.snapshot_date, MetricSnapshot.citation_count)
        .where(MetricSnapshot.item_id == item.id, MetricSnapshot.source == "daily")
        .order_by(MetricSnapshot.snapshot_date).limit(1)).first()
    cutoff, target = (_aware(first[0]).date(), first[1] or 0) if first else (now.date(), item.citation_count or 0)
    points = rebuilt_points(s2.citation_dates(ss["paper_id"]), _aware(item.published_at).date(), cutoff, target)
    # The engagement a rebuilt row carries is today's, so rebuilt rows never look like an engagement gain.
    eng = engagement_raw(_extract_engagement_signals(extra, item.source.url if item.source else ""))
    session.execute(delete(MetricSnapshot).where(MetricSnapshot.item_id == item.id,
                                                 MetricSnapshot.source == "rebuilt"))
    for day, value in points:
        session.add(MetricSnapshot(item_id=item.id, citation_count=value, engagement_raw=eng,
                                   snapshot_date=_midday(day), source="rebuilt"))
    item.extra_data = {**extra, "semantic_scholar": {**ss, "history_rebuilt": now.isoformat()}}
    session.commit()
    return len(points)


def rebuild_due(session, s2, now: datetime, limit: int | None = REBUILDS_PER_RUN) -> int:
    """Rebuild the history of papers that have citations and were never rebuilt, at most ``limit`` of them."""
    due = [i for i in _papers(session, now)
           if (i.citation_count or 0) > 0
           and (ss := (i.extra_data or {}).get("semantic_scholar") or {}).get("paper_id")
           and not ss.get("history_rebuilt")]
    due.sort(key=lambda i: -(i.citation_count or 0))
    done = 0
    for item in due[:limit] if limit else due:
        try:
            rebuild_history(session, item, s2, now)
            done += 1
        except Exception as exc:  # one paper's failure (the keyless pool, a bad response) shouldn't stop the rest
            session.rollback()
            logger.warning(f"Momentum: history rebuild failed for {item.id}: {exc}")
    return done


# ── 3. snapshots and gains ───────────────────────────────────────────


def take_snapshots(session, now: datetime) -> int:
    """One daily snapshot per paper in the window, and per community post with engagement data, unless today's
    exists. Returns how many were taken."""
    from athena.core.models import ContentCategory, MetricSnapshot, Source
    from athena.pipeline.scoring import engagement_raw
    from athena.pipeline.signals import _extract_engagement_signals
    day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    taken_today = set(session.execute(select(MetricSnapshot.item_id).where(
        MetricSnapshot.source == "daily", MetricSnapshot.snapshot_date >= day_start)).scalars())
    source_urls = dict(session.execute(select(Source.id, Source.url)).all())
    taken = 0
    for item in _feed_items(session, now, [ContentCategory.PAPER, ContentCategory.COMMUNITY_BLOG]):
        if item.id in taken_today:
            continue
        signals = _extract_engagement_signals(item.extra_data or {}, source_urls.get(item.source_id) or "")
        if item.category != ContentCategory.PAPER and not signals:
            continue
        session.add(MetricSnapshot(item_id=item.id, citation_count=item.citation_count or 0,
                                   engagement_raw=engagement_raw(signals), snapshot_date=now, source="daily"))
        taken += 1
    session.commit()
    return taken


def count_at(history: list[tuple[datetime, int]], when: datetime) -> int | None:
    """The count of the latest snapshot at or before ``when`` (``history`` sorted by date), or None."""
    i = bisect.bisect_right([d for d, _ in history], when)
    return history[i - 1][1] if i else None


def gain(history: list[tuple[datetime, int]], current: int, published: datetime | None, since: datetime) -> int | None:
    """Citations gained since ``since``. A paper published after it gained everything it has; one with no snapshot
    from then is unknown."""
    before = count_at(history, since)
    if before is None:
        if published is not None and published >= since:
            before = 0
        else:
            return None
    return max(0, current - before)


def histories(session, item_ids: list) -> dict:
    """Each item's snapshots as [(date, citations)], oldest first."""
    from athena.core.models import MetricSnapshot
    out = defaultdict(list)
    for item_id, when, count in session.execute(
            select(MetricSnapshot.item_id, MetricSnapshot.snapshot_date, MetricSnapshot.citation_count)
            .where(MetricSnapshot.item_id.in_(item_ids)).order_by(MetricSnapshot.snapshot_date)):
        out[item_id].append((_aware(when), count or 0))
    return out


def update_gains(session, now: datetime) -> int:
    """Set each window paper's 7- and 30-day gains, and clear them on papers that left the window."""
    from athena.core.models import ContentCategory, ContentItem
    papers = _papers(session, now)
    history = histories(session, [p.id for p in papers])
    for paper in papers:
        published = _aware(paper.published_at)
        current = paper.citation_count or 0
        paper.citation_gain_7d = gain(history[paper.id], current, published, now - timedelta(days=7))
        paper.citation_gain_30d = gain(history[paper.id], current, published, now - timedelta(days=30))
    session.execute(update(ContentItem).where(
        ContentItem.category == ContentCategory.PAPER,
        ContentItem.published_at < now - timedelta(days=window_days()),
        ContentItem.citation_gain_7d.isnot(None)).values(citation_gain_7d=None, citation_gain_30d=None)
        .execution_options(synchronize_session="fetch"))
    session.commit()
    return len(papers)


def series(session, item, now: datetime, days: int = SERIES_DAYS) -> list[dict]:
    """A paper's citations per day for the last ``days`` days: [{date, citations, rebuilt}], carried forward."""
    from athena.core.models import MetricSnapshot
    rows = [(_aware(d).date(), c or 0, s) for d, c, s in session.execute(
        select(MetricSnapshot.snapshot_date, MetricSnapshot.citation_count, MetricSnapshot.source)
        .where(MetricSnapshot.item_id == item.id).order_by(MetricSnapshot.snapshot_date))]
    if not rows:
        return []
    start = max(rows[0][0], now.date() - timedelta(days=days - 1))
    by_day = {}
    for day, count, source in rows:  # the last row of a day wins; a daily row beats a rebuilt one
        if day not in by_day or source == "daily" or by_day[day][1] != "daily":
            by_day[day] = (count, source)
    out, value, rebuilt, day = [], 0, True, rows[0][0]
    while day <= now.date():
        if day in by_day:
            value, source = by_day[day]
            rebuilt = source == "rebuilt"
        if day >= start:
            out.append({"date": day.isoformat(), "citations": value, "rebuilt": rebuilt})
        day += timedelta(days=1)
    return out


# ── the daily run ────────────────────────────────────────────────────


def run(session, s2, now: datetime, rebuilds: int | None = REBUILDS_PER_RUN) -> dict:
    """Refresh the counts, rebuild what is due, snapshot, then update the gains."""
    summary = {"refreshed": 0, "rebuilt": 0}
    try:
        summary["refreshed"] = refresh_feed_citations(session, s2, now)
        summary["rebuilt"] = rebuild_due(session, s2, now, rebuilds)
    except Exception as exc:  # Semantic Scholar being down still leaves today's snapshot of what is known
        session.rollback()
        logger.warning(f"Momentum: Semantic Scholar refresh failed: {exc}")
    summary["snapshots"] = take_snapshots(session, now)
    summary["papers"] = update_gains(session, now)
    return summary


@celery_app.task
def daily_momentum(force: bool = False) -> dict:
    """The day's citation refresh, snapshots and gains, once per UTC day (it is scheduled hourly)."""
    from athena.database.db import SessionLocal
    from athena.evolution.semantic_scholar import SemanticScholarClient
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    if not force and get_setting(DAY_MARKER) == today:
        return {"skipped": today}
    with SessionLocal() as session:
        summary = run(session, SemanticScholarClient(), now)
    set_setting(DAY_MARKER, today)
    logger.info(f"Momentum: {summary}")
    return summary
