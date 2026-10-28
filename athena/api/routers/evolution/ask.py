"""
Questions to a map (Ask a map), streamed, and the user's past questions.
"""
import json
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import evolution as db
from athena.core import llm, usage
from athena.evolution import ask
from athena.model_server import activity
from athena.api.routers.evolution._common import _built_topic_or_409, _topic_or_404

router = APIRouter()


class AskTurn(BaseModel):
    question: str = Field(..., max_length=1000)
    answer: str = Field(..., max_length=6000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    sections: list[Literal["method", "results", "limitations"]] = Field(default_factory=list, max_length=3)
    history: list[AskTurn] = Field(default_factory=list, max_length=6)


ANSWER_TOKENS = 900


def _sse(payload) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/topics/{slug}/ask")
async def ask_map(slug: str, body: AskRequest, session: Session = Depends(get_db),
                  r: redis_lib.Redis = Depends(get_redis), user: User = Depends(auth.spend("map_qa"))):
    """Streams server-sent events: the numbered sources first, then the answer's tokens, then the saved
    question's id."""
    topic = _built_topic_or_409(session, slug)
    auth.check_tokens(r, user, "map_qa")
    try:
        sources = await run_in_threadpool(ask.retrieve, session, topic, body.question, body.sections)
    except ask.AskUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    chat = ask.messages(topic.name, body.question, sources, [t.model_dump() for t in body.history])
    input_tokens = sum(len(m["content"]) for m in chat) // 4  # an estimate, if the server sends no counts
    model = llm.chat_model("qa")
    public = [s.public() for s in sources]
    topic_id, question, sections = topic.id, body.question, list(body.sections)

    async def generate():
        yield _sse({"sources": public, "abstract_only": sum(s.abstract_only for s in sources)})
        parts: list[str] = []
        counted = None
        call = activity.start("map_qa", model, user_id=user.id)
        try:
            stream = await llm.async_chat_client().chat.completions.create(
                model=model, messages=chat, max_tokens=ANSWER_TOKENS, temperature=0.2, stream=True,
                stream_options={"include_usage": True}, extra_body=llm.chat_extra())
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    counted = chunk.usage  # the last chunk: the served model's own counts
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    parts.append(delta)
                    yield _sse({"token": delta})
            call.tokens(*usage.tokens_of(counted))
            activity.finish(call)
        except Exception as exc:  # the model server went away mid-answer
            activity.finish(call, exc)
            logger.warning(f"Ask {slug}: the answer failed: {exc}")
            yield _sse({"error": f"The model did not answer: {str(exc)[:200]}"})
        finally:
            activity.finish(call, GeneratorExit())  # the page went away mid-answer; a no-op otherwise
        answer = "".join(parts)
        prompt_tokens, output_tokens = usage.tokens_of(counted)
        prompt_tokens, output_tokens = prompt_tokens or input_tokens, output_tokens or len(answer) // 4
        auth.add_tokens(r, user, "map_qa", prompt_tokens + output_tokens)
        if answer or counted:
            await run_in_threadpool(usage.add, "map_qa", model, prompt_tokens, output_tokens, "chat", user.id)
        if answer:
            question_id = await run_in_threadpool(db.save_map_question, user.id, topic_id, question, answer, public,
                                                  sections, prompt_tokens, output_tokens, model)
            yield _sse({"done": True, "question_id": str(question_id)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/topics/{slug}/questions")
def map_questions(slug: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return db.map_questions(session, user.id, _topic_or_404(session, slug).id)


@router.delete("/topics/{slug}/questions", status_code=204)
def clear_map_questions(slug: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    db.delete_map_question(session, user.id, topic_id=_topic_or_404(session, slug).id)


@router.delete("/questions/{question_id}", status_code=204)
def delete_map_question(question_id: UUID, session: Session = Depends(get_db),
                        user: User = Depends(auth.active_user)):
    if not db.delete_map_question(session, user.id, question_id=question_id):
        raise HTTPException(status_code=404, detail="Question not found")
