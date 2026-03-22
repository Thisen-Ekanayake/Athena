import asyncio
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Dict, Any

from athena.core.models import ContentItem, QAFetchCache
from athena.core.qa_fetcher import fetch_article_content, FetchResult
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


from typing import List, Dict
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import json
import openai
from athena.core.qa_prompt import build_messages, prune_history_if_needed
from athena.core.models import QAUsageLog
import tiktoken

class QARequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []

def est_tokens(text: str) -> int:
    try:
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
        return len(enc.encode(text))
    except Exception:
        return int(len(text.split()) * 1.3)

@router.post("/items/{item_id}/qa")
async def ask_question(item_id: UUID, req: QARequest, db: Session = Depends(get_db)):
    from athena.api.deps import get_redis
    r = get_redis()
    
    item = db.execute(select(ContentItem).where(ContentItem.id == item_id)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    session_id = f"sess_{item_id}_{hash(req.question)}" # We need a proper session_id, frontend doesn't send it, let's just make one or use hash
    # Wait, frontend is supposed to generate it? The spec says:
    # "Body: { question: string, history: [{role, content}] }"
    # So we can just use item_id and IP or simply track overall QA spend. Let's use a dummy session_id for logging.
    session_id = f"session_{item_id}"
    
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
        start_fetch = datetime.utcnow()
        result = await fetch_article_content(item)
        fetch_latency = int((datetime.utcnow() - start_fetch).total_seconds() * 1000)
        
        # 3. Build Messages
        messages_raw = build_messages(result.text, req.question, req.history)
        messages = prune_history_if_needed(messages_raw, 8000)
        
        # Compute approx input tokens
        input_tokens = sum(est_tokens(m["content"]) for m in messages)
        
        # 4. Stream response
        async def generate():
            client = openai.AsyncOpenAI()
            try:
                stream = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=800,
                    stream=True,
                )
                
                answer_tokens = 0
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        answer_tokens += 1
                        yield f"data: {json.dumps({'token': delta})}\n\n"
                yield "data: [DONE]\n\n"
                
                # Update tokens and cost
                total_tokens = input_tokens + answer_tokens
                cost = (input_tokens * 0.150 / 1_000_000) + (answer_tokens * 0.600 / 1_000_000)
                
                r.incrby(f"qa_session_tokens:{session_id}", total_tokens)
                r.expire(f"qa_session_tokens:{session_id}", 86400)
                r.incrbyfloat(f"qa_spend:{today_str}", cost)
                
                # Log usage
                db_sess = next(get_db())
                log = QAUsageLog(
                    item_id=item_id,
                    session_id=session_id,
                    turn_number=len(req.history) // 2 + 1,
                    question_length=len(req.question),
                    fetch_method=result.method,
                    fetch_latency_ms=fetch_latency,
                    article_tokens=input_tokens,
                    history_tokens=0,
                    answer_tokens=answer_tokens,
                    total_cost_usd=cost,
                    model="gpt-4o-mini",
                    partial_content=result.partial,
                    success=True
                )
                db_sess.add(log)
                db_sess.commit()
                db_sess.close()
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                r.decr("qa_active_streams")
                
        return StreamingResponse(generate(), media_type="text/event-stream")
        
    except Exception as e:
        r.decr("qa_active_streams")
        raise e

from sqlalchemy import func

@router.get("/admin/qa/sessions")
def get_admin_qa_sessions(db: Session = Depends(get_db)):
    from athena.api.deps import get_redis
    r = get_redis()
    
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    daily_spend = float(r.get(f"qa_spend:{today_str}") or 0.0)
    
    # Recent sessions
    recent = db.execute(
        select(QAUsageLog)
        .order_by(QAUsageLog.created_at.desc())
        .limit(50)
    ).scalars().all()
    
    # Stats
    method_dist = db.execute(
        select(QAUsageLog.fetch_method, func.count(QAUsageLog.id))
        .group_by(QAUsageLog.fetch_method)
    ).all()
    
    # Partial content rate
    total_queries = db.execute(select(func.count(QAUsageLog.id))).scalar() or 1
    partial_queries = db.execute(select(func.count(QAUsageLog.id)).where(QAUsageLog.partial_content == True)).scalar() or 0
    
    return {
        "daily_spend_usd": daily_spend,
        "questions_today": len([x for x in recent if x.created_at.strftime('%Y-%m-%d') == today_str]),
        "fetch_distribution": {m: c for m, c in method_dist},
        "partial_content_rate": round(partial_queries / total_queries, 4),
        "recent_sessions": [
            {
                "id": s.id,
                "session_id": s.session_id,
                "turn_number": s.turn_number,
                "method": s.fetch_method,
                "latency_ms": s.fetch_latency_ms,
                "cost_usd": s.total_cost_usd,
                "success": s.success,
                "created_at": s.created_at
            } for s in recent
        ]
    }


