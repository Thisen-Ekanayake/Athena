import tiktoken
from athena.core.models import ContentCategory
from athena.core.qa_fetcher import select_relevant_sections
from athena.core.qa_prompt import build_messages, prune_history_if_needed
import json
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from athena.core import llm, usage
from athena.model_server import activity
from athena.core.models import ContentItem, QAFetchCache, User
from athena.core.qa_fetcher import fetch_article_content
from athena.api.auth import spend
from athena.api.deps import get_db


router = APIRouter()


@router.get("/items/{item_id}/qa/status", response_model=Dict[str, Any])
async def get_qa_status(item_id: UUID, db: Session = Depends(get_db)):
    item = db.execute(select(ContentItem).where(ContentItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    cache = db.execute(select(QAFetchCache).where(QAFetchCache.item_id == item_id)).scalar_one_or_none()

    if cache:
        status = 'partial' if cache.is_partial else 'fetchable'
        if cache.fetch_method == 'abstract_only':
            status = 'unavailable'

        return {
            "status": status,
            "fetch_method": cache.fetch_method,
            "word_count": cache.word_count,
            "last_fetched_at": cache.last_fetched_at
        }

    return {
        "status": "unknown",
        "fetch_method": None,
        "word_count": 0
    }


@router.get("/items/{item_id}/qa/prefetch")
async def prefetch_qa_article(item_id: UUID, db: Session = Depends(get_db)):
    item = db.execute(select(ContentItem).where(ContentItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    cache = db.execute(select(QAFetchCache).where(QAFetchCache.item_id == item_id)).scalar_one_or_none()

    # If already cached recently (e.g. within 1 hour), skip
    if cache and (datetime.utcnow() - cache.last_fetched_at.replace(tzinfo=None)).total_seconds() < 3600:
        return {"status": "already_cached", "method": cache.fetch_method}

    start_time = datetime.utcnow()
    # Trigger fetch
    result = await fetch_article_content(item)
    fetch_latency = int((datetime.utcnow() - start_time).total_seconds() * 1000)

    # Cache the result metadata explicitly (we don't cache the whole text in DB, maybe Redis instead)
    if not cache:
        cache = QAFetchCache(item_id=item_id)
        db.add(cache)

    cache.fetch_method = result.method
    cache.word_count = result.word_count
    cache.is_partial = getattr(result, 'partial', False)
    cache.last_fetched_at = datetime.utcnow()
    cache.fetch_latency_ms = fetch_latency

    db.commit()

    return {
        "status": "cached",
        "method": result.method,
        "word_count": result.word_count,
        "latency_ms": fetch_latency
    }


class QARequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []


def est_tokens(text: str) -> int:
    try:
        enc = tiktoken.get_encoding("o200k_base")  # an estimate; the served model counts its own
        return len(enc.encode(text))
    except Exception:
        return int(len(text.split()) * 1.3)


@router.post("/items/{item_id}/qa")
async def ask_question(item_id: UUID, req: QARequest, db: Session = Depends(get_db),
                       user: User = Depends(spend("qa"))):
    from athena.api.deps import get_redis
    r = get_redis()

    item = db.execute(select(ContentItem).where(ContentItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    session_id = f"session_{user.id}_{item_id}"

    # 1. Budget Checks
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    daily_spend = float(r.get(f"qa_spend:{today_str}") or 0.0)
    if daily_spend > 10.0:
        raise HTTPException(status_code=429, detail="Daily budget exhausted for Q&A.")

    active_streams = r.incr("qa_active_streams")
    try:
        if active_streams > 10:
            raise HTTPException(status_code=429, detail="Server busy, too many concurrent Q&A streams.")

        # Session token tracking
        session_tokens = int(r.get(f"qa_session_tokens:{session_id}") or 0)
        if session_tokens > 40000:
            raise HTTPException(status_code=429, detail="Session limit reached for this article.")

        # 2. Fetch Article
        result = await fetch_article_content(item)

        # 2b. Apply content length limits per category
        is_paper = (
            item.category == ContentCategory.PAPER
            or item.category == 'paper'
        )
        max_tokens = 16000 if is_paper else 8000
        article_text = select_relevant_sections(
            result.text, req.question, max_tokens
        )

        # 2c. Fetch custom prompt from database
        from athena.core.models import PromptVersion, JobType
        active_prompt = db.execute(
            select(PromptVersion)
            .where(PromptVersion.job_type == JobType.QA)
            .where(PromptVersion.is_active.is_(True))
            .order_by(PromptVersion.version.desc())
        ).scalars().first()
        sys_prompt = active_prompt.system_prompt if active_prompt else None

        # 3. Build Messages
        messages_raw = build_messages(article_text, req.question, req.history, sys_prompt)
        messages = prune_history_if_needed(messages_raw, 8000)

        # Compute approx input tokens
        input_tokens = sum(est_tokens(m["content"]) for m in messages)

        # 4. Stream response
        model = llm.chat_model("qa")

        async def generate():
            client = llm.async_chat_client()
            call = activity.start("qa", model, user_id=user.id)
            try:
                # Send partial content flag as initial event
                if result.partial:
                    yield f"data: {json.dumps({'partial': True, 'method': result.method})}\n\n"

                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=800,
                    stream=True,
                    stream_options={"include_usage": True},  # the last chunk carries the served model's counts
                    extra_body=llm.chat_extra(),
                )

                parts, counted = [], None
                async for chunk in stream:
                    if getattr(chunk, "usage", None):
                        counted = chunk.usage
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        parts.append(delta)
                        yield f"data: {json.dumps({'token': delta})}\n\n"
                call.tokens(*usage.tokens_of(counted))
                activity.finish(call)
                yield "data: [DONE]\n\n"

                # Update tokens and cost: the server's counts, else the estimates
                prompt_tokens, answer_tokens = usage.tokens_of(counted)
                prompt_tokens = prompt_tokens or input_tokens
                answer_tokens = answer_tokens or est_tokens("".join(parts))
                total_tokens = prompt_tokens + answer_tokens
                cost = llm.cost(prompt_tokens, answer_tokens)
                usage.add("qa", model, prompt_tokens, answer_tokens, user_id=user.id)

                r.incrby(f"qa_session_tokens:{session_id}", total_tokens)
                r.expire(f"qa_session_tokens:{session_id}", 86400)
                r.incrbyfloat(f"qa_spend:{today_str}", cost)

            except Exception as e:
                activity.finish(call, e)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                activity.finish(call, GeneratorExit())  # stopped mid-answer; a no-op otherwise
                r.decr("qa_active_streams")

        return StreamingResponse(generate(), media_type="text/event-stream")

    except Exception as e:
        r.decr("qa_active_streams")
        raise e
